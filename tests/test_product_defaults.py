"""Tests for product creation defaults and immutable fields."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.services.product_defaults import (
    apply_product_creation_defaults,
    assign_product_category_from_type,
    default_product_meta,
    enforce_immutable_product_fields,
    product_is_sync_imported,
    validate_api_product_update,
)
from app.core.exceptions import ValidationError
from models.category import Category
from models.product import Product


@pytest.mark.asyncio
async def test_default_product_meta_uses_store_name():
    product = Product(name="Cool Tee", description="Soft cotton tee")
    title, description = default_product_meta(product, "Oshkelosh")
    assert title == "Cool Tee | Oshkelosh"
    assert description == "Soft cotton tee"


@pytest.mark.asyncio
async def test_default_product_meta_includes_product_type_option():
    product = Product(
        name="Amaryllis Solandraeflora",
        description="Botanical art print",
        options={"Product type": "Canvas (in) | Thin"},
    )
    title, description = default_product_meta(product, "Oshkelosh")
    assert title == "Amaryllis Solandraeflora – Canvas (in) | Thin | Oshkelosh"
    assert description == "Botanical art print"


@pytest.mark.asyncio
async def test_apply_product_creation_defaults_uses_product_type_for_slug(db_session):
    product = Product(
        name="Amaryllis Solandraeflora",
        description="Botanical art print",
        price_cents=1000,
        sku="AM-1",
        options={"Product type": "Canvas (in) | Thin"},
    )
    db_session.add(product)
    await db_session.flush()

    await apply_product_creation_defaults(db_session, product, store_name="Oshkelosh")
    await db_session.flush()

    assert product.slug == "amaryllis-solandraeflora-canvas-in-thin"
    assert product.meta_title == "Amaryllis Solandraeflora – Canvas (in) | Thin | Oshkelosh"


@pytest.mark.asyncio
async def test_apply_product_creation_defaults_sets_slug_and_meta(db_session):
    product = Product(
        name="New Widget",
        description="A handy widget",
        price_cents=1000,
        sku="W-1",
    )
    db_session.add(product)
    await db_session.flush()

    await apply_product_creation_defaults(db_session, product, store_name="Oshkelosh")
    await db_session.flush()

    assert product.slug == "new-widget"
    assert product.meta_title == "New Widget | Oshkelosh"
    assert product.meta_description == "A handy widget"


@pytest.mark.asyncio
async def test_assign_product_category_from_type_creates_category(db_session, test_user):
    product = Product(
        name="Synced Tee",
        price_cents=1000,
        sku="TEE-1",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()

    await assign_product_category_from_type(db_session, product, "T-Shirt")

    assert product.category_id is not None
    categories = (await db_session.execute(select(Category))).scalars().all()
    assert len(categories) == 1
    assert categories[0].id == product.category_id
    assert categories[0].name == "T-Shirt"
    assert categories[0].slug == "t-shirt"


def test_product_is_sync_imported_detects_marker():
    product = Product(
        name="Synced",
        tags=[{"supplier_sync": True, "supplier_external_key": "printful:variant:1"}],
    )
    assert product_is_sync_imported(product) is True
    assert product_is_sync_imported(Product(name="Manual")) is False


def test_enforce_immutable_product_fields_rejects_sku_change(test_user):
    product = Product(
        name="Widget",
        sku="W-1",
        created_by=test_user.id,
    )
    error = enforce_immutable_product_fields(
        product,
        None,
        sku="W-2",
        supplier_value="",
        supplier_product_id="",
        supplier_variant_id="",
        category_id=None,
    )
    assert error == "SKU cannot be changed after the product is created."


def test_validate_api_product_update_rejects_sync_category_change():
    product = Product(
        name="Synced",
        category_id=1,
        tags=[{"supplier_sync": True, "supplier_external_key": "printful:variant:1"}],
    )
    with pytest.raises(ValidationError, match="Category cannot be changed"):
        validate_api_product_update(product, {"category_id": 2})


class TestProductImmutableApi:
    async def test_patch_rejects_sku_change(self, client: AsyncClient, test_product, test_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]

        response = await client.patch(
            f"/api/v1/admin/products/{test_product.id}",
            json={"sku": "CHANGED-SKU"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
        body = response.json()
        message = body.get("detail") or body.get("message") or str(body)
        assert "SKU cannot be changed" in message

    async def test_create_applies_defaults(self, client: AsyncClient, test_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]

        response = await client.post(
            "/api/v1/admin/products",
            json={
                "name": "Defaulted Product",
                "description": "Has generated SEO fields",
                "price_cents": 1500,
                "sku": "DEF-001",
                "inventory_quantity": 1,
                "status": "draft",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["slug"] == "defaulted-product"
        assert data["meta_title"] == "Defaulted Product | Oshkelosh"
        assert data["meta_description"] == "Has generated SEO fields"
