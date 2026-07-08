"""Tests for notification events, templates, dispatch, and admin pages."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.notification_dispatch import dispatch_notification
from app.services.notification_templates import render_notification, save_template
from models.order import Order


class TestNotificationTemplates:
    @pytest.mark.asyncio
    async def test_render_order_confirmation_defaults(self, db_session):
        rendered = await render_notification(
            db_session,
            "order_confirmation",
            "email",
            {"order_id": 42, "store_name": "Test Shop", "customer_name": "Jane"},
            store_prefix="[Test Shop] ",
        )
        assert rendered is not None
        assert "[Test Shop] Order confirmation" == rendered.subject
        assert "42" in rendered.body

    @pytest.mark.asyncio
    async def test_save_and_render_custom_template(self, db_session):
        await save_template(
            db_session,
            "order_shipped",
            "sms",
            subject="Shipped",
            body="Order {order_id} shipped to you.",
            is_enabled=True,
        )
        rendered = await render_notification(
            db_session,
            "order_shipped",
            "sms",
            {"order_id": 7},
        )
        assert rendered is not None
        assert "7" in rendered.body


class TestNotificationDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_email_and_sms(self, db_session, test_user):
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={"success": True})
        mock_sms = AsyncMock()
        mock_sms.send_sms = AsyncMock(return_value={"success": True})

        def _channel_addon(channel: str):
            if channel == "email":
                return mock_email
            if channel == "sms":
                return mock_sms
            return None

        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            side_effect=_channel_addon,
        ):
            await dispatch_notification(
                db_session,
                "order_confirmation",
                email=test_user.email,
                phone="+15551234567",
                context={"order_id": 1, "customer_name": "Test"},
            )

        mock_email.send_email.assert_awaited_once()
        mock_sms.send_sms.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_auth_events_on_sms(self, db_session, test_user):
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={"success": True})
        mock_sms = AsyncMock()
        mock_sms.send_sms = AsyncMock(return_value={"success": True})

        def _channel_addon(channel: str):
            if channel == "email":
                return mock_email
            if channel == "sms":
                return mock_sms
            return None

        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            side_effect=_channel_addon,
        ):
            await dispatch_notification(
                db_session,
                "email_verification",
                email=test_user.email,
                phone="+15551234567",
                context={"verify_url": "http://x", "expire_hours": 24},
            )

        mock_email.send_email.assert_awaited_once()
        mock_sms.send_sms.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logs_missing_success_flag_as_failure(self, db_session, test_user):
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={})

        with (
            patch(
                "app.services.notification_dispatch.get_notification_addon_for_channel",
                return_value=mock_email,
            ),
            patch("app.services.notification_dispatch.logger.warning") as warn,
        ):
            await dispatch_notification(
                db_session,
                "order_confirmation",
                email=test_user.email,
                context={"order_id": 1, "customer_name": "Test"},
            )

        mock_email.send_email.assert_awaited_once()
        warn.assert_called_once()


class TestNotificationAdminPages:
    @pytest.mark.asyncio
    async def test_notifications_list_page(self, client, test_user):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/notifications",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "Notifications" in resp.text
        assert "Postmark" in resp.text
        assert "Edit message templates" in resp.text

    @pytest.mark.asyncio
    async def test_notification_messages_list_page(self, client, test_user):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/notifications/messages",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "Order confirmation" in resp.text
        assert "Email verification" in resp.text

    @pytest.mark.asyncio
    async def test_notification_message_edit_page(self, client, test_user):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/notifications/messages/order_confirmation/email",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "order_id" in resp.text


class TestOrderStatusNotifications:
    @pytest.mark.asyncio
    async def test_paid_transition_uses_dispatch(self, db_session, test_user):
        from app.services.commerce import apply_order_status_change

        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await apply_order_status_change(db_session, order, "paid")

        mock_dispatch.assert_awaited_once()
        assert mock_dispatch.await_args.args[1] == "order_confirmation"
