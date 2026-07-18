"""Tests for user profile, auth flags, and order address wiring."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.core.security import hash_password
from models.user import User


@contextmanager
def _mock_payment_addon():
    mock_addon = AsyncMock()
    mock_addon.addon_id = "mock_payment"
    mock_addon.create_payment = AsyncMock(
        return_value={
            "checkout_url": "https://pay.test",
            "session_id": "sess_mock",
            "payment_id": "pi_mock",
        }
    )
    with patch(
        "app.services.addons.require_payment_addon",
        return_value=mock_addon,
    ):
        yield


class TestOrderAddresses:
    async def test_create_order_persists_addresses(
        self, client: AsyncClient, test_user, test_product, test_variant
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )

        shipping = {
            "first_name": "Jane",
            "last_name": "Doe",
            "line1": "1 Main St",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
            "country": "US",
            "email": "jane@example.com",
        }
        billing = {"line1": "2 Billing Ave", "city": "Portland", "country": "US"}

        response = await client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "shipping_address": shipping,
                "billing_address": billing,
                "notes": "Leave at door",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["shipping_address"] == shipping
        assert data["billing_address"]["line1"] == billing["line1"]
        assert data["billing_address"]["city"] == billing["city"]
        assert data["billing_address"]["country"] == billing["country"]
        assert data["billing_address"]["email"] == test_user.email
        assert data["notes"] == "Leave at door"

    async def test_checkout_can_update_addresses(
        self, client: AsyncClient, test_user, test_product, test_variant
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )
        order = await client.post("/api/v1/orders", headers=headers)
        order_id = order.json()["id"]

        shipping = {"first_name": "Sam", "line1": "9 Oak Rd", "country": "US"}
        with _mock_payment_addon():
            checkout = await client.post(
                f"/api/v1/orders/{order_id}/checkout",
                headers=headers,
                json={"shipping_address": shipping},
            )
        assert checkout.status_code == 200

        detail = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
        assert detail.json()["shipping_address"]["line1"] == "9 Oak Rd"
        assert detail.json()["shipping_address"]["email"] == test_user.email

    async def test_tax_inclusive_order_total(
        self, client: AsyncClient, db_session, test_user, test_product, test_variant
    ):
        from app.services.site_settings import update_site_settings

        await update_site_settings(
            db_session,
            {"tax_inclusive": True, "tax_rate_bps": 1000, "shipping_flat_cents": 500},
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )

        response = await client.post("/api/v1/orders", headers=headers)
        assert response.status_code == 201
        data = response.json()
        # price 1999 inclusive of 10% tax + 500 shipping — tax must not be added twice
        assert data["tax_cents"] == 182  # extracted from 1999 at 10%
        assert data["shipping_cents"] == 500
        assert data["total_cents"] == 1999 + 500

    async def test_checkout_reprices_after_address_change(
        self, client: AsyncClient, db_session, test_user, test_product, test_variant
    ):
        from app.services.site_settings import update_site_settings

        await update_site_settings(
            db_session,
            {
                "tax_zones_json": [{"countries": ["DE"], "rate_bps": 1900}],
                "shipping_zones_json": [{"countries": ["DE"], "flat_cents": 1200}],
            },
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )
        order = await client.post(
            "/api/v1/orders",
            headers=headers,
            json={"shipping_address": {"country": "US"}},
        )
        order_id = order.json()["id"]
        us_total = order.json()["total_cents"]

        with _mock_payment_addon():
            checkout = await client.post(
                f"/api/v1/orders/{order_id}/checkout",
                headers=headers,
                json={"shipping_address": {"country": "DE"}},
            )
        assert checkout.status_code == 200

        detail = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
        de_total = detail.json()["total_cents"]
        assert de_total != us_total
        assert detail.json()["shipping_cents"] == 1200


class TestUserProfile:
    async def test_patch_me_updates_profile(self, client: AsyncClient, test_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        address = {
            "line1": "42 Test Lane",
            "city": "Austin",
            "postal_code": "78701",
            "country": "US",
        }
        billing = {
            "line1": "99 Bill Ave",
            "city": "Austin",
            "postal_code": "78702",
            "country": "US",
        }
        response = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={
                "full_name": "Updated Name",
                "phone": "+15551234567",
                "default_shipping_address": address,
                "default_billing_address": billing,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"
        assert data["phone"] == "+15551234567"
        assert data["default_shipping_address"] == address
        assert data["default_billing_address"] == billing

    async def test_change_password_requires_current_password(
        self, client: AsyncClient, test_user
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        missing = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"password": "NewSecurePass456!"},
        )
        assert missing.status_code == 422

        wrong = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"password": "NewSecurePass456!", "current_password": "WrongPass999!"},
        )
        assert wrong.status_code == 422

        correct = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"password": "NewSecurePass456!", "current_password": "SecurePass123!"},
        )
        assert correct.status_code == 200

        relogin = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "NewSecurePass456!"},
        )
        assert relogin.status_code == 200

    async def test_sso_only_user_sets_initial_password_without_current(
        self, client: AsyncClient, db_session
    ):
        from app.core.security import create_access_token

        user = User(
            email="sso-only@example.com",
            password_hash=None,
            verified=True,
            banned=False,
            oauth_identities={"google": "sub-123"},
        )
        db_session.add(user)
        await db_session.flush()

        headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
        response = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"password": "FirstPass123!"},
        )
        assert response.status_code == 200
        assert "password" in response.json()["auth_methods"]

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "sso-only@example.com", "password": "FirstPass123!"},
        )
        assert login.status_code == 200

    async def test_patch_me_updates_push_subscription(self, client: AsyncClient, test_user):
        from app.addons.registry import addon_registry

        class _PushAddon:
            addon_id = "onesignal"
            addon_category = "notification"
            supported_channels = ["push"]

            def list_public_push_config(self):
                return {"provider": "onesignal", "config": {"appId": "test-app"}}

        addon = _PushAddon()
        addon.is_enabled = True
        addon_registry._registry["onesignal"] = addon  # type: ignore[assignment]

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"push_token": "player-123", "push_provider": "onesignal"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["push_enabled"] is True

        clear = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"push_token": None, "push_provider": None},
        )
        assert clear.status_code == 200
        assert clear.json()["push_enabled"] is False

        addon_registry._registry.pop("onesignal", None)


class TestAuthFlags:
    async def test_banned_user_cannot_login(self, client: AsyncClient, db_session):
        user = User(
            email="banned@example.com",
            password_hash=hash_password("SecurePass123!"),
            banned=True,
            verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "banned@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 401

    async def test_unverified_user_can_login(self, client: AsyncClient, db_session):
        user = User(
            email="unverified@example.com",
            password_hash=hash_password("SecurePass123!"),
            banned=False,
            verified=False,
        )
        db_session.add(user)
        await db_session.flush()

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "unverified@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_register_sets_unverified_and_not_banned(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "flags@example.com",
                "password": "SecurePass123!",
                "full_name": "Flags User",
                "default_shipping_address": {
                    "line1": "1 Flag St",
                    "city": "Austin",
                    "postal_code": "78701",
                    "country": "US",
                },
                "billing_same_as_shipping": True,
            },
        )
        assert response.status_code == 201
        data = response.json()["user"]
        assert data["verified"] is False
        assert data["banned"] is False
        assert data["is_admin"] is False
        assert "access_token" in response.json()
