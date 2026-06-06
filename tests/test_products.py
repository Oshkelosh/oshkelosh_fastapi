"""Tests for product CRUD endpoints."""

from httpx import AsyncClient


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


class TestProductAdminCRUD:
    """Test admin product CRUD endpoints."""

    async def test_create_product(self, client: AsyncClient, test_user):
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
                "category": "Electronics",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["name"] == "New Product"
        assert data["price_cents"] == 2999

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

    async def test_admin_product_requires_auth(self, client: AsyncClient):
        """Test that admin product endpoints require authentication."""
        response = await client.get("/api/v1/admin/products")
        assert response.status_code == 401
