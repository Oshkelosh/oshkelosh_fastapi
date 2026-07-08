"""Checkout and commerce flow tests."""

from httpx import AsyncClient


class TestCheckout:
    async def test_cannot_add_draft_product_to_cart(
        self, client: AsyncClient, test_user, db_session
    ):
        from models.product import Product
        from models.product_variant import ProductVariant

        draft = Product(
            name="Draft Only",
            price_cents=500,
            sku="DRAFT-001Swap",
            inventory_quantity=10,
            status="draft",
            created_by=test_user.id,
        )
        db_session.add(draft)
        await db_session.flush()
        draft_variant = ProductVariant(
            product_id=draft.id,
            title=draft.name,
            price_cents=draft.price_cents,
            inventory_quantity=draft.inventory_quantity,
            sku=draft.sku,
            status="active",
        )
        db_session.add(draft_variant)
        await db_session.flush()
        await db_session.refresh(draft_variant)

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]

        response = await client.post(
            "/api/v1/cart/items",
            headers={"Authorization": f"Bearer {token}"},
            json={"product_id": draft.id, "variant_id": draft_variant.id, "quantity": 1},
        )
        assert response.status_code in (400, 422)

    async def test_checkout_reserves_inventory_at_creation(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={
                "product_id": test_product.id,
                "variant_id": test_variant.id,
                "quantity": 2,
            },
        )

        await db_session.refresh(test_variant)
        inventory_before = test_variant.inventory_quantity
        order_resp = await client.post("/api/v1/orders", headers=headers)
        assert order_resp.status_code == 201
        assert order_resp.json()["status"] == "pending"

        await db_session.refresh(test_variant)
        assert test_variant.inventory_quantity == inventory_before - 2

    async def test_cancel_pending_order_restores_inventory(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={
                "product_id": test_product.id,
                "variant_id": test_variant.id,
                "quantity": 1,
            },
        )
        order_resp = await client.post("/api/v1/orders", headers=headers)
        order_id = order_resp.json()["id"]

        cancel = await client.post(f"/api/v1/orders/{order_id}/cancel", headers=headers)
        assert cancel.status_code == 200

        await db_session.refresh(test_variant)
        assert test_variant.inventory_quantity == 100

    async def test_cancel_paid_order_restores_inventory(
        self, client: AsyncClient, test_user, test_product, test_variant, db_session
    ):
        from models.order import Order
        from models.order_item import OrderItem

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        order = Order(
            user_id=test_user.id,
            status="paid",
            total_cents=1999,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=test_product.id,
            variant_id=test_variant.id,
            product_name=test_product.name,
            product_sku=test_variant.sku or "SKU",
            quantity=3,
            unit_price_cents=test_variant.price_cents,
            total_price_cents=test_variant.price_cents * 3,
        )
        db_session.add(item)
        test_variant.inventory_quantity -= 3
        await db_session.flush()

        cancel = await client.post(f"/api/v1/orders/{order.id}/cancel", headers=headers)
        assert cancel.status_code == 200

        await db_session.refresh(test_variant)
        assert test_variant.inventory_quantity == 100
