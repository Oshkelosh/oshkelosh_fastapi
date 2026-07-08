"""Tests for Printful catalog normalization helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.printful.catalog import (
    build_printful_catalog_row,
    humanize_printful_type,
    merge_printful_variant_files,
    merge_printful_variant_payload,
    normalize_printful_catalog_products,
    printful_variant_attributes_from_row,
    printful_variant_image_alt_texts,
    printful_variant_image_url,
    printful_variant_image_urls,
    printful_variant_product_type,
    resolve_printful_catalog_product_type,
)


def test_humanize_printful_type():
    assert humanize_printful_type("T-SHIRT") == "T Shirt"
    assert humanize_printful_type("T-Shirt") == "T-Shirt"


def test_printful_variant_product_type_uses_main_category_id():
    product_type = printful_variant_product_type(
        {
            "main_category_id": 24,
            "product": {"product_id": 301, "name": "Bella Canvas Tee"},
        },
        category_titles={24: "T-Shirts"},
    )
    assert product_type == "T-Shirts"


@pytest.mark.asyncio
async def test_resolve_printful_catalog_product_type_fetches_catalog_product():
    client = type("Client", (), {})()
    client.get_catalog_product = AsyncMock(
        return_value={
            "result": {
                "product": {
                    "type_name": "T-Shirt",
                    "type": "T-SHIRT",
                }
            }
        }
    )
    cache: dict[int, str] = {}
    resolved = await resolve_printful_catalog_product_type(
        client,
        {"product": {"product_id": 71}},
        catalog_cache=cache,
    )
    assert resolved == "T-Shirt"
    assert cache[71] == "T-Shirt"
    client.get_catalog_product.assert_awaited_once_with("71")


PREVIEW_URL = "https://example.com/preview.jpg"
PRODUCT_IMAGE_URL = "https://example.com/product.jpg"
FALLBACK_URL = "https://example.com/fallback.jpg"


def _variant_with_images(
    *,
    preview_url: str | None = PREVIEW_URL,
    product_image: str | None = PRODUCT_IMAGE_URL,
    product_name: str | None = "Thin Canvas (12″×16″)",
    variant_name: str | None = "Amaryllis Solandraeflora / 12″×16″",
    preview_visible: bool = True,
    extra_files: list[dict] | None = None,
) -> dict:
    files: list[dict] = []
    if preview_url is not None:
        files.append(
            {
                "type": "preview",
                "preview_url": preview_url,
                "visible": preview_visible,
            }
        )
    if extra_files:
        files.extend(extra_files)
    product: dict[str, Any] = {}
    if product_image:
        product["image"] = product_image
    if product_name:
        product["name"] = product_name
    variant: dict[str, Any] = {"files": files, "product": product}
    if variant_name:
        variant["name"] = variant_name
    return variant


def test_printful_variant_image_urls_preview_then_product():
    urls = printful_variant_image_urls(_variant_with_images())
    assert urls == [PREVIEW_URL, PRODUCT_IMAGE_URL]


def test_printful_variant_image_urls_dedupes_same_url():
    urls = printful_variant_image_urls(
        _variant_with_images(preview_url=PRODUCT_IMAGE_URL, product_image=PRODUCT_IMAGE_URL)
    )
    assert urls == [PRODUCT_IMAGE_URL]


def test_printful_variant_image_urls_preview_only():
    urls = printful_variant_image_urls(_variant_with_images(product_image=None))
    assert urls == [PREVIEW_URL]


def test_printful_variant_image_urls_product_image_only():
    urls = printful_variant_image_urls(_variant_with_images(preview_url=None))
    assert urls == [PRODUCT_IMAGE_URL]


def test_printful_variant_image_urls_ignores_non_preview_files():
    urls = printful_variant_image_urls(
        _variant_with_images(
            preview_url=None,
            extra_files=[
                {"type": "mockup", "preview_url": "https://example.com/mockup.jpg", "visible": True},
                {"type": "default", "url": "https://example.com/default.jpg", "visible": True},
            ],
        )
    )
    assert urls == [PRODUCT_IMAGE_URL]


def test_printful_variant_image_urls_uses_invisible_preview():
    urls = printful_variant_image_urls(
        _variant_with_images(preview_visible=False, product_image=None)
    )
    assert urls == [PREVIEW_URL]


def test_printful_variant_image_urls_preview_falls_back_to_url_on_file():
    urls = printful_variant_image_urls(
        {
            "files": [
                {
                    "type": "preview",
                    "preview_url": "",
                    "url": "https://example.com/preview-via-url.jpg",
                    "visible": False,
                }
            ],
            "product": {},
        }
    )
    assert urls == ["https://example.com/preview-via-url.jpg"]


def test_printful_variant_image_urls_fallback_when_empty():
    urls = printful_variant_image_urls({}, fallback=FALLBACK_URL)
    assert urls == [FALLBACK_URL]


def test_printful_variant_image_urls_no_fallback_when_sources_present():
    urls = printful_variant_image_urls(_variant_with_images(), fallback=FALLBACK_URL)
    assert urls == [PREVIEW_URL, PRODUCT_IMAGE_URL]


def test_printful_variant_image_urls_empty_without_fallback():
    assert printful_variant_image_urls({}) == []


def test_printful_variant_image_alt_texts_preview_then_product_name():
    alts = printful_variant_image_alt_texts(
        _variant_with_images(),
        product_name="Amaryllis Solandraeflora",
    )
    assert alts == ["Amaryllis Solandraeflora / 12″×16″", "Thin Canvas (12″×16″)"]


def test_printful_variant_image_alt_texts_product_only_uses_catalog_product_name():
    alts = printful_variant_image_alt_texts(
        _variant_with_images(preview_url=None),
        product_name="Amaryllis Solandraeflora",
    )
    assert alts == ["Thin Canvas (12″×16″)"]


def test_printful_variant_image_alt_texts_deduped_url_uses_preview_alt():
    alts = printful_variant_image_alt_texts(
        _variant_with_images(preview_url=PRODUCT_IMAGE_URL, product_image=PRODUCT_IMAGE_URL),
        product_name="Amaryllis Solandraeflora",
    )
    assert alts == ["Amaryllis Solandraeflora / 12″×16″"]


def test_printful_variant_image_url_primary_order():
    assert printful_variant_image_url(_variant_with_images()) == PREVIEW_URL
    assert (
        printful_variant_image_url(_variant_with_images(preview_url=None)) == PRODUCT_IMAGE_URL
    )
    assert printful_variant_image_url({}, fallback=FALLBACK_URL) == FALLBACK_URL


AMARYLLIS_DEFAULT_FILE = {
    "id": 785188832,
    "type": "default",
    "preview_url": "https://files.cdn.printful.com/files/a15/a1568e277c7987ca9d17213f54157d1f_preview.png",
    "visible": True,
}
AMARYLLIS_PREVIEW_FILE = {
    "id": 810876135,
    "type": "preview",
    "preview_url": "https://files.cdn.printful.com/files/cc2/cc261ecfa856c1b1bb8d33c7c25a7bd7_preview.png",
    "visible": False,
}
AMARYLLIS_PRODUCT_IMAGE = "https://files.cdn.printful.com/products/616/15702_1660725256.jpg"


def _amaryllis_product_detail_stub() -> dict:
    return {
        "id": 4765920979,
        "name": "Amaryllis Solandraeflora / 12″×16″",
        "synced": True,
        "sku": "67E1024BC801F_12″x16″",
        "retail_price": "37.00",
        "size": "12″×16″",
        "product": {
            "variant_id": 15702,
            "product_id": 616,
            "image": AMARYLLIS_PRODUCT_IMAGE,
            "name": "Thin Canvas (12″×16″)",
        },
        "files": [AMARYLLIS_DEFAULT_FILE, AMARYLLIS_PREVIEW_FILE],
    }


def _amaryllis_variant_detail_only_default() -> dict:
    return {
        "id": 4765920979,
        "name": "Amaryllis Solandraeflora / 12″×16″",
        "synced": True,
        "sku": "67E1024BC801F_12″x16″",
        "retail_price": "37.00",
        "size": "12″×16″",
        "product": {
            "variant_id": 15702,
            "product_id": 616,
            "image": AMARYLLIS_PRODUCT_IMAGE,
            "name": "Thin Canvas (12″×16″)",
        },
        "files": [AMARYLLIS_DEFAULT_FILE],
    }


def test_merge_printful_variant_files_keeps_stub_preview_when_missing_from_detail():
    merged_files = merge_printful_variant_files(
        _amaryllis_product_detail_stub()["files"],
        _amaryllis_variant_detail_only_default()["files"],
    )
    file_types = [entry["type"] for entry in merged_files]
    assert file_types == ["default", "preview"]


def test_merge_printful_variant_payload_preserves_preview_mockup():
    merged = merge_printful_variant_payload(
        _amaryllis_product_detail_stub(),
        _amaryllis_variant_detail_only_default(),
    )
    urls = printful_variant_image_urls(merged)
    assert urls == [AMARYLLIS_PREVIEW_FILE["preview_url"], AMARYLLIS_PRODUCT_IMAGE]


def test_build_printful_catalog_row_uses_merged_preview_and_product_image():
    merged = merge_printful_variant_payload(
        _amaryllis_product_detail_stub(),
        _amaryllis_variant_detail_only_default(),
    )
    row = build_printful_catalog_row(
        merged,
        product_id=378560852,
        product_name="Amaryllis Solandraeflora",
        product_thumbnail="https://files.cdn.printful.com/files/e61/e619e186c6fc51a81e9f98eeca923b05_preview.png",
    )
    assert row["image_urls"] == [
        AMARYLLIS_PREVIEW_FILE["preview_url"],
        AMARYLLIS_PRODUCT_IMAGE,
    ]
    assert row["image_alt_texts"] == [
        "Amaryllis Solandraeflora / 12″×16″",
        "Thin Canvas (12″×16″)",
    ]
    assert row["thumbnail_url"] == AMARYLLIS_PREVIEW_FILE["preview_url"]


def test_printful_variant_attributes_from_row_size_only_not_option():
    """Printful name is a title; must not become a storefront Option picker axis."""
    row = build_printful_catalog_row(
        _amaryllis_product_detail_stub(),
        product_id=378560852,
        product_name="Amaryllis Solandraeflora",
        product_thumbnail=None,
    )
    attributes = printful_variant_attributes_from_row(row)
    assert attributes == {"Size": "12″×16″"}
    assert "Option" not in attributes


def test_normalize_printful_catalog_products_canvas_has_size_only_attributes():
    """Grouped import from real Printful canvas shape — one Size picker, no Option."""
    products = normalize_printful_catalog_products(
        [
            {
                "id": "4765920979",
                "sync_product_id": "378560852",
                "sync_product_name": "Amaryllis Solandraeflora",
                "name": "Amaryllis Solandraeflora / 12″×16″",
                "size": "12″×16″",
                "color": None,
                "retail_price": "37.00",
                "sku": "67E1024BC801F_12″x16″",
                "synced": True,
                "product_type": "Canvas",
            },
            {
                "id": "4765920980",
                "sync_product_id": "378560852",
                "sync_product_name": "Amaryllis Solandraeflora",
                "name": "Amaryllis Solandraeflora / 16″×20″",
                "size": "16″×20″",
                "color": None,
                "retail_price": "41.50",
                "sku": "67E1024BC801F_16″x20″",
                "synced": True,
                "product_type": "Canvas",
            },
        ]
    )
    assert len(products) == 1
    assert len(products[0].variants) == 2
    for variant in products[0].variants:
        assert "Option" not in variant.attributes
        assert "Size" in variant.attributes
    assert products[0].variants[0].title == "Amaryllis Solandraeflora / 12″×16″"
    assert products[0].variants[0].attributes == {"Size": "12″×16″"}


@pytest.mark.asyncio
async def test_expand_sync_product_always_fetches_product_detail():
    from unittest.mock import MagicMock

    from app.addons.suppliers.printful.addon import PrintfulAddon

    list_row = {
        "id": 378560852,
        "name": "Amaryllis Solandraeflora",
        "thumbnail_url": "https://files.cdn.printful.com/files/e61/e619e186c6fc51a81e9f98eeca923b05_preview.png",
        "sync_variants": [
            {
                "id": 4765920979,
                "synced": True,
                "sku": "67E1024BC801F_12″x16″",
                "retail_price": "37.00",
            }
        ],
    }
    product_detail = {
        "sync_product": {"id": 378560852, "name": "Amaryllis Solandraeflora"},
        "sync_variants": [_amaryllis_product_detail_stub()],
    }
    variant_detail = _amaryllis_variant_detail_only_default()

    client = MagicMock()
    client.get_sync_product = AsyncMock(return_value={"result": product_detail})
    client.get_sync_variant = AsyncMock(return_value={"result": variant_detail})

    addon = PrintfulAddon()
    rows = await addon._expand_sync_product(client, list_row)

    client.get_sync_product.assert_awaited_once_with("378560852")
    client.get_sync_variant.assert_awaited_once_with("4765920979")
    assert len(rows) == 1
    assert rows[0]["image_urls"] == [
        AMARYLLIS_PREVIEW_FILE["preview_url"],
        AMARYLLIS_PRODUCT_IMAGE,
    ]
