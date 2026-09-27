"""Unit tests for shared supplier catalog_utils."""

from app.addons.suppliers.catalog_utils import (
    flat_catalog_item_to_product,
    image_alts_aligned,
    variant_title_from_attributes,
)
from schemas.supplier import POD_INVENTORY_PLACEHOLDER, SupplierCatalogItem


def test_variant_title_prefixes_base_name_when_attributes_present():
    title = variant_title_from_attributes(
        "Cool Tee",
        {"Color": "Black", "Size": "L"},
    )
    assert title == "Cool Tee / Black / L"


def test_variant_title_options_only_when_no_base():
    title = variant_title_from_attributes("", {"Size": "M"})
    assert title == "M"


def test_variant_title_fallback_without_attributes():
    assert variant_title_from_attributes("Product", {}, fallback="Product / XL") == "Product / XL"
    assert variant_title_from_attributes("Product", {}) == "Product"


def test_flat_catalog_item_fills_image_alts_from_name():
    item = SupplierCatalogItem(
        external_key="gelato:1",
        name="Poster",
        description=None,
        price_cents=1000,
        sku="P-1",
        image_url="https://cdn.example/p.jpg",
        supplier_value="gelato",
        supplier_product_id="1",
        supplier_variant_id="",
        inventory_quantity=POD_INVENTORY_PLACEHOLDER,
    )
    product = flat_catalog_item_to_product(item)
    assert product.image_urls == []
    assert product.variants[0].image_urls == ["https://cdn.example/p.jpg"]
    assert product.variants[0].image_alt_texts == ["Poster"]


def test_image_alts_aligned():
    assert image_alts_aligned(["a", "b"], "Alt") == ["Alt", "Alt"]
    assert image_alts_aligned([], "Alt") == []
    assert image_alts_aligned(["a"], "") == []
