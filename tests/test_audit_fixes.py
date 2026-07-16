"""Tests for audit-plan fixes (cart, orders, admin, security)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.core.exceptions import ValidationError
from app.core.security import hash_password
from app.main import app
from app.services.commerce import reserve_order_inventory
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from models.product_variant import ProductVariant
from models.user import User


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


async def _auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestCartSubtotal:
    async def test_get_cart_returns_line_items_and_subtotal(
        self, client: AsyncClient, test_user, test_product, test_variant
    ):
        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 2},
        )

        cart = await client.get("/api/v1/cart", headers=headers)
        assert cart.status_code == 200
        data = cart.json()
        assert data["subtotal_cents"] == test_product.price_cents * 2
        assert len(data["items"]) == 1
        assert data["items"][0]["line_total_cents"] == test_product.price_cents * 2


class TestOrderIdor:
    async def test_user_cannot_read_other_users_order(
        self, client: AsyncClient, test_user, test_product, db_session
    ):
        other = User(
            email="other@example.com",
            password_hash=hash_password("SecurePass123!"),
            full_name="Other User",
            is_admin=False,
        )
        db_session.add(other)
        await db_session.flush()
        await db_session.refresh(other)

        order = Order(
            user_id=other.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        response = await client.get(f"/api/v1/orders/{order.id}", headers=headers)
        assert response.status_code == 404

    async def test_user_cannot_cancel_other_users_order(
        self, client: AsyncClient, test_user, test_product, db_session
    ):
        other = User(
            email="cancel-other@example.com",
            password_hash=hash_password("SecurePass123!"),
            full_name="Other User",
            is_admin=False,
        )
        db_session.add(other)
        await db_session.flush()
        await db_session.refresh(other)

        order = Order(
            user_id=other.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        response = await client.post(
            f"/api/v1/orders/{order.id}/cancel",
            headers=headers,
        )
        assert response.status_code == 404


class TestInventoryRollback:
    @pytest.mark.asyncio
    async def test_reserve_order_inventory_rolls_back_on_partial_failure(
        self, db_session
    ):
        product_ok = Product(
            name="In stock",
            price_cents=500,
            inventory_quantity=10,
            status="published",
        )
        product_empty = Product(
            name="Sold out",
            price_cents=500,
            inventory_quantity=0,
            status="published",
        )
        db_session.add(product_ok)
        db_session.add(product_empty)
        await db_session.flush()
        variant_ok = ProductVariant(
            product_id=product_ok.id,
            title="Default",
            position=0,
            price_cents=500,
            inventory_quantity=10,
            sku="OK-1",
            status="active",
        )
        variant_empty = ProductVariant(
            product_id=product_empty.id,
            title="Default",
            position=0,
            price_cents=500,
            inventory_quantity=0,
            sku="EMPTY-1",
            status="active",
        )
        db_session.add(variant_ok)
        db_session.add(variant_empty)
        await db_session.flush()
        await db_session.refresh(product_ok)
        await db_session.refresh(product_empty)
        await db_session.refresh(variant_ok)
        await db_session.refresh(variant_empty)

        items = [
            OrderItem(
                order_id=1,
                product_id=product_ok.id,
                variant_id=variant_ok.id,
                product_name=product_ok.name,
                product_sku="OK-1",
                quantity=3,
                unit_price_cents=500,
                total_price_cents=1500,
            ),
            OrderItem(
                order_id=1,
                product_id=product_empty.id,
                variant_id=variant_empty.id,
                product_name=product_empty.name,
                product_sku="EMPTY-1",
                quantity=1,
                unit_price_cents=500,
                total_price_cents=500,
            ),
        ]

        with pytest.raises(ValidationError, match="Insufficient inventory"):
            await reserve_order_inventory(db_session, items)

        await db_session.refresh(variant_ok)
        assert variant_ok.inventory_quantity == 10


class TestAdminOrderStatus:
    async def test_rejects_invalid_status_transition(
        self, client: AsyncClient, test_user, db_session
    ):
        app.state.needs_setup = False
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=1000,
            tax_cents=80,
            shipping_cents=500,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/orders/{order.id}/status",
            cookies=cookies,
            data={"status": "shipped", "csrf_token": csrf},
        )
        assert response.status_code == 200
        assert "Cannot transition" in response.text

        await db_session.refresh(order)
        assert order.status == "pending"

    async def test_requires_valid_csrf_token(
        self, client: AsyncClient, test_user, db_session
    ):
        app.state.needs_setup = False
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=1000,
            tax_cents=80,
            shipping_cents=500,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/orders/{order.id}/status",
            cookies=cookies,
            data={"status": "paid", "csrf_token": "wrong-token"},
        )
        assert response.status_code == 403

    async def test_admin_cancels_paid_order_flags_refund_review(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        order = Order(
            user_id=test_user.id,
            status="paid",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        db_session.add(
            OrderItem(
                order_id=order.id,
                product_id=test_product.id,
                variant_id=test_variant.id,
                product_name=test_product.name,
                product_sku=test_variant.sku or "SKU",
                quantity=1,
                unit_price_cents=test_variant.price_cents,
                total_price_cents=test_variant.price_cents,
            )
        )
        test_variant.inventory_quantity -= 1
        await db_session.commit()

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/orders/{order.id}/status",
            cookies=cookies,
            data={"status": "cancelled", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 302

        await db_session.refresh(order)
        await db_session.refresh(test_variant)
        assert order.status == "cancelled"
        assert "Refund review required" in (order.notes or "")
        assert test_variant.inventory_quantity == 100

    async def test_admin_cannot_cancel_shipped_order(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        order = Order(
            user_id=test_user.id,
            status="shipped",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        db_session.add(
            OrderItem(
                order_id=order.id,
                product_id=test_product.id,
                variant_id=test_variant.id,
                product_name=test_product.name,
                product_sku=test_variant.sku or "SKU",
                quantity=1,
                unit_price_cents=test_variant.price_cents,
                total_price_cents=test_variant.price_cents,
            )
        )
        await db_session.commit()

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/orders/{order.id}/status",
            cookies=cookies,
            data={"status": "cancelled", "csrf_token": csrf},
        )
        assert response.status_code == 200
        # shipped -> cancelled is no longer a valid transition, so the
        # route rejects it before reaching the admin cancel flow.
        assert "Cannot transition from &#39;shipped&#39; to &#39;cancelled&#39;" in response.text

        await db_session.refresh(order)
        assert order.status == "shipped"


class TestAdminStaticSecurity:
    async def test_blocks_path_traversal(self, client: AsyncClient):
        response = await client.get("/admin/static/../routes.py")
        assert response.status_code == 404


class TestManualSupplierApiAuth:
    async def test_requires_admin_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/suppliers/manual/suppliers")
        assert response.status_code in (401, 403)

    async def test_allows_admin_jwt(self, client: AsyncClient, test_user):
        headers = await _auth_headers(client, test_user.email, "SecurePass123!")
        response = await client.get(
            "/api/v1/suppliers/manual/suppliers",
            headers=headers,
        )
        assert response.status_code == 200
        assert "suppliers" in response.json()


@pytest.mark.asyncio
async def test_download_rejects_redirect_to_localhost():
    import httpx

    from app.config import Settings
    from app.services import addon_install

    cfg = Settings()

    class FakeStreamResponse:
        def __init__(self, status_code: int, *, location: str | None = None):
            self.status_code = status_code
            self.headers = {"location": location} if location else {}
            self.url = "https://example.com/start.zip"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "error",
                    request=None,
                    response=None,
                )

        async def aiter_bytes(self, chunk_size: int):
            if False:
                yield b""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("follow_redirects") is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeStreamResponse(
                302,
                location="https://127.0.0.1/evil.zip",
            )

    url = "https://example.com/addon.zip"
    with patch("app.services.addon_install._is_private_ip", return_value=False):
        with patch("app.services.addon_install.httpx.AsyncClient", FakeClient):
            with pytest.raises(ValidationError, match="Localhost"):
                await addon_install.download_addon_archive(url, cfg)
