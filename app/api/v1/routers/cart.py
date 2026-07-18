"""Cart endpoints.

Provides a per-user cart with item management and merge functionality.
"""

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.services.commerce import (
    ensure_product_purchasable,
    load_cart_items,
    load_products_for_cart_items,
    load_user_cart,
    load_variants_for_cart_items,
)
from app.db.connection import get_session
from models.cart import Cart
from models.cart_item import CartItem
from models.product import Product
from models.product_variant import ProductVariant
from app.services.product_variants import ensure_variant_purchasable, get_variant_for_product
from app.services.checkout_pricing import quote_order_charges
from app.services.currency import (
    client_country_from_request,
    cookie_currency_preference,
    preferred_currency_hint,
    shop_currency_from_settings,
)
from app.services.pricing.shipping import SiteShippingQuoter
from app.services.site_settings import get_site_settings
from schemas.cart import (
    CartItemAdd,
    CartItemShippingEstimateResponse,
    CartItemUpdate,
    CartQuoteRequest,
    CartQuoteResponse,
    CartReadWithItems,
    CartItemWithPrice,
)

router = APIRouter(prefix="/cart", tags=["cart"])

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _get_or_create_cart(
    session,
    user_id: int,
) -> Cart:
    """Return the user's active cart, creating one if it doesn't exist."""
    result = await session.execute(
        select(Cart).where(col(Cart.user_id) == user_id)
    )
    cart = result.scalar_one_or_none()
    if cart is None:
        cart = Cart(user_id=user_id)
        session.add(cart)
        await session.flush()
        await session.refresh(cart)
    return cart


def _compute_cart_totals(
    cart_items: list[CartItem],
    products: dict[int, Product],
    variants: dict[int, ProductVariant],
) -> dict:
    """Compute subtotal and line totals for a cart."""
    items_with_price: list[CartItemWithPrice] = []
    subtotal_cents = 0

    for item in cart_items:
        product = products.get(item.product_id)
        variant = variants.get(item.variant_id)
        if product is None or variant is None:
            continue
        line_total = variant.price_cents * item.quantity
        subtotal_cents += line_total
        items_with_price.append(
            CartItemWithPrice(
                id=item.id,
                cart_id=item.cart_id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                created_at=item.created_at,
                updated_at=item.updated_at,
                product_name=product.name,
                variant_title=variant.title,
                unit_price_cents=variant.price_cents,
                unit_price=Decimal(variant.price_cents) / Decimal(100),
                line_total_cents=line_total,
                line_total=Decimal(line_total) / Decimal(100),
            )
        )

    return {
        "items": [i.model_dump() for i in items_with_price],
        "subtotal_cents": subtotal_cents,
        "subtotal": Decimal(subtotal_cents) / Decimal(100),
    }


# ------------------------------------------------------------------
# Public endpoints (require auth)
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=dict,
    summary="Get user cart",
    description="Return the current user's shopping cart with computed totals.",
)
async def get_cart(
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> dict:
    """Get or create the current user's cart."""
    cart = await _get_or_create_cart(session, current_user.id)
    cart_items = await load_cart_items(session, cart.id)
    products = await load_products_for_cart_items(session, cart_items)
    variants = await load_variants_for_cart_items(session, cart_items)
    totals = _compute_cart_totals(cart_items, products, variants)
    result = {
        "id": cart.id,
        "session_id": cart.session_id,
        "user_id": cart.user_id,
        "created_at": cart.created_at,
        "updated_at": cart.updated_at,
    }
    result.update(totals)
    return result


@router.post(
    "/quote",
    response_model=CartQuoteResponse,
    summary="Quote cart tax and shipping",
    description=(
        "Return estimated tax and shipping for the current cart using Site Settings "
        "rules, optional supplier shipping quotes, and any enabled tax tool addon."
    ),
)
async def quote_cart(
    request: Request,
    body: CartQuoteRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> CartQuoteResponse:
    """Preview checkout charges before order creation."""
    payload = body or CartQuoteRequest()
    cart, cart_items = await load_user_cart(session, current_user.id)
    if cart is None or not cart_items:
        raise ValidationError(message="Cart is empty")

    products = await load_products_for_cart_items(session, cart_items)
    variants = await load_variants_for_cart_items(session, cart_items)
    totals = _compute_cart_totals(cart_items, products, variants)
    site = await get_site_settings(session)
    shop_currency = shop_currency_from_settings(site)
    charges = await quote_order_charges(
        cart_items,
        products,
        payload.shipping_address,
        site,
        variants,
        shipping_selections=payload.shipping_selections,
        currency=shop_currency,
    )
    address_country = None
    if isinstance(payload.shipping_address, dict):
        address_country = payload.shipping_address.get("country")
    preferred = preferred_currency_hint(
        shop_currency=shop_currency,
        address_country=address_country,
        ip_country=client_country_from_request(request),
        cookie_preference=cookie_currency_preference(request),
    )
    from app.services.checkout_pricing import compute_order_total_cents

    return CartQuoteResponse(
        subtotal_cents=totals["subtotal_cents"],
        tax_cents=charges.tax_cents,
        shipping_cents=charges.shipping_cents,
        total_cents=compute_order_total_cents(totals["subtotal_cents"], charges, site),
        tax_inclusive=bool(site.tax_inclusive),
        tax_source=charges.tax_source,
        currency=shop_currency,
        preferred_currency=preferred,
        shipping_breakdown=charges.shipping_breakdown,
    )


@router.post(
    "/items/{item_id}/shipping-estimate",
    response_model=CartItemShippingEstimateResponse,
    summary="Estimate shipping for one cart item",
    description=(
        "Return a standalone shipping estimate for a single cart line using the "
        "user's saved shipping address. Not used for checkout totals."
    ),
)
async def estimate_item_shipping(
    item_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> CartItemShippingEstimateResponse:
    """Quote shipping for one cart line in isolation."""
    address = current_user.default_shipping_address
    if not address:
        raise ValidationError(message="A saved shipping address is required for estimates")

    cart, cart_items = await load_user_cart(session, current_user.id)
    if cart is None:
        raise NotFound(resource_name="CartItem", resource_id=item_id)

    item = next((row for row in cart_items if row.id == item_id), None)
    if item is None:
        raise NotFound(resource_name="CartItem", resource_id=item_id)

    products = await load_products_for_cart_items(session, [item])
    variants = await load_variants_for_cart_items(session, [item])
    if item.product_id not in products or item.variant_id not in variants:
        raise NotFound(resource_name="CartItem", resource_id=item_id)

    site = await get_site_settings(session)
    shop_currency = shop_currency_from_settings(site)
    quote = await SiteShippingQuoter(site).quote(
        [item],
        products,
        address,
        variants,
        currency=shop_currency,
    )
    row = quote.breakdown[0] if quote.breakdown else {}
    return CartItemShippingEstimateResponse(
        cart_item_id=item.id,
        shipping_cents=quote.shipping_cents,
        currency=shop_currency,
        label=str(row.get("label") or ""),
        source=str(row.get("source") or ""),
    )


@router.post(
    "/items",
    response_model=CartItem,
    status_code=status.HTTP_201_CREATED,
    summary="Add item to cart",
    description="Add a product to the current user's cart. Creates or updates an existing line item.",
)
async def add_item(
    body: CartItemAdd,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> CartItem:
    """Add a product item to the current user's cart."""
    # Check product exists
    product = await session.get(Product, body.product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=body.product_id)
    ensure_product_purchasable(product)
    variant = await get_variant_for_product(session, body.product_id, body.variant_id)
    ensure_variant_purchasable(product, variant, body.quantity)

    cart = await _get_or_create_cart(session, current_user.id)

    result = await session.execute(
        select(CartItem).where(
            (col(CartItem.cart_id) == cart.id)
            & (col(CartItem.variant_id) == body.variant_id)
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        new_quantity = existing.quantity + body.quantity
        ensure_variant_purchasable(product, variant, new_quantity)
        existing.quantity = new_quantity
        await session.flush()
        await session.refresh(existing)
        if hasattr(session, "mark_dirty"):
            session.mark_dirty(existing)
        return existing

    item = CartItem(
        cart_id=cart.id,
        product_id=body.product_id,
        variant_id=body.variant_id,
        quantity=body.quantity,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


@router.patch(
    "/items/{item_id}",
    response_model=CartItem,
    summary="Update cart item quantity",
    description="Update the quantity of a cart item.",
)
async def update_item(
    item_id: int,
    body: CartItemUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> CartItem:
    """Update the quantity of a cart item."""
    cart = await _get_or_create_cart(session, current_user.id)

    result = await session.execute(
        select(CartItem).where(
            (col(CartItem.id) == item_id)
            & (col(CartItem.cart_id) == cart.id)
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFound(resource_name="CartItem", resource_id=item_id)

    product = await session.get(Product, item.product_id)
    variant = await session.get(ProductVariant, item.variant_id)
    if product is not None and variant is not None:
        ensure_variant_purchasable(product, variant, body.quantity)

    item.quantity = body.quantity
    await session.flush()
    await session.refresh(item)
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(item)
    return item


@router.delete(
    "/items/{item_id}",
    response_model=dict,
    summary="Remove cart item",
    description="Remove a single item from the cart.",
)
async def remove_item(
    item_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> dict:
    """Remove a cart item by ID."""
    cart = await _get_or_create_cart(session, current_user.id)

    result = await session.execute(
        select(CartItem).where(
            (col(CartItem.id) == item_id)
            & (col(CartItem.cart_id) == cart.id)
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFound(resource_name="CartItem", resource_id=item_id)

    await session.delete(item)
    return {"message": "Item removed from cart"}


@router.delete(
    "/items",
    response_model=dict,
    summary="Remove all cart items",
    description="Remove all items from the current user's cart.",
)
async def clear_cart(
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> dict:
    """Remove all items from the current user's cart."""
    cart = await _get_or_create_cart(session, current_user.id)

    result = await session.execute(
        select(CartItem).where(col(CartItem.cart_id) == cart.id)
    )
    items = result.scalars().all()
    for item in items:
        await session.delete(item)

    return {"message": "Cart cleared"}
