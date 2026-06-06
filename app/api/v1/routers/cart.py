"""Cart endpoints.

Provides a per-user cart with item management and merge functionality.
"""

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.services.commerce import ensure_product_purchasable, load_cart_items, load_user_cart
from app.db.connection import get_session
from models.cart import Cart
from models.cart_item import CartItem
from models.product import Product
from schemas.cart import CartItemAdd, CartItemUpdate, CartReadWithItems, CartItemWithPrice

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


def _compute_cart_totals(cart: Cart) -> dict:
    """Compute subtotal and line totals for a cart."""
    items_with_price: list[CartItemWithPrice] = []
    subtotal_cents = 0

    for item in cart.cart_items:
        if item.product is not None:
            line_total = item.product.price_cents * item.quantity
            subtotal_cents += line_total
            items_with_price.append(
                CartItemWithPrice(
                    id=item.id,
                    cart_id=item.cart_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    unit_price_cents=item.product.price_cents,
                    unit_price=Decimal(item.product.price_cents) / Decimal(100),
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
    cart.cart_items = await load_cart_items(session, cart.id)
    totals = _compute_cart_totals(cart)
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

    cart = await _get_or_create_cart(session, current_user.id)

    # Check if item already exists
    result = await session.execute(
        select(CartItem).where(
            (col(CartItem.cart_id) == cart.id)
            & (col(CartItem.product_id) == body.product_id)
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.quantity += body.quantity
        await session.flush()
        await session.refresh(existing)
        if hasattr(session, "mark_dirty"):
            session.mark_dirty(existing)
        return existing

    item = CartItem(
        cart_id=cart.id,
        product_id=body.product_id,
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


@router.post(
    "/merge",
    response_model=dict,
    summary="Merge session cart with user cart",
    description="Merge items from an anonymous (session) cart into the authenticated user's cart.",
)
async def merge_cart(
    body: "MergeRequest",
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> dict:
    """Merge a session cart's items into the user's cart."""
    session_id = body.session_id

    # Find the session cart
    result = await session.execute(
        select(Cart).where(col(Cart.session_id) == session_id)
    )
    session_cart = result.scalar_one_or_none()
    if session_cart is None:
        return await get_cart(current_user, session)  # type: ignore[misc]

    session_cart.cart_items = await load_cart_items(session, session_cart.id)

    user_cart = await _get_or_create_cart(session, current_user.id)

    for session_item in session_cart.cart_items:
        product = await session.get(Product, session_item.product_id)
        if product is None:
            continue
        try:
            ensure_product_purchasable(product)
        except ValidationError:
            continue

        # Check if user already has this item
        result = await session.execute(
            select(CartItem).where(
                (col(CartItem.cart_id) == user_cart.id)
                & (col(CartItem.product_id) == product.id)
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.quantity += session_item.quantity
            if hasattr(session, "mark_dirty"):
                session.mark_dirty(existing)
        else:
            new_item = CartItem(
                cart_id=user_cart.id,
                product_id=product.id,
                quantity=session_item.quantity,
            )
            session.add(new_item)

        # Remove from session cart
        await session.delete(session_item)

    await session.delete(session_cart)

    # Return merged cart
    user_cart.cart_items = await load_cart_items(session, user_cart.id)
    totals = _compute_cart_totals(user_cart)
    result_data = {
        "id": user_cart.id,
        "session_id": user_cart.session_id,
        "user_id": user_cart.user_id,
        "created_at": user_cart.created_at,
        "updated_at": user_cart.updated_at,
    }
    result_data.update(totals)
    return result_data


# ------------------------------------------------------------------
# Request body for merge
# ------------------------------------------------------------------

class MergeRequest(BaseModel):
    session_id: str
