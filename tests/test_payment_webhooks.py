"""Tests for payment webhook idempotency and processing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from app.services.payment_webhooks import process_payment_webhook
from models.order import Order
from models.processed_webhook_event import ProcessedWebhookEvent
from schemas.payment import PaymentWebhookOutcome


class _MockPaymentAddon:
    addon_id = "mock_pay"

    def __init__(self) -> None:
        self.parse_webhook = AsyncMock(
            return_value=PaymentWebhookOutcome(
                handled=True,
                event_type="payment.completed",
                order_id=1,
                mark_paid=True,
                payment_id="pi_test",
            )
        )

    def webhook_event_id(self, payload: dict) -> str:
        return payload.get("id", "")


@pytest.mark.asyncio
async def test_webhook_duplicate_event_is_idempotent(db_session):
    order = Order(
        user_id=None,
        status="pending",
        total_cents=1000,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    addon = _MockPaymentAddon()
    addon.parse_webhook.return_value = PaymentWebhookOutcome(
        handled=True,
        event_type="payment.completed",
        order_id=order.id,
        mark_paid=True,
        payment_id="pi_test",
    )

    payload = {"id": "evt_123", "type": "payment.completed"}
    first = await process_payment_webhook(
        db_session,
        addon,
        payload=payload,
        signature="sig",
        event_id="evt_123",
    )
    assert first["handled"] is True
    assert first.get("duplicate") is not True

    second = await process_payment_webhook(
        db_session,
        addon,
        payload=payload,
        signature="sig",
        event_id="evt_123",
    )
    assert second == {"handled": True, "duplicate": True}

    result = await db_session.execute(select(ProcessedWebhookEvent))
    events = result.scalars().all()
    assert len(events) == 1
