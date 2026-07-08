"""Tests for product image upload, import, and admin UI."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlmodel import col, select

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.services.image_processing import process_product_image
from app.services.product_images import (
    delete_product_image,
    import_images_from_urls,
    primary_image_urls_for_products,
    product_image_to_dict,
    upload_product_image,
    variant_keys_from_primary_key,
    variant_urls_from_primary_url,
)
from app.services.supplier_catalog_sync import SupplierCatalogSyncOptions, sync_supplier_catalog
from models.product import Product
from models.product_image import ProductImage
import models.product_image  # noqa: F401 — register table for tests


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


def _tiny_png_bytes() -> bytes:
    image = Image.new("RGB", (1, 1), color=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _large_png_bytes(width: int = 3000, height: int = 2000) -> bytes:
    image = Image.new("RGB", (width, height), color=(0, 128, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _storage_mock(base_url: str = "http://testserver/media/files") -> MagicMock:
    storage = MagicMock()

    async def _upload(key: str, content: bytes, content_type: str) -> str:
        del content, content_type
        return f"{base_url}/{key}"

    storage.upload = AsyncMock(side_effect=_upload)
    storage.delete = AsyncMock()
    return storage


def test_process_product_image_outputs_webp_variants():
    processed = process_product_image(_large_png_bytes(), source_content_type="image/png")

    assert set(processed.variants) == {"full", "card", "thumb"}
    for name, (content, content_type) in processed.variants.items():
        assert content_type == "image/webp"
        assert content[:4] == b"RIFF"
        image = Image.open(BytesIO(content))
        if name == "full":
            assert max(image.size) <= 2000
        elif name == "card":
            assert max(image.size) <= 800
        else:
            assert max(image.size) <= 256


def test_variant_urls_from_primary_url():
    full = "http://testserver/media/files/products/abc123/full.webp"
    assert variant_urls_from_primary_url(full) == {
        "card": "http://testserver/media/files/products/abc123/card.webp",
        "thumb": "http://testserver/media/files/products/abc123/thumb.webp",
    }


def test_variant_keys_from_primary_key():
    full_key = "products/abc123/full.webp"
    assert variant_keys_from_primary_key(full_key) == [
        "products/abc123/full.webp",
        "products/abc123/card.webp",
        "products/abc123/thumb.webp",
    ]


@pytest.mark.asyncio
async def test_upload_product_image_creates_row(db_session, test_user):
    product = Product(
        name="Widget",
        price_cents=1000,
        sku="W-IMG",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()

    storage = _storage_mock()

    image = await upload_product_image(
        db_session,
        product,
        _tiny_png_bytes(),
        "image/png",
        storage=storage,
        alt_text="Widget photo",
    )

    assert image.url.endswith("/full.webp")
    assert image.alt_text == "Widget photo"
    assert image.sort_order == 0
    assert storage.upload.await_count == 3
    uploaded_keys = [call.args[0] for call in storage.upload.await_args_list]
    assert uploaded_keys[0].endswith("/full.webp")
    assert uploaded_keys[1].endswith("/card.webp")
    assert uploaded_keys[2].endswith("/thumb.webp")


@pytest.mark.asyncio
async def test_delete_product_image_removes_all_variants(db_session, test_user):
    product = Product(
        name="Delete Me",
        price_cents=100,
        sku="DEL-IMG",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()

    storage = _storage_mock()
    image = await upload_product_image(
        db_session,
        product,
        _tiny_png_bytes(),
        "image/png",
        storage=storage,
    )

    await delete_product_image(db_session, image, storage=storage)

    deleted_keys = [call.args[0] for call in storage.delete.await_args_list]
    assert len(deleted_keys) == 3
    assert all(key.endswith(".webp") for key in deleted_keys)


@pytest.mark.asyncio
async def test_product_image_to_dict_includes_variants(db_session, test_user):
    product = Product(name="Dict", price_cents=100, sku="DICT-1", created_by=test_user.id)
    db_session.add(product)
    await db_session.flush()

    storage = _storage_mock()
    image = await upload_product_image(
        db_session,
        product,
        _tiny_png_bytes(),
        "image/png",
        storage=storage,
    )

    payload = product_image_to_dict(image)
    assert payload["url"].endswith("/full.webp")
    assert payload["variants"]["card"].endswith("/card.webp")
    assert payload["variants"]["thumb"].endswith("/thumb.webp")


@pytest.mark.asyncio
async def test_import_images_from_urls_downloads_and_stores(db_session, test_user):
    product = Product(
        name="Imported",
        price_cents=500,
        sku="IMP-1",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()

    storage = _storage_mock()

    with patch(
        "app.services.product_images.download_remote_image",
        AsyncMock(return_value=(_tiny_png_bytes(), "image/png")),
    ):
        created = await import_images_from_urls(
            db_session,
            product,
            ["https://supplier.example/mockup.jpg"],
            storage=storage,
            alt_text="Imported",
        )

    assert len(created) == 1
    assert created[0].url.endswith("/full.webp")
    assert storage.upload.await_count == 3


@pytest.mark.asyncio
async def test_primary_image_urls_for_products(db_session, test_user):
    first = Product(name="A", price_cents=100, sku="A-1", created_by=test_user.id)
    second = Product(name="B", price_cents=200, sku="B-1", created_by=test_user.id)
    db_session.add(first)
    db_session.add(second)
    await db_session.flush()

    db_session.add(
        ProductImage(
            product_id=first.id,
            url="http://example.com/products/a/full.webp",
            sort_order=1,
        )
    )
    db_session.add(
        ProductImage(
            product_id=first.id,
            url="http://example.com/products/b/full.webp",
            sort_order=0,
        )
    )
    db_session.add(
        ProductImage(
            product_id=second.id,
            url="http://example.com/products/c/full.webp",
            sort_order=0,
        )
    )
    await db_session.flush()

    urls = await primary_image_urls_for_products(db_session, [first.id, second.id])
    assert urls[first.id] == "http://example.com/products/b/thumb.webp"
    assert urls[second.id] == "http://example.com/products/c/thumb.webp"


@pytest.mark.asyncio
async def test_sync_create_downloads_images_not_update(db_session, test_user):
    from app.addons.suppliers.printful.catalog import normalize_printful_catalog

    catalog = normalize_printful_catalog(
        [
            {
                "id": "4752058849",
                "name": "Cool Tee / M",
                "retail_price": "24.50",
                "sku": "TEE-M",
                "synced": True,
                "thumbnail_url": "https://example.com/thumb.jpg",
                "image_urls": ["https://example.com/thumb.jpg"],
            }
        ]
    )
    mock_addon = MagicMock()
    mock_addon.is_enabled = True
    mock_addon.supports_catalog_sync = MagicMock(return_value=True)
    mock_addon.fetch_catalog_for_import = AsyncMock(return_value=catalog)

    storage = _storage_mock()

    with (
        patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon),
        patch("app.services.supplier_catalog_sync.get_storage", return_value=storage),
        patch(
            "app.services.product_images.download_remote_image",
            AsyncMock(return_value=(_tiny_png_bytes(), "image/png")),
        ),
    ):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 1
    images = (await db_session.execute(select(ProductImage))).scalars().all()
    assert len(images) == 1
    assert images[0].url.endswith("/full.webp")
    assert images[0].alt_text == "Cool Tee / M"

    products = (await db_session.execute(select(Product))).scalars().all()
    product = products[0]
    original_url = images[0].url

    updated_catalog = normalize_printful_catalog(
        [
            {
                "id": "4752058849",
                "name": "Updated Tee / M",
                "retail_price": "29.99",
                "sku": "TEE-M-NEW",
                "synced": True,
                "thumbnail_url": "https://example.com/new-thumb.jpg",
                "image_urls": ["https://example.com/new-thumb.jpg"],
            }
        ]
    )
    mock_addon.fetch_catalog_for_import = AsyncMock(return_value=updated_catalog)

    with (
        patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon),
        patch("app.services.supplier_catalog_sync.get_storage", return_value=storage),
        patch(
            "app.services.product_images.download_remote_image",
            AsyncMock(return_value=(_tiny_png_bytes(), "image/png")),
        ),
    ):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.updated == 1
    await db_session.refresh(product)
    images_after = (await db_session.execute(select(ProductImage))).scalars().all()
    assert len(images_after) == 1
    assert images_after[0].url == original_url


@pytest.mark.asyncio
async def test_sync_import_uses_per_image_alt_texts(db_session, test_user):
    from app.addons.suppliers.printful.catalog import normalize_printful_catalog

    catalog = normalize_printful_catalog(
        [
            {
                "id": "4752058849",
                "name": "Cool Tee / M",
                "retail_price": "24.50",
                "sku": "TEE-M",
                "synced": True,
                "image_urls": [
                    "https://example.com/preview.jpg",
                    "https://example.com/product.jpg",
                ],
                "image_alt_texts": [
                    "Cool Tee / M",
                    "Thin Canvas (12″×16″)",
                ],
            }
        ]
    )
    mock_addon = MagicMock()
    mock_addon.is_enabled = True
    mock_addon.supports_catalog_sync = MagicMock(return_value=True)
    mock_addon.fetch_catalog_for_import = AsyncMock(return_value=catalog)

    storage = _storage_mock()

    with (
        patch("app.services.supplier_catalog_sync.get_supplier_addon", return_value=mock_addon),
        patch("app.services.supplier_catalog_sync.get_storage", return_value=storage),
        patch(
            "app.services.product_images.download_remote_image",
            AsyncMock(return_value=(_tiny_png_bytes(), "image/png")),
        ),
    ):
        result = await sync_supplier_catalog(
            db_session,
            "printful",
            SupplierCatalogSyncOptions(import_status="draft"),
            actor_user_id=test_user.id,
        )

    assert result.created == 1
    images = (
        await db_session.execute(
            select(ProductImage).order_by(col(ProductImage.sort_order).asc())
        )
    ).scalars().all()
    assert len(images) == 2
    assert images[0].alt_text == "Cool Tee / M"
    assert images[1].alt_text == "Thin Canvas (12″×16″)"


@pytest.mark.asyncio
async def test_admin_product_image_upload(client: AsyncClient, test_user, db_session, test_product):
    cookies, csrf = _admin_session(test_user.id)
    png_bytes = _tiny_png_bytes()

    storage = _storage_mock()

    with patch("app.storage.get_storage", return_value=storage):
        response = await client.post(
            f"/admin/products/{test_product.id}/images",
            cookies=cookies,
            data={"csrf_token": csrf, "alt_text": "Admin shot"},
            files={"file": ("shot.png", BytesIO(png_bytes), "image/png")},
        )

    assert response.status_code == 302
    assert response.headers["location"] == f"/admin/products/{test_product.id}"

    result = await db_session.execute(
        select(ProductImage).where(ProductImage.product_id == test_product.id)
    )
    images = result.scalars().all()
    assert len(images) == 1
    assert images[0].alt_text == "Admin shot"
    assert images[0].url.endswith("/full.webp")
    assert storage.upload.await_count == 3


@pytest.mark.asyncio
async def test_admin_products_list_shows_thumbnail(client: AsyncClient, test_user, db_session, test_product):
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            url="http://testserver/media/files/products/list-group/full.webp",
            sort_order=0,
        )
    )
    await db_session.flush()

    cookies, _csrf = _admin_session(test_user.id)
    response = await client.get("/admin/products", cookies=cookies)

    assert response.status_code == 200
    assert "list-group/thumb.webp" in response.text
    assert "product-thumb" in response.text


@pytest.mark.asyncio
async def test_media_url_requires_admin_auth(client: AsyncClient):
    response = await client.get("/api/v1/media/products/example/full.webp")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_product_edit_form_no_nested_forms_with_images(
    client: AsyncClient, test_user, db_session, test_product
):
    """Image delete forms must not nest inside the main product save form."""
    from app.main import app

    app.state.needs_setup = False
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            url="http://testserver/media/files/products/edit-form-thumb.jpg",
            sort_order=0,
        )
    )
    await db_session.flush()

    cookies, _csrf = _admin_session(test_user.id)
    response = await client.get(f"/admin/products/{test_product.id}", cookies=cookies)

    assert response.status_code == 200
    html = response.text
    form_marker = f'<form method="POST" action="/admin/products/{test_product.id}"'
    form_start = html.index(form_marker)
    save_pos = html.index("Save Product")
    main_form_region = html[form_start:save_pos]
    assert main_form_region.count("<form") == 1, "nested forms detected before Save Product"
    assert 'name="status"' in main_form_region


@pytest.mark.asyncio
async def test_api_list_includes_relational_images(client: AsyncClient, db_session, test_product):
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            url="http://example.com/api-list.jpg",
            sort_order=0,
            alt_text="List shot",
        )
    )
    await db_session.flush()

    response = await client.get("/api/v1/products")
    assert response.status_code == 200
    payload = response.json()
    item = next(row for row in payload["items"] if row["id"] == test_product.id)
    assert item["images"] == [
        {
            "id": item["images"][0]["id"],
            "url": "http://example.com/api-list.jpg",
            "variants": {},
            "alt_text": "List shot",
            "sort_order": 0,
            "variant_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_api_product_by_slug_includes_relational_images(
    client: AsyncClient, db_session, test_product
):
    db_session.add(
        ProductImage(
            product_id=test_product.id,
            url="http://example.com/api-slug.jpg",
            sort_order=0,
        )
    )
    await db_session.flush()

    response = await client.get(f"/api/v1/products/by-slug/{test_product.slug}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["images"][0]["url"] == "http://example.com/api-slug.jpg"
