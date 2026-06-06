"""Checkout and commerce flow tests."""

from httpx import AsyncClient


class TestCheckout:
    async def test_cannot_add_draft_product_to_cart(
        self, client: AsyncClient, test_user, db_session
    ):
        from models.product import Product

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
        await db_session.refresh(draft)

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]

        response = await client.post(
            "/api/v1/cart/items",
            headers={"Authorization": f"Bearer {token}"},
            json={"product_id": draft.id, "quantity": 1},
        )
        assert response.status_code in (400, 422)

    async def test_checkout_creates_pending_order_without_inventory_change(
        self, client: AsyncClient, test_user, test_product, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "quantity": 2},
        )

        await db_session.refresh(test_product)
        inventory_before = test_product.inventory_quantity
        order_resp = await client.post("/api/v1/orders", headers=headers)
        assert order_resp.status_code == 201
        order = order_resp.json()
        assert order["status"] == "pending"

        product_resp = await client.get(f"/api/v1/products/{test_product.id}")
        assert product_resp.json()["inventory_quantity"] == inventory_before

    async def test_cancel_paid_order_restores_inventory(
        self, client: AsyncClient, test_user, test_product, db_session
    ):
        from models.order import Order
        from models.order_item import OrderItem

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {token}"}

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
        await db_session.refresh(order)

        item = OrderItem(
            order_id=order.id,
            product_id=test_product.id,
            product_name=test_product.name,
            product_sku=test_product.sku,
            quantity=3,
            unit_price_cents=test_product.price_cents,
            total_price_cents=test_product.price_cents * 3,
        )
        db_session.add(item)
        test_product.inventory_quantity -= 3
        await db_session.flush()
        await db_session.refresh(test_product)

        cancel = await client.post(
            f"/api/v1/orders/{order.id}/cancel",
            headers=admin_headers,
        )
        assert cancel.status_code == 200

        await db_session.refresh(test_product)
        product_resp = await client.get(f"/api/v1/products/{test_product.id}")
        assert product_resp.json()["inventory_quantity"] == 100
