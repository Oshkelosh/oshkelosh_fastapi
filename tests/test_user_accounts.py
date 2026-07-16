"""Tests for remaining user DB plan items."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.db.backends.d1_http_session import D1HTTPAsyncSession
from app.core.security import hash_password, verify_password
from app.services.payments import complete_order_payment
from app.services.user_accounts import (
    clear_email_verification,
    issue_email_verification,
    issue_password_reset,
    resolve_order_shipping_address,
)
from models.order import Order
from models.user import User


async def _auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAdminUserCrud:
    async def test_admin_lists_and_updates_user(
        self, client: AsyncClient, test_user, db_session
    ):
        headers = await _auth_headers(client, test_user.email, "SecurePass123!")

        listed = await client.get("/api/v1/admin/users", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1

        detail = await client.get(f"/api/v1/admin/users/{test_user.id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["email"] == test_user.email

        updated = await client.patch(
            f"/api/v1/admin/users/{test_user.id}",
            headers=headers,
            json={"full_name": "Admin Updated", "phone": "+15550001111"},
        )
        assert updated.status_code == 200
        assert updated.json()["full_name"] == "Admin Updated"

    async def test_admin_creates_user(self, client: AsyncClient, test_user):
        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        response = await client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "staff@example.com",
                "password": "SecurePass123!",
                "full_name": "Staff User",
                "is_admin": False,
                "verified": True,
                "banned": False,
            },
        )
        assert response.status_code == 201
        assert response.json()["email"] == "staff@example.com"

    async def test_deleting_user_preserves_order_history(
        self, db_session, test_user, test_product
    ):
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.commit()

        await db_session.delete(test_user)
        await db_session.commit()

        await db_session.refresh(order)
        preserved = await db_session.get(Order, order.id)
        assert preserved is not None
        assert preserved.user_id is None

    async def test_sqlite_foreign_keys_set_user_id_null_on_raw_delete(
        self, db_session, test_user, test_product
    ):
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.commit()

        await db_session.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": test_user.id},
        )
        await db_session.commit()

        await db_session.refresh(order)
        preserved = await db_session.get(Order, order.id)
        assert preserved is not None
        assert preserved.user_id is None


class TestEmailVerification:
    @pytest.fixture(autouse=True)
    def _enable_verification(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.require_email_verification", True)

    async def test_register_sends_verification_but_allows_login(
        self, client: AsyncClient, db_session
    ):
        address = {
            "line1": "1 Verify Ln",
            "city": "Austin",
            "postal_code": "78701",
            "country": "US",
        }
        mock_addon = AsyncMock()
        mock_addon.send_email = AsyncMock(return_value={"success": True})
        mock_addon.supported_channels = ["email"]
        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_addon,
        ):
            register = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "verifyme@example.com",
                    "password": "SecurePass123!",
                    "full_name": "Verify Me",
                    "default_shipping_address": address,
                    "billing_same_as_shipping": True,
                },
            )
        assert register.status_code == 201
        body = register.json()
        assert body["user"]["verified"] is False
        assert "access_token" in body
        mock_addon.send_email.assert_awaited_once()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "verifyme@example.com", "password": "SecurePass123!"},
        )
        assert login.status_code == 200

        from sqlmodel import select

        result = await db_session.execute(
            select(User).where(User.email == "verifyme@example.com")
        )
        user = result.scalar_one()
        token = user.email_verification_token
        assert token

        verify = await client.post(
            "/api/v1/auth/verify-email",
            json={"token": token},
        )
        assert verify.status_code == 200

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["verified"] is True

    async def test_resend_verification(self, client: AsyncClient, db_session):
        address = {
            "line1": "2 Resend Ln",
            "city": "Austin",
            "postal_code": "78701",
            "country": "US",
        }
        mock_addon = AsyncMock()
        mock_addon.send_email = AsyncMock(return_value={"success": True})
        mock_addon.supported_channels = ["email"]
        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_addon,
        ):
            register = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "resend@example.com",
                    "password": "SecurePass123!",
                    "default_shipping_address": address,
                    "billing_same_as_shipping": True,
                },
            )
            assert register.status_code == 201
            token = register.json()["access_token"]
            mock_addon.send_email.reset_mock()
            resend = await client.post(
                "/api/v1/auth/resend-verification",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resend.status_code == 200
        mock_addon.send_email.assert_awaited_once()


class TestPasswordReset:
    async def test_forgot_and_reset_password(self, client: AsyncClient, db_session):
        user = User(
            email="resetme@example.com",
            password_hash=hash_password("SecurePass123!"),
            verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        mock_addon = AsyncMock()
        mock_addon.send_email = AsyncMock(return_value={"success": True})
        mock_addon.supported_channels = ["email"]
        with patch(
            "app.services.notification_dispatch.get_notification_addon_for_channel",
            return_value=mock_addon,
        ):
            forgot = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "resetme@example.com"},
            )
        assert forgot.status_code == 200
        mock_addon.send_email.assert_awaited_once()

        await db_session.refresh(user)
        token = user.password_reset_token
        assert token

        reset = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "NewSecure456!"},
        )
        assert reset.status_code == 200

        await db_session.refresh(user)
        assert verify_password("NewSecure456!", user.password_hash)


class TestOrderAddressFallback:
    async def test_create_order_uses_default_shipping_address(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        test_user.default_shipping_address = {
            "first_name": "Saved",
            "line1": "99 Default Rd",
            "country": "US",
        }
        test_user.default_billing_address = {
            "line1": "88 Billing Rd",
            "city": "Austin",
            "postal_code": "78701",
            "country": "US",
        }
        test_user.phone = "+15551230000"
        db_session.add(test_user)
        await db_session.flush()

        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )

        order = await client.post("/api/v1/orders", headers=headers)
        assert order.status_code == 201
        data = order.json()
        address = data["shipping_address"]
        assert address["line1"] == "99 Default Rd"
        assert address["email"] == test_user.email
        assert address["phone"] == "+15551230000"
        assert data["billing_address"]["line1"] == "88 Billing Rd"


class TestPaymentCustomerLinkage:
    async def test_complete_order_payment_links_customer_id(
        self, db_session, test_user, test_product
    ):
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        with patch("app.services.payments.apply_order_status_change", new_callable=AsyncMock) as status_change:
            paid = await complete_order_payment(
                db_session,
                order.id,
                processor_id="stripe",
                customer_id="cus_test_123",
            )
            status_change.assert_awaited_once()

        assert paid.id == order.id
        await db_session.refresh(test_user)
        assert test_user.payment_customer_ids == {"stripe": "cus_test_123"}


class TestUserAccountHelpers:
    def test_resolve_order_shipping_address_falls_back_and_injects_contact(self):
        user = User(
            email="buyer@example.com",
            password_hash="hash",
            phone="+15550100",
            default_shipping_address={"line1": "42 Saved Ln", "country": "US"},
        )
        resolved = resolve_order_shipping_address(user, None)
        assert resolved is not None
        assert resolved["line1"] == "42 Saved Ln"
        assert resolved["email"] == "buyer@example.com"
        assert resolved["phone"] == "+15550100"

    def test_resolve_order_billing_address_falls_back(self):
        from app.services.user_accounts import resolve_order_billing_address

        user = User(
            email="buyer@example.com",
            password_hash="hash",
            default_shipping_address={"line1": "Ship Ln", "country": "US"},
            default_billing_address={"line1": "Bill Ln", "country": "US"},
        )
        resolved = resolve_order_billing_address(user, None)
        assert resolved is not None
        assert resolved["line1"] == "Bill Ln"
        assert resolved["email"] == "buyer@example.com"

        user.default_billing_address = None
        resolved = resolve_order_billing_address(user, None)
        assert resolved is not None
        assert resolved["line1"] == "Ship Ln"

    def test_issue_tokens_set_expiry(self):
        user = User(email="a@b.com", password_hash="hash")
        issue_email_verification(user)
        assert user.email_verification_token
        assert user.email_verification_expires_at is not None

        issue_password_reset(user)
        assert user.password_reset_token
        assert user.password_reset_expires_at is not None

    def test_d1_compile_update_preserves_null_field_clears(self):
        user = User(
            id=123,
            email="clear@example.com",
            password_hash="hash",
            email_verification_token="token",
            email_verification_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        clear_email_verification(user)

        session = D1HTTPAsyncSession(object())  # type: ignore[arg-type]
        sql, values = session._compile_update(user)

        assert "email_verification_token = ?" in sql
        assert "email_verification_expires_at = ?" in sql
        assert values[-1] == 123
        assert None in values[:-1]
