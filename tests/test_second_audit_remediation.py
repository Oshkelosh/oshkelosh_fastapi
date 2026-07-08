"""Tests for second-pass audit remediation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlmodel import col, select

from app.addons.registry import addon_registry
from app.services.addons import get_frontend_addon, invalidate_frontend_cache
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from models.product_variant import ProductVariant


class TestDashboardRevenue:
    @pytest.mark.asyncio
    async def test_stats_exclude_pending_and_cancelled_revenue(
        self, client: AsyncClient, test_user, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        db_session.add(
            Order(
                user_id=test_user.id,
                status="pending",
                total_cents=5000,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
            )
        )
        db_session.add(
            Order(
                user_id=test_user.id,
                status="paid",
                total_cents=2000,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
            )
        )
        await db_session.commit()

        resp = await client.get("/api/v1/admin/stats", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total_revenue_cents"] == 2000


class TestProductDeleteGuard:
    @pytest.mark.asyncio
    async def test_rest_delete_blocked_when_order_items_exist(
        self, client: AsyncClient, test_user, test_product, db_session
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
                product_name=test_product.name,
                product_sku=test_product.sku or "SKU",
                quantity=1,
                unit_price_cents=test_product.price_cents,
                total_price_cents=test_product.price_cents,
            )
        )
        await db_session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.delete(
            f"/api/v1/admin/products/{test_product.id}",
            headers=headers,
        )
        assert resp.status_code == 422
        assert "existing orders" in resp.json()["message"].lower()


class TestFrontendCacheOnDisable:
    @pytest.mark.asyncio
    async def test_disable_async_clears_frontend_cache(self):
        from app.services import addons as addons_module

        invalidate_frontend_cache()
        addon_registry.register_all()
        frontend = addon_registry.get("default")
        if frontend is None:
            pytest.skip("default frontend addon not installed")

        frontend.is_enabled = True
        addons_module._frontend_addon_id = "default"
        assert get_frontend_addon() is not None

        await addon_registry.disable_async("default")
        assert addons_module._frontend_addon_id is None


class TestCartInventory:
    @pytest.mark.asyncio
    async def test_add_out_of_stock_product_rejected(
        self, client: AsyncClient, test_user, db_session
    ):
        product = Product(
            name="Sold Out",
            price_cents=1000,
            sku="OOS-001",
            inventory_quantity=0,
            status="published",
        )
        db_session.add(product)
        await db_session.flush()
        variant = ProductVariant(
            product_id=product.id,
            title="Default",
            position=0,
            price_cents=1000,
            inventory_quantity=0,
            sku="OOS-001",
            status="active",
        )
        db_session.add(variant)
        await db_session.commit()
        await db_session.refresh(product)
        await db_session.refresh(variant)

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post(
            "/api/v1/cart/items",
            json={"product_id": product.id, "variant_id": variant.id, "quantity": 1},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "inventory" in resp.json()["message"].lower()


class TestOrderPlacedNotification:
    @pytest.mark.asyncio
    async def test_create_order_dispatches_order_placed(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
            headers=headers,
        )

        with patch(
            "app.services.notifications.notify_order_placed",
            new_callable=AsyncMock,
        ) as notify:
            resp = await client.post("/api/v1/orders", headers=headers, json={})
            assert resp.status_code == 201
            notify.assert_awaited_once()
