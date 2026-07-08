"""Order notification side effects via notification addons."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.notification_dispatch import dispatch_notification
from app.services.notification_events import ORDER_STATUS_EVENT_MAP

logger = logging.getLogger(__name__)


@dataclass
class CustomerContact:
    email: str | None
    phone: str | None
    push_token: str | None
    full_name: str | None


async def _resolve_customer(session: Any, order: Any) -> CustomerContact | None:
    if order.user_id is not None:
        from models.user import User

        user = await session.get(User, order.user_id)
        if user is None:
            return None
        return CustomerContact(
            email=user.email,
            phone=user.phone,
            push_token=user.push_token,
            full_name=user.full_name,
        )

    shipping = order.shipping_address or {}
    email = shipping.get("email") if isinstance(shipping, dict) else None
    if not email:
        return None
    return CustomerContact(
        email=str(email),
        phone=shipping.get("phone") if isinstance(shipping, dict) else None,
        push_token=None,
        full_name=shipping.get("first_name") if isinstance(shipping, dict) else None,
    )


async def notify_order_placed(session: Any, order: Any) -> None:
    """Send notifications when a pending order is created."""
    contact = await _resolve_customer(session, order)
    if contact is None or not (contact.email or contact.phone or contact.push_token):
        logger.warning("No contact info for order %s; skipping order_placed", order.id)
        return

    await dispatch_notification(
        session,
        "order_placed",
        email=contact.email,
        phone=contact.phone,
        push_token=contact.push_token,
        context={
            "order_id": order.id,
            "customer_name": contact.full_name or "",
            "total_cents": order.total_cents,
        },
    )


async def notify_order_status_change(
    session: Any,
    order: Any,
    old_status: str,
    new_status: str,
) -> None:
    """Send notifications when an order reaches paid, shipped, or delivered."""
    event_key = ORDER_STATUS_EVENT_MAP.get((old_status, new_status))
    if event_key is None:
        return

    contact = await _resolve_customer(session, order)
    if contact is None or not (contact.email or contact.phone or contact.push_token):
        logger.warning("No contact info for order %s; skipping notification", order.id)
        return

    context = {
        "order_id": order.id,
        "customer_name": contact.full_name or "",
        "tracking_url": getattr(order, "tracking_url", None) or "",
        "tracking_number": getattr(order, "tracking_number", None) or "",
        "carrier": getattr(order, "carrier", None) or "",
    }

    await dispatch_notification(
        session,
        event_key,
        email=contact.email,
        phone=contact.phone,
        push_token=contact.push_token,
        context=context,
    )
