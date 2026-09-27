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


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _contact_from_address(address: Any) -> CustomerContact:
    if not isinstance(address, dict):
        return CustomerContact(email=None, phone=None, push_token=None, full_name=None)
    return CustomerContact(
        email=_nonempty(address.get("email")),
        phone=_nonempty(address.get("phone")),
        push_token=None,
        full_name=_nonempty(address.get("full_name"))
        or _nonempty(address.get("first_name")),
    )


def _merge_contact(*contacts: CustomerContact) -> CustomerContact:
    email = next((c.email for c in contacts if c.email), None)
    phone = next((c.phone for c in contacts if c.phone), None)
    push_token = next((c.push_token for c in contacts if c.push_token), None)
    full_name = next((c.full_name for c in contacts if c.full_name), None)
    return CustomerContact(
        email=email, phone=phone, push_token=push_token, full_name=full_name
    )


async def _resolve_customer(session: Any, order: Any) -> CustomerContact | None:
    shipping = _contact_from_address(getattr(order, "shipping_address", None))
    billing = _contact_from_address(getattr(order, "billing_address", None))

    user_contact: CustomerContact | None = None
    if order.user_id is not None:
        from models.user import User

        user = await session.get(User, order.user_id)
        if user is not None:
            user_contact = CustomerContact(
                email=_nonempty(user.email),
                phone=_nonempty(user.phone),
                push_token=_nonempty(user.push_token),
                full_name=_nonempty(user.full_name),
            )

    merged = (
        _merge_contact(user_contact, shipping, billing)
        if user_contact is not None
        else _merge_contact(shipping, billing)
    )
    if not (merged.email or merged.phone or merged.push_token):
        return None
    return merged


async def notify_order_placed(session: Any, order: Any) -> None:
    """Send notifications when a pending order is created."""
    try:
        contact = await _resolve_customer(session, order)
        if contact is None:
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
    except Exception:
        logger.exception("Order placed notification failed for order %s", order.id)


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

    try:
        contact = await _resolve_customer(session, order)
        if contact is None:
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
    except Exception:
        logger.exception(
            "Order status notification failed for order %s (%s)",
            order.id,
            event_key,
        )
