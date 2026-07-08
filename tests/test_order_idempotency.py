"""Tests for order idempotency keys."""

from httpx import AsyncClient


class TestOrderIdempotency:
    async def test_replay_returns_same_order(
        self, client: AsyncClient, test_user, test_product, test_variant
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "Idempotency-Key": "checkout-attempt-001",
        }
        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )

        first = await client.post("/api/v1/orders", headers=headers)
        assert first.status_code == 201
        first_id = first.json()["id"]

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
        )
        second = await client.post("/api/v1/orders", headers=headers)
        assert second.status_code == 200
        assert second.json()["id"] == first_id
