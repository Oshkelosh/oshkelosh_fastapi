"""Order notification side effects via notification addons."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.addons import get_notification_addon

logger = logging.getLogger(__name__)

_STATUS_MESSAGES = {
    ("pending", "paid"): (
        "Order confirmation",
        "Thank you for your order #{order_id}. Your payment was received.",
    ),
    ("paid", "shipped"): (
        "Your order has shipped",
        "Order #{order_id} is on its way.",
    ),
    ("shipped", "delivered"): (
        "Order delivered",
        "Order #{order_id} has been delivered. Thank you for shopping with us!",
    ),
}


async def notify_order_status_change(
    session: Any,
    order: Any,
    old_status: str,
    new_status: str,
) -> None:
    """Send email when an order reaches paid, shipped, or delivered."""
    addon = get_notification_addon()
    if addon is None:
        return

    template = _STATUS_MESSAGES.get((old_status, new_status))
    if template is None:
        return

    email = await _resolve_customer_email(session, order)
    if not email:
        logger.warning("No email for order %s; skipping notification", order.id)
        return

    from app.services.site_settings import get_site_settings

    site = await get_site_settings(session)
    store_prefix = f"[{site.store_name}] " if site.store_name else ""

    subject, body_template = template
    subject = f"{store_prefix}{subject}"
    body = body_template.format(order_id=order.id)
    try:
        result = await addon.send_email(email, subject, body)
        if not result.get("success", True):
            logger.warning(
                "Notification failed for order %s: %s",
                order.id,
                result.get("error", "unknown"),
            )
    except Exception:
        logger.exception("Notification addon error for order %s", order.id)


async def _resolve_customer_email(session: Any, order: Any) -> Optional[str]:
    if order.user_id is None:
        return None
    from models.user import User

    user = await session.get(User, order.user_id)
    return user.email if user else None
