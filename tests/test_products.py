"""Tests for product CRUD endpoints."""

import pytest
from httpx import AsyncClient
from sqlmodel import select

from models.category import Category
from models.product import Product
from models.product_variant import ProductVariant
from app.services.product_variants import refresh_product_listing_cache


class TestProductListing:
    """Test product listing endpoints."""

    async def test_list_products_empty(self, client: AsyncClient):
        """Test listing products when there are none."""
        response = await client.get("/api/v1/products")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_products_with_data(self, client: AsyncClient, test_product):
        """Test listing products with data."""
        response = await client.get("/api/v1/products")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(p["name"] == "Test Product" for p in data["items"])

    async def test_list_products_pagination(self, client: AsyncClient, test_product):
        """Test product listing pagination."""
        response = await client.get("/api/v1/products?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_get_product_by_id(self, client: AsyncClient, test_product):
        """Test getting a single product."""
        response = await client.get(f"/api/v1/products/{test_product.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Product"
        assert data["sku"] == "TEST-001"

    async def test_get_product_not_found(self, client: AsyncClient):
        """Test getting a non-existent product."""
        response = await client.get("/api/v1/products/999999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_products_filter_by_category_slug(self, client: AsyncClient, db_session):
        thin = Category(name="Canvas (in) | Thin", slug="canvas-in-thin")
        framed = Category(name="Canvas (in) | Framed", slug="canvas-in-framed")
        db_session.add(thin)
        db_session.add(framed)
        await db_session.flush()

        thin_product = Product(
            name="Amaryllis Thin",
            slug="amaryllis-thin",
            price_cents=1000,
            sku="THIN-1",
            inventory_quantity=1,
            status="published",
            category_id=thin.id,
        )
        framed_product = Product(
            name="Amaryllis Framed",
            slug="amaryllis-framed",
            price_cents=2000,
            sku="FRAMED-1",
            inventory_quantity=1,
            status="published",
            category_id=framed.id,
        )
        db_session.add(thin_product)
        db_session.add(framed_product)
        await db_session.flush()

        for product in (thin_product, framed_product):
            variant = ProductVariant(
                product_id=product.id,
                title=product.name,
                position=0,
                price_cents=product.price_cents,
                inventory_quantity=product.inventory_quantity,
                sku=product.sku,
                status="active",
            )
            db_session.add(variant)
            await db_session.flush()
            refresh_product_listing_cache(product, [variant])

        await db_session.commit()

        thin_response = await client.get("/api/v1/products?category=canvas-in-thin")
        assert thin_response.status_code == 200
        thin_data = thin_response.json()
        assert thin_data["total"] == 1
        assert thin_data["items"][0]["slug"] == "amaryllis-thin"

        framed_response = await client.get("/api/v1/products?category=canvas-in-framed")
        assert framed_response.status_code == 200
        framed_data = framed_response.json()
        assert framed_data["total"] == 1
        assert framed_data["items"][0]["slug"] == "amaryllis-framed"

    @pytest.mark.asyncio
    async def test_list_products_filter_by_category_id(self, client: AsyncClient, test_product):
        response = await client.get(
            f"/api/v1/products?category_id={test_product.category_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == test_product.id

    @pytest.mark.asyncio
    async def test_list_products_unknown_category_slug_returns_empty(self, client: AsyncClient):
        response = await client.get("/api/v1/products?category=does-not-exist")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestProductAdminCRUD:
    """Test admin product CRUD endpoints."""

    async def test_create_product(self, client: AsyncClient, test_user, test_category):
        """Test creating a product as admin."""
        # Login as admin
        login = await client.post("/api/v1/auth/login", json={
            "email": test_user.email,
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]

        response = await client.post(
            "/api/v1/admin/products",
            json={
                "name": "New Product",
                "description": "A new product",
                "price_cents": 2999,
                "sku": "NEW-001",
                "inventory_quantity": 50,
                "status": "draft",
                "category_id": test_category.id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["name"] == "New Product"
        assert data["price_cents"] == 2999

    async def test_create_product_generates_default_variant(
        self, client: AsyncClient, test_user, test_category, db_session
    ):
        login = await client.post("/api/v1/auth/login", json={
            "email": test_user.email,
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]

        response = await client.post(
            "/api/v1/admin/products",
            json={
                "name": "Variant Product",
                "description": "A new product",
                "price_cents": 3499,
                "sku": "VAR-001",
                "inventory_quantity": 25,
                "status": "draft",
                "category_id": test_category.id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (200, 201)

        result = await db_session.execute(
            select(ProductVariant).where(ProductVariant.product_id == response.json()["id"])
        )
        assert len(result.scalars().all()) == 1

    async def test_update_product(self, client: AsyncClient, test_product, test_user):
        """Test updating a product."""
        from passlib.context import CryptContext
        login = await client.post("/api/v1/auth/login", json={
            "email": test_user.email,
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]

        response = await client.patch(
            f"/api/v1/admin/products/{test_product.id}",
            json={"price_cents": 2499, "name": "Updated Product"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Product"
        assert data["price_cents"] == 2499

    async def test_delete_product(self, client: AsyncClient, test_product, test_user):
        """Test deleting a product."""
        login = await client.post("/api/v1/auth/login", json={
            "email": test_user.email,
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]

        response = await client.delete(
            f"/api/v1/admin/products/{test_product.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204

    async def test_public_admin_delete_blocks_products_on_existing_orders(
        self, client: AsyncClient, test_product, test_variant, test_user, db_session
    ):
        from models.order import Order
        from models.order_item import OrderItem

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
        await db_session.commit()

        login = await client.post("/api/v1/auth/login", json={
            "email": test_user.email,
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]

        response = await client.delete(
            f"/api/v1/products/{test_product.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
        assert "existing orders" in response.json()["message"].lower()

    async def test_admin_product_requires_auth(self, client: AsyncClient):
        """Test that admin product endpoints require authentication."""
        response = await client.get("/api/v1/admin/products")
        assert response.status_code == 401
