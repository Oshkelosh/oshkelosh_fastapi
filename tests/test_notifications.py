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
        assert "Abandoned cart" in resp.text

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
        assert "{order_id}" in resp.text
        assert "{ order_id }" not in resp.text


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


class TestCustomerContactResolution:
    def _order(self, **kwargs):
        values = {
            "status": "pending",
            "total_cents": 1000,
            "tax_cents": 0,
            "shipping_cents": 0,
            "currency": "usd",
        }
        values.update(kwargs)
        return Order(**values)

    @pytest.mark.asyncio
    async def test_guest_uses_full_name_and_phone_only(self, db_session):
        from app.services.notifications import notify_order_placed

        order = self._order(
            user_id=None,
            shipping_address={
                "full_name": "Ada Lovelace",
                "phone": "+15551230000",
            },
        )
        db_session.add(order)
        await db_session.flush()

        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await notify_order_placed(db_session, order)

        mock_dispatch.assert_awaited_once()
        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["email"] is None
        assert kwargs["phone"] == "+15551230000"
        assert kwargs["context"]["customer_name"] == "Ada Lovelace"

    @pytest.mark.asyncio
    async def test_guest_without_contact_skips(self, db_session):
        from app.services.notifications import notify_order_placed

        order = self._order(user_id=None, shipping_address={"full_name": "No Contact"})
        db_session.add(order)
        await db_session.flush()

        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await notify_order_placed(db_session, order)

        mock_dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logged_in_fills_phone_from_shipping(self, db_session, test_user):
        from app.services.notifications import notify_order_placed

        order = self._order(
            user_id=test_user.id,
            shipping_address={"phone": "+15559876543"},
        )
        db_session.add(order)
        await db_session.flush()

        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await notify_order_placed(db_session, order)

        mock_dispatch.assert_awaited_once()
        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["email"] == test_user.email
        assert kwargs["phone"] == "+15559876543"
        assert kwargs["context"]["customer_name"] == test_user.full_name

    @pytest.mark.asyncio
    async def test_missing_user_falls_back_to_shipping(self, db_session):
        from types import SimpleNamespace

        from app.services.notifications import notify_order_placed

        order = SimpleNamespace(
            id=1,
            user_id=999999,
            shipping_address={"email": "orphan@example.com", "full_name": "Orphan"},
            billing_address=None,
            total_cents=1000,
        )
        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await notify_order_placed(db_session, order)

        mock_dispatch.assert_awaited_once()
        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["email"] == "orphan@example.com"
        assert kwargs["context"]["customer_name"] == "Orphan"


class TestDispatchContract:
    @pytest.mark.asyncio
    async def test_disabled_template_does_not_call_addon(self, db_session, test_user):
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={"success": True})
        await save_template(
            db_session,
            "order_confirmation",
            "email",
            subject="Off",
            body="Off",
            is_enabled=False,
        )
        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_email,
        ):
            sent = await dispatch_notification(
                db_session,
                "order_confirmation",
                email=test_user.email,
                context={"order_id": 1},
            )
        assert sent is False
        mock_email.send_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_push_dispatch_sends_slim_data(self, db_session, test_user):
        mock_push = AsyncMock()
        mock_push.send_push = AsyncMock(return_value={"success": True})
        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_push,
        ):
            sent = await dispatch_notification(
                db_session,
                "order_confirmation",
                push_token="device-token",
                context={"order_id": 9, "customer_name": "Ada"},
            )
        assert sent is True
        mock_push.send_push.assert_awaited_once()
        data = mock_push.send_push.await_args.kwargs["data"]
        assert data == {"event": "order_confirmation", "order_id": 9}

    @pytest.mark.asyncio
    async def test_failure_log_omits_recipient(self, db_session, test_user):
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={})
        with (
            patch(
                "app.services.notification_dispatch.get_notification_addon_for_channel",
                return_value=mock_email,
            ),
            patch("app.services.notification_dispatch.logger.warning") as warn,
        ):
            sent = await dispatch_notification(
                db_session,
                "order_confirmation",
                email=test_user.email,
                context={"order_id": 1, "customer_name": "Test"},
            )
        assert sent is False
        logged = " ".join(str(a) for a in warn.call_args.args)
        assert test_user.email not in logged

    @pytest.mark.asyncio
    async def test_order_placed_and_delivered_through_dispatch(self, db_session, test_user):
        from app.services.commerce import apply_order_status_change
        from app.services.notifications import notify_order_placed

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
            await notify_order_placed(db_session, order)
        assert mock_dispatch.await_args.args[1] == "order_placed"

        order.status = "shipped"
        with patch(
            "app.services.notifications.dispatch_notification",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await apply_order_status_change(db_session, order, "delivered")
        mock_dispatch.assert_awaited_once()
        assert mock_dispatch.await_args.args[1] == "order_delivered"

    @pytest.mark.asyncio
    async def test_notify_errors_do_not_abort_paid(self, db_session, test_user):
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

        with patch(
            "app.services.notification_dispatch.get_site_settings",
            side_effect=RuntimeError("settings boom"),
        ):
            await apply_order_status_change(db_session, order, "paid")

        assert order.status == "paid"

    @pytest.mark.asyncio
    async def test_verification_email_uses_site_url(self, db_session, test_user):
        from app.services.site_settings import update_site_settings
        from app.services.user_accounts import send_verification_email

        await update_site_settings(db_session, {"site_url": "https://shop.example.com"})
        mock_email = AsyncMock()
        mock_email.send_email = AsyncMock(return_value={"success": True})
        with (
            patch("app.services.site_settings.settings") as mock_settings,
            patch(
                "app.services.notification_dispatch.get_notification_addon_for_channel",
                return_value=mock_email,
            ),
        ):
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            await send_verification_email(db_session, test_user)

        body = mock_email.send_email.await_args.args[2]
        assert body.startswith("https://shop.example.com/") or "https://shop.example.com/" in body
        assert "https://shop.example.com/verify-email?token=" in str(
            mock_email.send_email.await_args
        )


class TestNotificationChannelExclusivity:
    @pytest.mark.asyncio
    async def test_startup_keeps_one_addon_per_channel(self, db_session):
        from app.addons.registry import addon_registry
        from app.services.addons import enforce_notification_channel_exclusivity

        class _EmailAddon:
            addon_category = "notification"
            supported_channels = ("email",)

            def __init__(self, addon_id: str):
                self.addon_id = addon_id
                self.is_enabled = True

        first = _EmailAddon("email_a")
        second = _EmailAddon("email_b")
        addon_registry._registry["email_a"] = first  # type: ignore[assignment]
        addon_registry._registry["email_b"] = second  # type: ignore[assignment]
        try:
            await enforce_notification_channel_exclusivity(db_session)
            assert first.is_enabled is True
            assert second.is_enabled is False
        finally:
            addon_registry._registry.pop("email_a", None)
            addon_registry._registry.pop("email_b", None)
