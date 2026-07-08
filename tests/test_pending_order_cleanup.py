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
