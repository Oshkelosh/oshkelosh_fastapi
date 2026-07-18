"""Generic payment checkout orchestration (processor-agnostic)."""

from __future__ import annotations

from typing import Any

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import build_checkout_redirect_urls
from app.services.site_settings import get_site_settings
from models.order import Order


async def start_checkout(
    session: Any,
    order: Order,
    payment_addon: PaymentAddon,
    *,
    customer_email: str,
) -> dict[str, Any]:
    """Call the active payment addon and persist payment fields on the order."""
    amount = order.total_cents
    site = await get_site_settings(session)
    return_url, cancel_url = build_checkout_redirect_urls(site, order.id)

    result = await payment_addon.create_payment(
        amount=amount,
        currency=order.currency,
        order_id=str(order.id),
        customer_email=customer_email,
        return_url=return_url,
        cancel_url=cancel_url,
    )

    if not result.get("success", False):
        from app.core.exceptions import ValidationError

        raise ValidationError(
            message=(
                f"Payment provider '{payment_addon.addon_id}' could not create a "
                "checkout session. Please try again."
            )
        )

    order.payment_processor_id = payment_addon.addon_id
    if result.get("payment_id"):
        order.payment_id = str(result["payment_id"])
    elif result.get("session_id"):
        order.payment_id = str(result["session_id"])

    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)
    await session.flush()

    return result
