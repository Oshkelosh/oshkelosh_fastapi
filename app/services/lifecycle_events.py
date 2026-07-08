"""Lifecycle event fan-out for marketing and CRM tool addons."""

from __future__ import annotations

import logging
from typing import Any

from app.services.addons import get_enabled_tools

logger = logging.getLogger(__name__)

EVENT_USER_REGISTERED = "user.registered"
EVENT_ORDER_PAID = "order.paid"
EVENT_CART_ABANDONED = "cart.abandoned"


def build_user_registered_payload(user: Any) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "verified": bool(getattr(user, "verified", False)),
    }


def build_order_paid_payload(order: Any, user: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "order_id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "total_cents": order.total_cents,
        "tax_cents": order.tax_cents,
        "shipping_cents": order.shipping_cents,
        "currency": order.currency,
    }
    if user is not None:
        payload["email"] = user.email
        payload["full_name"] = user.full_name
    return payload


def build_cart_abandoned_payload(
    *,
    user: Any,
    cart_id: int,
    subtotal_cents: int,
    cart_url: str,
) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "cart_id": cart_id,
        "email": user.email,
        "full_name": user.full_name,
        "subtotal_cents": subtotal_cents,
        "cart_url": cart_url,
    }


async def dispatch_lifecycle_event(
    session: Any,
    event_key: str,
    payload: dict[str, Any],
) -> None:
    """Notify all enabled tool addons of a lifecycle event."""
    del session  # reserved for future persistence / audit
    for tool in get_enabled_tools():
        handler = getattr(tool, "on_lifecycle_event", None)
        if handler is None:
            continue
        try:
            await tool.on_lifecycle_event(event_key, payload)
        except Exception:
            logger.exception(
                "Tool '%s' failed handling lifecycle event '%s'",
                tool.addon_id,
                event_key,
            )
