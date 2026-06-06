"""Order endpoints.

Provides order creation from cart, order listing, and admin order management.
"""

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import col, func, select

from app.core.dependencies import CurrentUser, get_admin_user, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session
from app.services.commerce import (
    apply_order_status_change,
    compute_order_charges,
    ensure_product_purchasable,
    load_user_cart,
    serialize_order,
)
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from schemas.order import OrderRead, OrderUpdateStatus

router = APIRouter(prefix="/orders", tags=["orders"])

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
    "shipped": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create order from cart",
    description=(
        "Create a new order from the current user's cart. "
        "Inventory is reserved when payment is confirmed (status paid)."
    ),
)
async def create_order(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OrderRead:
    """Create an unpaid order from the authenticated user's cart."""
    user_id = current_user.id

    cart, cart_items = await load_user_cart(session, user_id)
    if cart is None or not cart_items:
        raise ValidationError(message="Cart is empty")

    total_cents = 0
    order_items_data: list[dict] = []

    for item in cart_items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise ValidationError(
                message=f"Product {item.product_id} is no longer available"
            )
        ensure_product_purchasable(product)
        if product.inventory_quantity < item.quantity:
            raise ValidationError(
                message=f"Insufficient inventory for product '{product.name}'"
            )

        line_total = product.price_cents * item.quantity
        total_cents += line_total
        order_items_data.append({
            "product_id": product.id,
            "product_name": product.name,
            "product_sku": product.sku or f"SKU-{product.id}",
            "quantity": item.quantity,
            "unit_price_cents": product.price_cents,
            "total_price_cents": line_total,
        })

    tax_cents, shipping_cents = compute_order_charges(total_cents)

    order = Order(
        user_id=user_id,
        status="pending",
        total_cents=total_cents,
        tax_cents=tax_cents,
        shipping_cents=shipping_cents,
        currency="usd",
    )
    session.add(order)
    await session.flush()
    await session.refresh(order)

    for data in order_items_data:
        oi = OrderItem(
            order_id=order.id,
            product_id=data["product_id"],
            product_name=data["product_name"],
            product_sku=data["product_sku"],
            quantity=data["quantity"],
            unit_price_cents=data["unit_price_cents"],
            total_price_cents=data["total_price_cents"],
        )
        session.add(oi)

    for item in cart_items:
        await session.delete(item)

    await session.flush()
    return await serialize_order(session, order)


@router.post(
    "/{order_id}/checkout",
    summary="Create payment checkout session",
    description="Start checkout with the enabled payment processor for a pending order.",
)
async def checkout_order(
    order_id: int,
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

    payment_addon = require_payment_addon()
    amount = order.total_cents + order.tax_cents + order.shipping_cents
    customer_email = current_user.email or ""

    result = await payment_addon.create_payment(
        amount=amount,
        currency=order.currency,
        order_id=str(order.id),
        customer_email=customer_email,
    )
    return result


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
        "items": [OrderRead.model_validate(o).model_dump() for o in orders],
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
    description="Cancel an order if its status allows cancellation (pending, paid, shipped).",
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

    allowed = VALID_TRANSITIONS.get(order.status, set())
    if "cancelled" not in allowed:
        raise ValidationError(
            message=f"Cannot cancel order with status '{order.status}'"
        )

    await apply_order_status_change(session, order, "cancelled")
    await session.flush()
    return await serialize_order(session, order)


@router.get(
    "/admin",
    response_model=dict,
    summary="List all orders (admin)",
    description="Return a paginated list of all orders. Admin only.",
)
async def admin_list_orders(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="Filter by order status"
    ),
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> dict:
    """List all orders (admin only)."""
    stmt = select(Order)

    if status_filter:
        stmt = stmt.where(col(Order.status) == status_filter)

    stmt = stmt.order_by(Order.created_at.desc())

    total_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total_count: int = total_result.scalar_one() or 0

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    orders = result.scalars().all()

    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return {
        "items": [OrderRead.model_validate(o).model_dump() for o in orders],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.patch(
    "/admin/{order_id}/status",
    response_model=OrderRead,
    summary="Update order status (admin)",
    description="Update the status of an order. Admin only.",
)
async def admin_update_order_status(
    order_id: int,
    body: OrderUpdateStatus,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> OrderRead:
    """Update an order's status (admin only)."""
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFound(resource_name="Order", resource_id=order_id)

    allowed = VALID_TRANSITIONS.get(order.status, set())
    if body.status not in allowed:
        raise ValidationError(
            message=f"Cannot transition from '{order.status}' to '{body.status}'"
        )

    await apply_order_status_change(session, order, body.status)
    await session.flush()
    return await serialize_order(session, order)
