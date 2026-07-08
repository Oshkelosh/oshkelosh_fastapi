"""Tests for payment webhook idempotency and processing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from app.services.payment_webhooks import process_payment_webhook
from models.audit_log import AuditLog
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


@pytest.mark.asyncio
async def test_webhook_retry_after_unhandled_failure_can_succeed(db_session):
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
    addon.parse_webhook.side_effect = [
        PaymentWebhookOutcome(
            handled=False,
            event_type="payment.completed",
            order_id=order.id,
            mark_paid=False,
            error="bad signature",
        ),
        PaymentWebhookOutcome(
            handled=True,
            event_type="payment.completed",
            order_id=order.id,
            mark_paid=True,
            payment_id="pi_retry",
        ),
    ]

    payload = {"id": "evt_retry", "type": "payment.completed"}
    first = await process_payment_webhook(
        db_session,
        addon,
        payload=payload,
        signature="bad-sig",
        event_id="evt_retry",
    )
    assert first == {"handled": False, "error": "bad signature"}

    result = await db_session.execute(select(ProcessedWebhookEvent))
    assert result.scalars().all() == []

    second = await process_payment_webhook(
        db_session,
        addon,
        payload=payload,
        signature="good-sig",
        event_id="evt_retry",
    )
    assert second["handled"] is True
    assert second.get("duplicate") is not True

    await db_session.flush()
    await db_session.refresh(order)
    assert order.status == "paid"

    result = await db_session.execute(select(ProcessedWebhookEvent))
    events = result.scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_late_payment_for_cancelled_order_marks_refund_review(db_session):
    order = Order(
        user_id=None,
        status="cancelled",
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
        payment_id="pi_late",
        payment_charge_id="ch_late",
    )

    result = await process_payment_webhook(
        db_session,
        addon,
        payload={"id": "evt_late", "type": "payment.completed"},
        signature="sig",
        event_id="evt_late",
    )
    assert result["handled"] is True

    await db_session.flush()
    await db_session.refresh(order)
    assert order.status == "cancelled"
    assert order.payment_id == "pi_late"
    assert order.payment_charge_id == "ch_late"
    assert "Refund review required" in (order.notes or "")

    audit_rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(row.action == "reconcile" and row.resource_id == str(order.id) for row in audit_rows)
