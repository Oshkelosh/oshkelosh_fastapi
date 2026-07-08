"""Tests for native abandoned cart recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.abandoned_cart import process_abandoned_carts
from app.services.site_settings import get_site_settings, update_site_settings
from models.cart import Cart
from models.cart_item import CartItem


class TestAbandonedCart:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self, db_session):
        result = await process_abandoned_carts(db_session)
        assert result.sent == 0
        assert result.scanned == 0

    @pytest.mark.asyncio
    async def test_sends_for_stale_cart(self, db_session, test_user, test_product, test_variant):
        await update_site_settings(
            db_session,
            {
                "abandoned_cart_enabled": True,
                "abandoned_cart_delay_hours": 1,
                "site_url": "https://shop.example.com",
            },
        )

        cart = Cart(
            user_id=test_user.id,
            updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db_session.add(cart)
        await db_session.flush()
        db_session.add(
            CartItem(cart_id=cart.id, product_id=test_product.id, variant_id=test_variant.id, quantity=1)
        )
        await db_session.flush()

        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={"success": True})

        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_email,
        ):
            result = await process_abandoned_carts(db_session)

        assert result.sent == 1
        assert result.scanned == 1
        mock_email.send_email.assert_awaited_once()
        await db_session.refresh(cart)
        assert cart.abandoned_reminder_count == 1
        assert cart.abandoned_reminded_at is not None

    @pytest.mark.asyncio
    async def test_skips_recent_cart(self, db_session, test_user, test_product, test_variant):
        await update_site_settings(
            db_session,
            {"abandoned_cart_enabled": True, "abandoned_cart_delay_hours": 24},
        )

        cart = Cart(user_id=test_user.id)
        db_session.add(cart)
        await db_session.flush()
        db_session.add(
            CartItem(cart_id=cart.id, product_id=test_product.id, variant_id=test_variant.id, quantity=1)
        )
        await db_session.flush()

        result = await process_abandoned_carts(db_session)
        assert result.sent == 0
        assert result.scanned == 0

    @pytest.mark.asyncio
    async def test_cart_abandoned_event_in_catalog(self):
        from app.services.notification_events import get_event

        event = get_event("cart_abandoned")
        assert event is not None
        assert "cart_url" in event.placeholders
