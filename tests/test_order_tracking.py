"""Tests for order shipment tracking fields."""

from __future__ import annotations

import pytest

from app.services.commerce import apply_order_tracking, apply_order_status_change
from app.services.notifications import notify_order_status_change
from models.order import Order


class TestOrderTrackingFields:
    def test_apply_order_tracking_strips_empty(self):
        order = Order(
            user_id=1,
            status="paid",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        apply_order_tracking(
            order,
            tracking_number=" 1Z999  ",
            tracking_url="https://track.example/1Z999",
            carrier=" UPS ",
        )
        assert order.tracking_number == "1Z999"
        assert order.tracking_url == "https://track.example/1Z999"
        assert order.carrier == "UPS"

    @pytest.mark.asyncio
    async def test_shipped_notification_includes_tracking_url(self, db_session, test_user):
        from unittest.mock import AsyncMock, patch

        order = Order(
            user_id=test_user.id,
            status="paid",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
            tracking_url="https://track.example/pkg-1",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        mock_dispatch = AsyncMock()
        with patch(
            "app.services.notifications.dispatch_notification",
            mock_dispatch,
        ):
            await notify_order_status_change(db_session, order, "paid", "shipped")

        mock_dispatch.assert_awaited_once()
        assert mock_dispatch.await_args.kwargs["context"]["tracking_url"] == (
            "https://track.example/pkg-1"
        )

    @pytest.mark.asyncio
    async def test_admin_status_update_persists_tracking(self, client, test_user, db_session):
        from app.main import app
        from sqlmodel import select
        from tests.test_audit_fixes import _admin_session

        app.state.needs_setup = False
        order = Order(
            user_id=test_user.id,
            status="paid",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        cookies, csrf = _admin_session(test_user.id)
        resp = await client.post(
            f"/admin/orders/{order.id}/status",
            data={
                "status": "shipped",
                "tracking_number": "PKG123",
                "tracking_url": "https://carrier.example/PKG123",
                "carrier": "DHL",
                "csrf_token": csrf,
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 302

        result = await db_session.execute(select(Order).where(Order.id == order.id))
        updated = result.scalar_one()
        assert updated.status == "shipped"
        assert updated.tracking_number == "PKG123"
        assert updated.tracking_url == "https://carrier.example/PKG123"
        assert updated.carrier == "DHL"
