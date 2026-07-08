"""Payment completion helpers for payment addons and webhooks."""

from __future__ import annotations

from typing import Any, Optional

from app.core.exceptions import NotFound, ValidationError
from app.services.commerce import VALID_TRANSITIONS, apply_order_status_change
from app.services.user_accounts import link_payment_customer
from models.order import Order


async def complete_order_payment(
    session: Any,
    order_id: int,
    *,
    processor_id: str,
    customer_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    payment_charge_id: Optional[str] = None,
) -> Order:
    """Mark an order paid and optionally link processor payment identifiers."""
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFound(resource_name="Order", resource_id=order_id)

    if order.status == "paid":
        if payment_id:
            order.payment_id = payment_id
        if payment_charge_id:
            order.payment_charge_id = payment_charge_id
        if processor_id:
            order.payment_processor_id = processor_id
        if order.user_id and customer_id:
            await link_payment_customer(session, order.user_id, processor_id, customer_id)
        return order

    allowed = VALID_TRANSITIONS.get(order.status, set())
    if "paid" not in allowed:
        raise ValidationError(
            message=f"Cannot mark order {order_id} paid from status '{order.status}'"
        )

    order.payment_processor_id = processor_id
    if payment_id:
        order.payment_id = payment_id
    if payment_charge_id:
        order.payment_charge_id = payment_charge_id

    await apply_order_status_change(session, order, "paid")

    if order.user_id and customer_id:
        await link_payment_customer(session, order.user_id, processor_id, customer_id)

    from models.user import User

    from app.services.lifecycle_events import (
        EVENT_ORDER_PAID,
        build_order_paid_payload,
        dispatch_lifecycle_event,
    )
    from app.services.tool_discovery import build_purchase_payload, dispatch_commerce_event

    user = await session.get(User, order.user_id) if order.user_id else None
    await dispatch_lifecycle_event(
        session,
        EVENT_ORDER_PAID,
        build_order_paid_payload(order, user),
    )
    await dispatch_commerce_event("purchase", build_purchase_payload(order, user))

    return order
