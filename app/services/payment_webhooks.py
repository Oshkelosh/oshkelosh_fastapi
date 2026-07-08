"""Generic payment webhook orchestration (processor-agnostic)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.exc import IntegrityError

from app.addons.payments.base import PaymentAddon
from app.services.payments import complete_order_payment, record_late_cancelled_payment
from models.order import Order
from models.processed_webhook_event import ProcessedWebhookEvent


async def process_payment_webhook(
    session: Any,
    addon: PaymentAddon,
    *,
    payload: dict[str, Any],
    signature: str,
    event_id: str,
    provider: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent webhook handling: parse via addon, apply core side effects."""
    provider_id = provider or addon.addon_id
    outcome = await addon.parse_webhook(payload, signature)
    if not outcome.handled:
        return {"handled": False, "error": outcome.error or "Webhook not handled"}

    record = ProcessedWebhookEvent(
        event_id=event_id,
        provider=provider_id,
        event_type="processing",
    )
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError:
        return {"handled": True, "duplicate": True}

    record.event_type = outcome.event_type or "processed"
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(record)

    if outcome.mark_paid and outcome.order_id is not None:
        order = await session.get(Order, outcome.order_id)
        if order is not None:
            if order.status == "pending":
                await complete_order_payment(
                    session,
                    outcome.order_id,
                    processor_id=provider_id,
                    customer_id=outcome.customer_id,
                    payment_id=outcome.payment_id,
                    payment_charge_id=outcome.payment_charge_id,
                )
            elif order.status == "cancelled":
                await record_late_cancelled_payment(
                    session,
                    order,
                    processor_id=provider_id,
                    event_id=event_id,
                    payment_id=outcome.payment_id,
                    payment_charge_id=outcome.payment_charge_id,
                )

    return {
        "handled": True,
        "event_type": record.event_type,
        "event_id": outcome.event_id or event_id,
    }
