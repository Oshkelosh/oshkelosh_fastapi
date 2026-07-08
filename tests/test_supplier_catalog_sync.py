"""Tests for supplier catalog import and sync."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.addons.suppliers.printful.catalog import normalize_printful_catalog_products
from app.addons.suppliers.printify.catalog import normalize_printify_catalog_products
from app.core.exceptions import ValidationError
from app.services.product_defaults import product_is_sync_imported
from app.services.supplier_catalog_sync import (
    SupplierCatalogSyncOptions,
    sync_supplier_catalog,
)
from models.category import Category
from models.product import Product
from models.product_variant import ProductVariant
import models.product_image  # noqa: F401 — register table for tests


async def _auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _mock_addon(catalog_products: list) -> MagicMock:
    addon = MagicMock()
    addon.is_enabled = True
    addon.supports_catalog_sync = MagicMock(return_value=True)
    addon.fetch_catalog_for_import = AsyncMock(return_value=catalog_products)
    return addon


@pytest.mark.asyncio
async def test_sync_creates_product_with_defaults(db_session, test_user):
    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "4752058849",
                "sync_product_id": "100",
                "sync_product_name": "Cool Tee",
                "name": "Cool Tee / M",
                "description": "Soft tee",
                "retail_price": "24.50",
                "sku": "TEE-M",
                "synced": True,
                "size": "M",
                "thumbnail_url": "https://example.com/thumb.jpg",
                "product_type": "T-Shirt",
            }
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 1
    assert result.variants_created == 1

    products = (await db_session.execute(select(Product))).scalars().all()
    product = products[0]
    assert product.slug == "cool-tee-t-shirt"
    assert product.meta_title == "Cool Tee – T-Shirt | Oshkelosh"
    assert product.category_id is not None
    category = (
        await db_session.execute(select(Category).where(Category.id == product.category_id))
    ).scalar_one()
    assert category.slug == "t-shirt"
    assert product.options.get("Product type") == "T-Shirt"

    variants = (await db_session.execute(select(ProductVariant))).scalars().all()
    assert len(variants) == 1
    assert variants[0].supplier_external_key == "printful:variant:4752058849"


@pytest.mark.asyncio
async def test_sync_same_design_name_different_product_types_get_distinct_slugs(
    db_session, test_user
):
    """Same sync product name on different base products must not get -2 slug suffixes."""
    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "4765920979",
                "sync_product_id": "378560852",
                "sync_product_name": "Amaryllis Solandraeflora",
                "name": "Amaryllis Solandraeflora / 12″×16″",
                "retail_price": "37.00",
                "sku": "thin-12x16",
                "synced": True,
                "size": "12″×16″",
                "product_type": "Canvas (in) | Thin",
            },
            {
                "id": "4765920980",
                "sync_product_id": "378560853",
                "sync_product_name": "Amaryllis Solandraeflora",
                "name": "Amaryllis Solandraeflora / 12″×16″",
                "retail_price": "45.00",
                "sku": "framed-12x16",
                "synced": True,
                "size": "12″×16″",
                "product_type": "Canvas (in) | Framed",
            },
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 2
    products = (await db_session.execute(select(Product))).scalars().all()
    slugs = {product.slug for product in products}
    assert slugs == {
        "amaryllis-solandraeflora-canvas-in-thin",
        "amaryllis-solandraeflora-canvas-in-framed",
    }


@pytest.mark.asyncio
async def test_sync_creates_product_with_supplier_tags(db_session, test_user):
    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "4752058849",
                "sync_product_id": "100",
                "sync_product_name": "Cool Tee",
                "name": "Cool Tee / M",
                "retail_price": "24.50",
                "sku": "TEE-M",
                "synced": True,
                "size": "M",
                "thumbnail_url": "https://example.com/thumb.jpg",
            }
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 1
    assert result.errors == []

    products = (await db_session.execute(select(Product))).scalars().all()
    assert len(products) == 1
    product = products[0]
    assert product.name == "Cool Tee"
    assert product.price_cents == 2450
    assert product.status == "draft"
    assert product.supplier_external_product_key == "printful:product:100"

    variants = (await db_session.execute(select(ProductVariant))).scalars().all()
    assert len(variants) == 1
    assert variants[0].supplier_product_id == "4752058849"


@pytest.mark.asyncio
async def test_sync_updates_existing_product_by_external_key(db_session, test_user):
    existing = Product(
        name="Old name",
        price_cents=1000,
        sku="old-sku",
        inventory_quantity=5,
        status="published",
        supplier_external_product_key="printful:product:100",
        tags=[],
        created_by=test_user.id,
    )
    db_session.add(existing)
    await db_session.flush()
    variant = ProductVariant(
        product_id=existing.id,
        title="Old variant",
        price_cents=1000,
        inventory_quantity=5,
        sku="old-sku",
        status="active",
        supplier_addon_id="printful",
        supplier_product_id="4752058849",
        supplier_external_key="printful:variant:4752058849",
    )
    db_session.add(variant)
    await db_session.commit()

    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "4752058849",
                "sync_product_id": "100",
                "sync_product_name": "Cool Tee",
                "name": "Updated Tee / M",
                "retail_price": "29.99",
                "sku": "TEE-M-NEW",
                "synced": True,
                "size": "M",
            }
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 0
    assert result.updated == 1
    assert result.variants_updated == 1

    await db_session.refresh(existing)
    await db_session.refresh(variant)
    assert existing.name == "Cool Tee"
    assert existing.price_cents == 2999
    assert existing.sku == "old-sku"
    assert existing.status == "published"
    assert product_is_sync_imported(existing) is True
    assert variant.price_cents == 2999
    assert variant.inventory_quantity == 5


@pytest.mark.asyncio
async def test_sync_preserves_existing_product_options(db_session, test_user):
    existing = Product(
        name="Old name",
        price_cents=1000,
        sku="old-sku",
        inventory_quantity=5,
        status="published",
        supplier_external_product_key="printful:product:100",
        options={"Material": "Cotton"},
        tags=[],
        created_by=test_user.id,
    )
    db_session.add(existing)
    await db_session.flush()
    variant = ProductVariant(
        product_id=existing.id,
        title="Old variant",
        price_cents=1000,
        inventory_quantity=5,
        sku="old-sku",
        status="active",
        supplier_addon_id="printful",
        supplier_product_id="4752058849",
        supplier_external_key="printful:variant:4752058849",
    )
    db_session.add(variant)
    await db_session.commit()

    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "4752058849",
                "sync_product_id": "100",
                "sync_product_name": "Cool Tee",
                "name": "Updated Tee / M",
                "description": "Remote supplier description",
                "retail_price": "29.99",
                "sku": "TEE-M-NEW",
                "synced": True,
                "size": "M",
                "product_type": "T-Shirt",
            }
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    await db_session.refresh(existing)
    assert existing.description == "Remote supplier description"
    assert existing.options == {"Material": "Cotton"}


@pytest.mark.asyncio
async def test_archive_missing_archives_orphaned_variants(db_session, test_user):
    product = Product(
        name="Printify product",
        price_cents=2000,
        status="published",
        supplier_external_product_key="printify:p2",
        tags=[],
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()
    kept_variant = ProductVariant(
        product_id=product.id,
        title="Still here",
        price_cents=2000,
        inventory_quantity=9999,
        status="active",
        supplier_addon_id="printify",
        supplier_product_id="p2",
        supplier_variant_id="v2",
        supplier_external_key="printify:p2:v2",
    )
    orphan_product = Product(
        name="Gone",
        price_cents=1000,
        status="published",
        supplier_external_product_key="printify:p1",
        tags=[],
        created_by=test_user.id,
    )
    db_session.add(orphan_product)
    await db_session.flush()
    orphan_variant = ProductVariant(
        product_id=orphan_product.id,
        title="Gone variant",
        price_cents=1000,
        inventory_quantity=9999,
        status="active",
        supplier_addon_id="printify",
        supplier_product_id="p1",
        supplier_variant_id="v1",
        supplier_external_key="printify:p1:v1",
    )
    db_session.add(kept_variant)
    db_session.add(orphan_variant)
    await db_session.commit()

    catalog = normalize_printify_catalog_products(
        [
            {
                "product_id": "p2",
                "variant_id": "v2",
                "title": "Still here",
                "price": 2000,
                "is_enabled": True,
                "visible": True,
            }
        ]
    )
    mock_addon = _mock_addon(catalog)

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        result = await sync_supplier_catalog(
            db_session,
            "printify",
            SupplierCatalogSyncOptions(archive_missing=True),
            actor_user_id=test_user.id,
        )

    assert result.variants_archived >= 1
    await db_session.refresh(orphan_variant)
    assert orphan_variant.status == "archived"


@pytest.mark.asyncio
async def test_manual_supplier_sync_rejected(db_session):
    manual = MagicMock()
    manual.supports_catalog_sync = MagicMock(return_value=False)
    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=manual):
        with pytest.raises(ValidationError, match="not supported"):
            await sync_supplier_catalog(
                db_session,
                "manual",
                SupplierCatalogSyncOptions(),
            )


@pytest.mark.asyncio
async def test_admin_api_sync_endpoint(client: AsyncClient, test_user, db_session):
    catalog = normalize_printful_catalog_products(
        [
            {
                "id": "999",
                "sync_product_id": "50",
                "sync_product_name": "API Sync Tee",
                "name": "API Sync Tee / M",
                "retail_price": "10.00",
                "synced": True,
                "size": "M",
            }
        ]
    )
    mock_addon = _mock_addon(catalog)
    headers = await _auth_headers(client, test_user.email, "SecurePass123!")

    with patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon):
        response = await client.post(
            "/api/v1/admin/suppliers/printful/sync",
            headers=headers,
            json={"import_status": "published", "archive_missing": False},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert "created 1 products" in body["message"]
