"""Tests for category creation SEO defaults."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.services.category_defaults import (
    apply_category_creation_defaults,
    default_category_meta,
)
from app.services.product_defaults import assign_product_category_from_type
from app.services.site_settings import get_site_settings, update_site_settings
from models.category import Category
from models.product import Product


@pytest.mark.asyncio
async def test_default_category_meta_uses_name_and_description():
    category = Category(name="Canvas Prints", slug="canvas", description="High quality canvas")
    title, description = default_category_meta(category, "Oshkelosh")
    assert title == "Canvas Prints | Oshkelosh"
    assert description == "High quality canvas"


@pytest.mark.asyncio
async def test_apply_category_creation_defaults_fills_meta_from_description(db_session):
    category = Category(
        name="Posters",
        slug="posters",
        description="Wall art posters for every room",
    )
    db_session.add(category)
    await db_session.flush()

    await apply_category_creation_defaults(db_session, category, store_name="Oshkelosh")
    await db_session.flush()

    assert category.meta_title == "Posters | Oshkelosh"
    assert category.meta_description == "Wall art posters for every room"


@pytest.mark.asyncio
async def test_apply_category_creation_defaults_uses_site_description_when_no_description(
    db_session,
):
    await update_site_settings(
        db_session,
        {"meta_description": "Shop our curated catalog"},
    )
    await db_session.flush()

    category = Category(name="Misc", slug="misc")
    db_session.add(category)
    await db_session.flush()

    await apply_category_creation_defaults(db_session, category, store_name="Oshkelosh")
    await db_session.flush()

    assert category.meta_title == "Misc | Oshkelosh"
    assert category.meta_description == "Shop our curated catalog"


@pytest.mark.asyncio
async def test_apply_category_creation_defaults_respects_explicit_meta_title(db_session):
    category = Category(
        name="Hoodies",
        slug="hoodies",
        description="Warm hoodies",
        meta_title="Custom Hoodie Title",
    )
    db_session.add(category)
    await db_session.flush()

    await apply_category_creation_defaults(db_session, category, store_name="Oshkelosh")
    await db_session.flush()

    assert category.meta_title == "Custom Hoodie Title"
    assert category.meta_description == "Warm hoodies"


@pytest.mark.asyncio
async def test_assign_product_category_from_type_generates_category_seo(
    db_session, test_user
):
    site = await get_site_settings(db_session)
    store_name = site.store_name or "Store"

    product = Product(
        name="Synced Tee",
        price_cents=1000,
        sku="TEE-1",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()

    await assign_product_category_from_type(db_session, product, "T-Shirt")
    await db_session.flush()

    categories = (await db_session.execute(select(Category))).scalars().all()
    assert len(categories) == 1
    category = categories[0]
    assert category.meta_title == f"T-Shirt | {store_name}"
    assert category.meta_description == site.meta_description
