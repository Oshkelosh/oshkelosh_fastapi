"""Tests for storefront SEO routes and HTML injection."""

from __future__ import annotations

import models.site_settings  # noqa: F401
import pytest

from app.config import settings
from app.services.product_variants import refresh_product_listing_cache
from app.services.site_settings import update_site_settings
from app.storefront.seo import (
    build_product_json_ld,
    build_product_offers_json_ld,
    inject_seo_into_html,
    render_sitemap_xml,
    SeoMeta,
    _product_primary_image,
)
from models.category import Category
from models.product import Product
from models.product_image import ProductImage
from models.product_variant import ProductVariant


@pytest.fixture(autouse=True)
def seo_site_settings_url_priority(monkeypatch):
    """Let SiteSettings.site_url win over env public_app_url / CORS in SEO tests."""
    monkeypatch.setattr(settings, "public_app_url", None)
    monkeypatch.setattr(settings, "cors_origins", [])


@pytest.mark.asyncio
async def test_robots_txt_disallows_admin_and_api(client, db_session):
    await update_site_settings(db_session, {"site_url": "https://shop.example.com"})
    await db_session.commit()

    response = await client.get("/robots.txt")
    assert response.status_code == 200
    body = response.text
    assert "Disallow: /admin/" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /cart" in body
    assert "Disallow: /checkout" in body
    assert "Disallow: /orders" in body
    assert "Sitemap: https://shop.example.com/sitemap.xml" in body
    assert response.headers.get("cache-control") == "public, max-age=600"


@pytest.mark.asyncio
async def test_sitemap_includes_published_products_only(
    client, db_session, test_product: Product, test_user
):
    await update_site_settings(db_session, {"site_url": "https://shop.example.com"})
    await db_session.commit()

    test_product.slug = "test-product"
    test_product.status = "published"
    db_session.add(test_product)

    draft = Product(
        name="Draft Product",
        slug="draft-product",
        price_cents=999,
        status="draft",
        created_by=test_user.id,
    )
    db_session.add(draft)
    await db_session.flush()

    category = Category(name="Shirts", slug="shirts", description="Shirts category")
    db_session.add(category)
    await db_session.commit()

    response = await client.get("/sitemap.xml")
    assert response.status_code == 200
    body = response.text
    assert "<loc>https://shop.example.com/</loc>" in body
    assert "<loc>https://shop.example.com/products</loc>" in body
    assert "<loc>https://shop.example.com/categories</loc>" in body
    assert "<loc>https://shop.example.com/products/test-product</loc>" in body
    assert "draft-product" not in body
    assert "<loc>https://shop.example.com/categories/shirts</loc>" in body
    assert response.headers.get("cache-control") == "public, max-age=600"


@pytest.mark.asyncio
async def test_product_page_html_injection(client, db_session, test_product: Product):
    await update_site_settings(
        db_session,
        {
            "site_url": "https://shop.example.com",
            "store_name": "Test Shop",
            "meta_description": "Shop great things",
        },
    )
    test_product.slug = "test-product"
    test_product.status = "published"
    test_product.meta_description = "A test product for SEO"
    db_session.add(test_product)
    await db_session.commit()

    response = await client.get("/products/test-product")
    assert response.status_code == 200
    body = response.text
    assert "<title>Test Product | Test Shop</title>" in body
    assert 'meta name="description" content="A test product for SEO"' in body
    assert 'rel="canonical" href="https://shop.example.com/products/test-product"' in body
    assert 'property="og:type" content="product"' in body
    assert 'property="og:site_name" content="Test Shop"' in body
    assert 'name="twitter:card" content="summary_large_image"' in body
    assert 'name="twitter:title" content="Test Product | Test Shop"' in body
    assert 'type="application/ld+json"' in body
    assert '"@type": "Product"' in body
    assert '"@type": "Offer"' in body


@pytest.mark.asyncio
async def test_private_paths_inject_noindex(client, db_session):
    await update_site_settings(
        db_session,
        {"site_url": "https://shop.example.com", "store_name": "Test Shop"},
    )
    await db_session.commit()

    for path in ("/cart", "/checkout", "/account", "/orders", "/login"):
        response = await client.get(path)
        assert response.status_code == 200, path
        body = response.text
        assert 'meta name="robots" content="noindex, nofollow"' in body, path
        assert response.headers.get("cache-control") == "private, no-store", path


@pytest.mark.asyncio
async def test_categories_index_html_injection(client, db_session):
    await update_site_settings(
        db_session,
        {
            "site_url": "https://shop.example.com",
            "store_name": "Test Shop",
            "meta_description": "Shop great things",
        },
    )
    await db_session.commit()

    response = await client.get("/categories")
    assert response.status_code == 200
    body = response.text
    assert "<title>Categories | Test Shop</title>" in body
    assert 'rel="canonical" href="https://shop.example.com/categories"' in body
    assert 'meta name="robots" content="index, follow"' in body


@pytest.mark.asyncio
async def test_product_page_injects_aggregate_offer_for_multi_variant_product(
    client, db_session, test_product: Product, test_variant: ProductVariant
):
    await update_site_settings(
        db_session,
        {
            "site_url": "https://shop.example.com",
            "store_name": "Test Shop",
        },
    )
    second_variant = ProductVariant(
        product_id=test_product.id,
        title="Large",
        position=1,
        price_cents=2499,
        inventory_quantity=5,
        sku="TEST-002",
        status="active",
    )
    db_session.add(second_variant)
    await db_session.flush()
    refresh_product_listing_cache(test_product, [test_variant, second_variant])
    test_product.status = "published"
    db_session.add(test_product)
    await db_session.commit()

    response = await client.get("/products/test-product")
    assert response.status_code == 200
    body = response.text
    assert '"@type": "AggregateOffer"' in body
    assert '"lowPrice": "19.99"' in body
    assert '"highPrice": "24.99"' in body
    assert '"offerCount": 2' in body


@pytest.mark.asyncio
async def test_unknown_product_slug_returns_plain_spa_shell(client, db_session):
    await update_site_settings(db_session, {"site_url": "https://shop.example.com"})
    await db_session.commit()

    response = await client.get("/products/does-not-exist")
    assert response.status_code == 200
    body = response.text
    assert "<!DOCTYPE html>" in body.lower() or "<html" in body.lower()
    assert 'rel="canonical" href="https://shop.example.com/products/does-not-exist"' not in body


@pytest.mark.asyncio
async def test_get_product_by_slug_api(client, db_session, test_product: Product):
    test_product.slug = "seo-api-product"
    test_product.status = "published"
    db_session.add(test_product)
    await db_session.commit()

    response = await client.get("/api/v1/products/by-slug/seo-api-product")
    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "seo-api-product"
    assert payload["name"] == "Test Product"


def test_inject_seo_into_html_replaces_title_and_adds_meta():
    html = """<!DOCTYPE html>
<html><head><title>Old</title></head><body></body></html>"""
    meta = SeoMeta(
        title="New Title",
        description="New description",
        canonical_url="https://shop.example.com/products/foo",
        og_type="product",
        site_name="Test Shop",
        json_ld=[{"@type": "Product", "name": "Foo"}],
    )
    result = inject_seo_into_html(html, meta)
    assert "<title>New Title</title>" in result
    assert "Old" not in result
    assert 'meta name="description" content="New description"' in result
    assert 'rel="canonical" href="https://shop.example.com/products/foo"' in result
    assert 'property="og:site_name" content="Test Shop"' in result
    assert 'name="twitter:title" content="New Title"' in result
    assert '"@type": "Product"' in result


def test_render_sitemap_xml_escapes_urls():
    product = Product(
        id=1,
        name="Test",
        slug="test",
        price_cents=100,
        status="published",
    )
    xml = render_sitemap_xml("https://shop.example.com", products=[product], categories=[])
    assert "<loc>https://shop.example.com/products/test</loc>" in xml
    assert "<loc>https://shop.example.com/categories</loc>" in xml


def test_build_product_offers_single_variant():
    product = Product(
        name="Tee",
        slug="tee",
        price_cents=1500,
        inventory_quantity=10,
        has_variants=False,
    )
    variant = ProductVariant(
        product_id=1,
        title="Default",
        position=0,
        price_cents=1500,
        inventory_quantity=10,
        sku="SKU-1",
        status="active",
    )
    offers = build_product_offers_json_ld(product, "https://shop.example.com", [variant])
    assert offers["@type"] == "Offer"
    assert offers["price"] == "15.00"
    assert offers["availability"] == "https://schema.org/InStock"


def test_build_product_offers_aggregate_for_multi_variant():
    product = Product(
        name="Tee",
        slug="tee",
        price_cents=1500,
        inventory_quantity=15,
        has_variants=True,
    )
    variants = [
        ProductVariant(
            product_id=1,
            title="Small",
            position=0,
            price_cents=1500,
            inventory_quantity=10,
            status="active",
        ),
        ProductVariant(
            product_id=1,
            title="Large",
            position=1,
            price_cents=2000,
            inventory_quantity=5,
            status="active",
        ),
    ]
    offers = build_product_offers_json_ld(product, "https://shop.example.com", variants)
    assert offers["@type"] == "AggregateOffer"
    assert offers["lowPrice"] == "15.00"
    assert offers["highPrice"] == "20.00"
    assert offers["offerCount"] == 2


def test_build_product_json_ld_uses_variant_sku_for_single_variant():
    product = Product(
        name="Tee",
        slug="tee",
        price_cents=1500,
        sku="PRODUCT-SKU",
        inventory_quantity=1,
        has_variants=False,
    )
    variant = ProductVariant(
        product_id=1,
        title="Default",
        position=0,
        price_cents=1500,
        inventory_quantity=1,
        sku="VARIANT-SKU",
        status="active",
    )
    payload = build_product_json_ld(product, "https://shop.example.com", None, [variant])
    assert payload["sku"] == "VARIANT-SKU"
    assert payload["offers"]["@type"] == "Offer"


@pytest.mark.asyncio
async def test_product_primary_image_prefers_shared_image(db_session, test_product: Product):
    variant = test_product._test_variant  # type: ignore[attr-defined]
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            variant_id=variant.id,
            url="https://cdn.example.com/variant.jpg",
            sort_order=0,
        )
    )
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            variant_id=None,
            url="https://cdn.example.com/shared.jpg",
            sort_order=1,
        )
    )
    await db_session.commit()

    image_url = await _product_primary_image(db_session, test_product)
    assert image_url == "https://cdn.example.com/shared.jpg"
