"""Order endpoints.

Provides order creation from cart, order listing, and admin order management.
"""

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlmodel import col, func, select

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session
from app.services.commerce import (
    apply_order_status_change,
    cart_line_totals,
    ensure_product_purchasable,
    load_user_cart,
    load_variants_for_cart_items,
    release_order_inventory,
    reserve_order_inventory,
    serialize_order,
    validate_status_transition,
)
from app.services.product_variants import ensure_variant_purchasable, get_variant_for_product
from app.services.checkout_pricing import (
    compute_order_total_cents,
    quote_order_charges,
    reprice_pending_order,
)
from app.services.order_idempotency import find_idempotent_order, record_idempotent_order
from app.services.site_settings import get_site_settings
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from models.product_variant import ProductVariant
from models.user import User
from schemas.order import OrderCheckoutUpdate, OrderCreateFromCart, OrderRead
from app.services.user_accounts import resolve_order_shipping_address, resolve_order_billing_address

router = APIRouter(prefix="/orders", tags=["orders"])

logger = logging.getLogger(__name__)


async def _discard_duplicate_order(
    session,
    *,
    order: Order,
    order_items: list[OrderItem],
) -> None:
    """Undo local side effects when an idempotency race loses."""
    await release_order_inventory(session, order_items)
    for item in order_items:
        await session.delete(item)
    await session.delete(order)
    await session.flush()


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create order from cart",
    description=(
        "Create a new order from the current user's cart. "
        "Inventory is reserved immediately; stale pending orders can be cleaned up "
        "by background maintenance jobs."
    ),
)
async def create_order(
    response: Response,
    body: OrderCreateFromCart | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OrderRead:
    """Create an unpaid order from the authenticated user's cart."""
    payload = body or OrderCreateFromCart()
    user_id = current_user.id

    if idempotency_key:
        key = idempotency_key.strip()
        if len(key) < 8 or len(key) > 128:
            raise ValidationError(message="Idempotency-Key must be 8–128 characters")
        existing = await find_idempotent_order(session, user_id=user_id, raw_key=key)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return await serialize_order(session, existing)

    cart, cart_items = await load_user_cart(session, user_id)
    if cart is None or not cart_items:
        raise ValidationError(message="Cart is empty")

    products: dict[int, Product] = {}
    variants: dict[int, ProductVariant] = {}

    for item in cart_items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise ValidationError(
                message=f"Product {item.product_id} is no longer available"
            )
        variant = await get_variant_for_product(session, item.product_id, item.variant_id)
        ensure_product_purchasable(product)
        ensure_variant_purchasable(product, variant, item.quantity)
        products[product.id] = product
        variants[variant.id] = variant

    subtotal_cents, order_items_data = cart_line_totals(cart_items, products, variants)

    user = await session.get(User, user_id)
    if user is None:
        raise NotFound(resource_name="User", resource_id=user_id)

    shipping_address = resolve_order_shipping_address(user, payload.shipping_address)
    billing_address = resolve_order_billing_address(user, payload.billing_address)

    site = await get_site_settings(session)
    charges = await quote_order_charges(
        cart_items,
        products,
        shipping_address,
        site,
        variants,
    )

    order = Order(
        user_id=user_id,
        status="pending",
        total_cents=compute_order_total_cents(subtotal_cents, charges, site),
        tax_cents=charges.tax_cents,
        shipping_cents=charges.shipping_cents,
        currency=payload.currency,
        shipping_address=shipping_address,
        billing_address=billing_address,
        notes=payload.notes,
    )
    session.add(order)
    await session.flush()
    await session.refresh(order)

    order_items: list[OrderItem] = []
    for data in order_items_data:
        oi = OrderItem(
            order_id=order.id,
            product_id=data["product_id"],
            variant_id=data.get("variant_id"),
            variant_snapshot=data.get("variant_snapshot"),
            product_name=data["product_name"],
            product_sku=data["product_sku"],
            quantity=data["quantity"],
            unit_price_cents=data["unit_price_cents"],
            total_price_cents=data["total_price_cents"],
        )
        session.add(oi)
        order_items.append(oi)

    await reserve_order_inventory(session, order_items)

    if idempotency_key:
        dup = await record_idempotent_order(
            session,
            user_id=user_id,
            raw_key=idempotency_key.strip(),
            order_id=order.id,
        )
        if dup is not None:
            await _discard_duplicate_order(session, order=order, order_items=order_items)
            response.status_code = status.HTTP_200_OK
            return await serialize_order(session, dup)

    for item in cart_items:
        await session.delete(item)

    await session.flush()

    from app.services.notifications import notify_order_placed

    await notify_order_placed(session, order)

    response.status_code = status.HTTP_201_CREATED
    return await serialize_order(session, order)


@router.post(
    "/{order_id}/checkout",
    summary="Create payment checkout session",
    description="Start checkout with the enabled payment processor for a pending order.",
)
async def checkout_order(
    order_id: int,
    body: OrderCheckoutUpdate | None = None,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Create a payment session for a pending order."""
    from app.services.addons import require_payment_addon

    user_id = current_user.id
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise NotFound(resource_name="Order", resource_id=order_id)

    if order.status != "pending":
        raise ValidationError(message=f"Cannot checkout order with status '{order.status}'")

    if body is not None:
        if body.shipping_address is not None:
            user = await session.get(User, user_id)
            order.shipping_address = (
                resolve_order_shipping_address(user, body.shipping_address)
                if user
                else body.shipping_address
            )
        if body.billing_address is not None:
            order.billing_address = body.billing_address

    site = await get_site_settings(session)
    await reprice_pending_order(session, order, site)

    payment_addon = require_payment_addon()
    customer_email = current_user.email or ""

    from app.services.payment_checkout import start_checkout

    return await start_checkout(
        session,
        order,
        payment_addon,
        customer_email=customer_email,
    )


@router.get(
    "",
    response_model=dict,
    summary="List user's orders",
    description="Return a paginated list of the current user's orders.",
)
async def list_orders(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="Filter by order status"
    ),
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List the authenticated user's orders."""
    user_id = current_user.id
    stmt = select(Order).where(col(Order.user_id) == user_id)

    if status_filter:
        stmt = stmt.where(col(Order.status) == status_filter)

    stmt = stmt.order_by(Order.created_at.desc())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total_count: int = total_result.scalar_one() or 0

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    orders = result.scalars().all()

    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return {
        "items": [
            (await serialize_order(session, o)).model_dump() for o in orders
        ],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get(
    "/{order_id}",
    response_model=OrderRead,
    summary="Get order detail",
    description="Return the full detail of a single order belonging to the current user.",
)
async def get_order(
    order_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OrderRead:
    """Return a single order's detail."""
    user_id = current_user.id
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise NotFound(resource_name="Order", resource_id=order_id)
    return await serialize_order(session, order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderRead,
    summary="Cancel order",
    description="Cancel a pending order owned by the current user.",
)
async def cancel_order(
    order_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OrderRead:
    """Cancel an order if the current status allows it."""
    user_id = current_user.id
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise NotFound(resource_name="Order", resource_id=order_id)

    if order.status != "pending":
        raise ValidationError(message="Only pending orders can be cancelled by customers")

    validate_status_transition(order.status, "cancelled")

    await apply_order_status_change(session, order, "cancelled")
    await session.flush()
    return await serialize_order(session, order)
