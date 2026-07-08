"""Tests for product variant helpers."""

from __future__ import annotations

import pytest

from app.services.product_variants import (
    create_default_variant,
    get_active_variants,
    refresh_product_listing_cache,
    supplier_assignment_from_variant,
)
from models.product import Product
from models.product_variant import ProductVariant


def test_refresh_product_listing_cache_aggregates_variants():
    product = Product(name="Tee", price_cents=0, inventory_quantity=0, status="published")
    variants = [
        ProductVariant(
            product_id=1,
            title="Small",
            position=0,
            price_cents=1500,
            inventory_quantity=2,
            sku="TEE-S",
            status="active",
        ),
        ProductVariant(
            product_id=1,
            title="Large",
            position=1,
            price_cents=2000,
            inventory_quantity=5,
            sku="TEE-L",
            status="active",
        ),
    ]

    refresh_product_listing_cache(product, variants)

    assert product.has_variants is True
    assert product.price_cents == 1500
    assert product.inventory_quantity == 7
    assert product.sku == "TEE-S"


def test_get_active_variants_filters_archived():
    variants = [
        ProductVariant(
            product_id=1,
            title="Active",
            position=1,
            price_cents=1000,
            inventory_quantity=1,
            status="active",
        ),
        ProductVariant(
            product_id=1,
            title="Archived",
            position=0,
            price_cents=900,
            inventory_quantity=1,
            status="archived",
        ),
    ]

    active = get_active_variants(variants)

    assert len(active) == 1
    assert active[0].title == "Active"


def test_supplier_assignment_from_manual_variant_uses_slug():
    variant = ProductVariant(
        product_id=1,
        title="Mug",
        position=0,
        price_cents=1000,
        inventory_quantity=1,
        supplier_addon_id="manual",
        supplier_product_id="MUG-1",
        supplier_variant_id="local_workshop",
        status="active",
    )

    assignment = supplier_assignment_from_variant(variant)

    assert assignment is not None
    assert assignment.addon_id == "manual"
    assert assignment.manual_slug == "local_workshop"
    assert assignment.supplier_product_id == "MUG-1"


@pytest.mark.asyncio
async def test_create_default_variant_sets_listing_cache(db_session):
    product = Product(
        name="Manual item",
        price_cents=2500,
        compare_at_price_cents=3000,
        inventory_quantity=12,
        sku="MAN-1",
        status="draft",
    )
    db_session.add(product)
    await db_session.flush()

    variant = await create_default_variant(
        db_session,
        product,
        supplier_addon_id="printful",
        supplier_product_id="123",
    )

    assert variant.product_id == product.id
    assert variant.price_cents == 2500
    assert variant.inventory_quantity == 12
    assert product.price_cents == 2500
    assert product.has_variants is False
