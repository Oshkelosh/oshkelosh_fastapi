"""Tests for lifecycle event fan-out and commerce hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lifecycle_events import (
    EVENT_ORDER_PAID,
    EVENT_USER_REGISTERED,
    build_order_paid_payload,
    build_user_registered_payload,
    dispatch_lifecycle_event,
)
from app.services.tool_discovery import build_purchase_payload, dispatch_commerce_event


class TestLifecycleEvents:
    def test_build_user_registered_payload(self, test_user):
        payload = build_user_registered_payload(test_user)
        assert payload["user_id"] == test_user.id
        assert payload["email"] == test_user.email

    def test_build_order_paid_payload(self, test_user):
        order = MagicMock()
        order.id = 10
        order.user_id = test_user.id
        order.status = "paid"
        order.total_cents = 5000
        order.tax_cents = 400
        order.shipping_cents = 500
        order.currency = "USD"

        payload = build_order_paid_payload(order, test_user)
        assert payload["order_id"] == 10
        assert payload["email"] == test_user.email

    @pytest.mark.asyncio
    async def test_dispatch_lifecycle_event_calls_tools(self, db_session):
        mock_tool = MagicMock()
        mock_tool.addon_id = "crm"
        mock_tool.on_lifecycle_event = AsyncMock()

        with patch(
            "app.services.lifecycle_events.get_enabled_tools",
            return_value=[mock_tool],
        ):
            await dispatch_lifecycle_event(
                EVENT_USER_REGISTERED,
                {"user_id": 1, "email": "a@b.com"},
            )

        mock_tool.on_lifecycle_event.assert_awaited_once_with(
            EVENT_USER_REGISTERED,
            {"user_id": 1, "email": "a@b.com"},
        )

    @pytest.mark.asyncio
    async def test_dispatch_commerce_event_calls_tools(self):
        mock_tool = MagicMock()
        mock_tool.addon_id = "pixel"
        mock_tool.on_commerce_event = AsyncMock()

        order = MagicMock()
        order.id = 3
        order.user_id = 1
        order.total_cents = 1000
        order.tax_cents = 0
        order.shipping_cents = 0
        order.currency = "USD"

        with patch(
            "app.services.tool_discovery.get_enabled_tools",
            return_value=[mock_tool],
        ):
            await dispatch_commerce_event(
                "purchase",
                build_purchase_payload(order),
            )

        mock_tool.on_commerce_event.assert_awaited_once()
        assert mock_tool.on_commerce_event.await_args.args[0] == "purchase"
