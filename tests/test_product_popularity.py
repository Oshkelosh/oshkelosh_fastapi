"""Tests for product popularity sorting and units_sold counter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.commerce import apply_order_status_change
from app.services.payments import complete_order_payment
from app.services.product_popularity import compute_popularity_score
from models.order import Order
from models.order_item import OrderItem
from models.product import Product


def _published_product(
    db_session,
    test_user,
    *,
    name: str,
    slug: str,
    sku: str,
    units_sold: int = 0,
    created_at: datetime | None = None,
) -> Product:
    product = Product(
        name=name,
        slug=slug,
        description=f"{name} description",
        price_cents=1000,
        sku=sku,
        inventory_quantity=50,
        status="published",
        units_sold=units_sold,
        created_by=test_user.id,
    )
    if created_at is not None:
        product.created_at = created_at
        product.updated_at = created_at
    db_session.add(product)
    return product


class TestComputePopularityScore:
    def test_clamps_age_to_one_day(self):
        now = datetime.now(tz=timezone.utc)
        assert compute_popularity_score(5, now) == 5.0

    def test_uses_whole_days(self):
        created = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert compute_popularity_score(10, created) == 10 / max(
            1, (datetime.now(tz=timezone.utc) - created).days
        )


class TestPopularitySort:
    @pytest.mark.asyncio
    async def test_same_units_sold_older_product_ranks_lower(
        self, client: AsyncClient, db_session, test_user
    ):
        now = datetime.now(tz=timezone.utc)
        older = _published_product(
            db_session,
            test_user,
            name="Older Product",
            slug="older-product",
            sku="OLD-001",
            units_sold=10,
            created_at=now - timedelta(days=30),
        )
        newer = _published_product(
            db_session,
            test_user,
            name="Newer Product",
            slug="newer-product",
            sku="NEW-001",
            units_sold=10,
            created_at=now - timedelta(days=5),
        )
        await db_session.flush()
        await db_session.refresh(older)
        await db_session.refresh(newer)

        response = await client.get("/api/v1/products?sort=popularity&order=desc")
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names.index("Newer Product") < names.index("Older Product")

    @pytest.mark.asyncio
    async def test_higher_units_per_day_wins(
        self, client: AsyncClient, db_session, test_user
    ):
        now = datetime.now(tz=timezone.utc)
        slow = _published_product(
            db_session,
            test_user,
            name="Slow Seller",
            slug="slow-seller",
            sku="SLOW-001",
            units_sold=2,
            created_at=now - timedelta(days=10),
        )
        fast = _published_product(
            db_session,
            test_user,
            name="Fast Seller",
            slug="fast-seller",
            sku="FAST-001",
            units_sold=8,
            created_at=now - timedelta(days=10),
        )
        await db_session.flush()

        response = await client.get("/api/v1/products?sort=popularity&order=desc")
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names[0] == "Fast Seller"
        assert names.index("Fast Seller") < names.index("Slow Seller")

    @pytest.mark.asyncio
    async def test_zero_sales_products_are_randomized(
        self, client: AsyncClient, db_session, test_user
    ):
        for i in range(8):
            _published_product(
                db_session,
                test_user,
                name=f"Unsold Product {i}",
                slug=f"unsold-product-{i}",
                sku=f"UNSOLD-{i:03d}",
            )
        await db_session.flush()

        orderings = set()
        for _ in range(10):
            response = await client.get("/api/v1/products?sort=popularity&order=desc")
            assert response.status_code == 200
            orderings.add(tuple(item["name"] for item in response.json()["items"]))
        assert len(orderings) > 1

    @pytest.mark.asyncio
    async def test_response_includes_units_sold_and_popularity_score(
        self, client: AsyncClient, test_product
    ):
        response = await client.get(f"/api/v1/products/{test_product.id}")
        assert response.status_code == 200
        data = response.json()
        assert "units_sold" in data
        assert "popularity_score" in data
        assert data["units_sold"] == 0

    @pytest.mark.asyncio
    async def test_list_sets_cache_control_headers(self, client: AsyncClient, test_product):
        response = await client.get("/api/v1/products?sort=popularity&order=desc")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "public, max-age=30"

        response_default = await client.get("/api/v1/products")
        assert "max-age=60" in response_default.headers.get("cache-control", "")

    @pytest.mark.asyncio
    async def test_detail_sets_etag(self, client: AsyncClient, test_product):
        response = await client.get(f"/api/v1/products/{test_product.id}")
        assert response.status_code == 200
        assert response.headers.get("etag", "").startswith('W/"')


class TestUnitsSoldIncrement:
    @pytest.mark.asyncio
    async def test_pending_to_paid_increments_units_sold(
        self, db_session, test_user, test_product
    ):
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=1000,
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
                quantity=3,
                unit_price_cents=1000,
                total_price_cents=3000,
            )
        )
        await db_session.flush()

        with (
            patch(
                "app.services.fulfillment.fulfill_order_with_suppliers",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.notifications.notify_order_status_change",
                new_callable=AsyncMock,
            ),
        ):
            await apply_order_status_change(db_session, order, "paid")

        await db_session.refresh(test_product)
        assert test_product.units_sold == 3

    @pytest.mark.asyncio
    async def test_complete_order_payment_idempotent(
        self, db_session, test_user, test_product
    ):
        order = Order(
            user_id=test_user.id,
            status="paid",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
            payment_processor_id="test",
            payment_id="pay_123",
        )
        db_session.add(order)
        await db_session.flush()
        db_session.add(
            OrderItem(
                order_id=order.id,
                product_id=test_product.id,
                product_name=test_product.name,
                product_sku=test_product.sku or "SKU",
                quantity=2,
                unit_price_cents=1000,
                total_price_cents=2000,
            )
        )
        await db_session.flush()
        test_product.units_sold = 2
        await db_session.flush()

        with patch(
            "app.services.payments.apply_order_status_change",
            new_callable=AsyncMock,
        ) as status_change:
            await complete_order_payment(
                db_session,
                order.id,
                processor_id="test",
                payment_id="pay_456",
            )

        status_change.assert_not_awaited()
        await db_session.refresh(test_product)
        assert test_product.units_sold == 2
