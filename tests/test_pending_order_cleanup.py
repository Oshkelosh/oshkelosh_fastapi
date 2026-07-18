"""Tests for stale pending order cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.pending_order_cleanup import process_stale_pending_orders
from models.order import Order
from models.order_item import OrderItem


@pytest.mark.asyncio
async def test_stale_pending_order_is_cancelled(db_session, test_product, monkeypatch):
    monkeypatch.setattr("app.services.pending_order_cleanup.settings.pending_order_expiry_hours", 24)

    order = Order(
        user_id=None,
        status="pending",
        total_cents=500,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            product_id=test_product.id,
            product_name=test_product.name,
            product_sku=test_product.sku or "SKU-1",
            quantity=1,
            unit_price_cents=test_product.price_cents,
            total_price_cents=test_product.price_cents,
        )
    )
    await db_session.flush()

    result = await process_stale_pending_orders(db_session)
    assert result.cancelled >= 1
    await db_session.refresh(order)
    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_stale_pending_order_without_items_is_cancelled(db_session, monkeypatch):
    monkeypatch.setattr("app.services.pending_order_cleanup.settings.pending_order_expiry_hours", 24)

    order = Order(
        user_id=None,
        status="pending",
        total_cents=500,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db_session.add(order)
    await db_session.flush()

    result = await process_stale_pending_orders(db_session)
    assert result.cancelled == 1
    await db_session.refresh(order)
    assert order.status == "cancelled"


def _stale_order_with_payment() -> Order:
    return Order(
        user_id=None,
        status="pending",
        total_cents=500,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
        payment_processor_id="fakepsp",
        payment_id="pi_stale",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )


class _FakePsp:
    is_enabled = True

    def __init__(self, status: str):
        self._status = status

    async def get_payment_status(self, payment_id: str):
        return {"payment_id": payment_id, "status": self._status}


@pytest.mark.asyncio
async def test_charged_pending_order_is_reconciled_not_cancelled(db_session, monkeypatch):
    monkeypatch.setattr("app.services.pending_order_cleanup.settings.pending_order_expiry_hours", 24)
    order = _stale_order_with_payment()
    db_session.add(order)
    await db_session.flush()

    monkeypatch.setattr(
        "app.addons.registry.addon_registry.get", lambda addon_id: _FakePsp("succeeded")
    )
    result = await process_stale_pending_orders(db_session)
    assert result.reconciled == 1
    assert result.cancelled == 0
    await db_session.refresh(order)
    assert order.status == "paid"


@pytest.mark.asyncio
async def test_unknown_payment_status_skips_cancellation(db_session, monkeypatch):
    monkeypatch.setattr("app.services.pending_order_cleanup.settings.pending_order_expiry_hours", 24)
    order = _stale_order_with_payment()
    db_session.add(order)
    await db_session.flush()

    monkeypatch.setattr(
        "app.addons.registry.addon_registry.get", lambda addon_id: _FakePsp("error")
    )
    result = await process_stale_pending_orders(db_session)
    assert result.skipped == 1
    assert result.cancelled == 0
    await db_session.refresh(order)
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_unpaid_checkout_session_is_still_cancelled(db_session, monkeypatch):
    monkeypatch.setattr("app.services.pending_order_cleanup.settings.pending_order_expiry_hours", 24)
    order = _stale_order_with_payment()
    db_session.add(order)
    await db_session.flush()

    monkeypatch.setattr(
        "app.addons.registry.addon_registry.get", lambda addon_id: _FakePsp("open")
    )
    result = await process_stale_pending_orders(db_session)
    assert result.cancelled == 1
    await db_session.refresh(order)
    assert order.status == "cancelled"
