"""Tests for order idempotency keys."""

from httpx import AsyncClient
from sqlmodel import select

from models.cart import Cart
from models.order import Order
from models.order_idempotency_key import OrderIdempotencyKey


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

    async def test_late_idempotency_conflict_discards_duplicate_order(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session, monkeypatch
    ):
        from app.api.v1.routers import orders as orders_router
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "Idempotency-Key": "checkout-race-001",
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

        original_record = orders_router.record_idempotent_order

        async def late_duplicate(*args, **kwargs):
            existing = await orders_router.find_idempotent_order(
                args[0],
                user_id=kwargs["user_id"],
                raw_key=kwargs["raw_key"],
            )
            assert existing is not None
            return existing

        monkeypatch.setattr(orders_router, "record_idempotent_order", late_duplicate)

        second = await client.post("/api/v1/orders", headers=headers)
        assert second.status_code == 200
        assert second.json()["id"] == first_id

        monkeypatch.setattr(orders_router, "record_idempotent_order", original_record)

        orders = list((await db_session.execute(select(Order))).scalars())
        keys = list((await db_session.execute(select(OrderIdempotencyKey))).scalars())
        carts = list((await db_session.execute(select(Cart))).scalars())
        await db_session.refresh(test_variant)

        assert len(orders) == 1
        assert len(keys) == 1
        assert len(carts) == 1
        assert test_variant.inventory_quantity == 99
