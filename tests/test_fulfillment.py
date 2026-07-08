"""Tests for multi-supplier fulfillment."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.fulfillment import fulfill_order_with_suppliers
from app.services.suppliers import (
    build_supplier_tag,
    merge_product_tags_with_supplier,
    parse_supplier_tag,
    supplier_fulfillment_key,
    validate_supplier_form,
)
from models.manual_supplier import ManualSupplier
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from models.product_variant import ProductVariant


class TestSupplierTagHelpers:
    def test_parse_printful_tag(self):
        tag = {"supplier_addon_id": "printful", "supplier_product_id": "123"}
        assignment = parse_supplier_tag(tag)
        assert assignment is not None
        assert assignment.addon_id == "printful"
        assert supplier_fulfillment_key(assignment) == "printful"

    def test_parse_manual_tag(self):
        tag = {
            "supplier_addon_id": "manual",
            "manual_supplier_slug": "local_workshop",
            "supplier_product_id": "SKU-1",
        }
        assignment = parse_supplier_tag(tag)
        assert assignment is not None
        assert assignment.manual_slug == "local_workshop"
        assert supplier_fulfillment_key(assignment) == "manual:local_workshop"

    def test_build_and_merge_tags(self):
        merged = merge_product_tags_with_supplier(
            [{"label": "summer"}],
            "manual:local_workshop",
            "SKU-9",
        )
        assert len(merged) == 2
        assert build_supplier_tag("printful", "999") == {
            "supplier_addon_id": "printful",
            "supplier_product_id": "999",
        }

    def test_parse_printify_tag(self):
        tag = {
            "supplier_addon_id": "printify",
            "supplier_product_id": "5bfd0b66a342bcc9b5563216",
            "supplier_variant_id": "17887",
        }
        assignment = parse_supplier_tag(tag)
        assert assignment is not None
        assert assignment.addon_id == "printify"
        assert assignment.variant_id == "17887"
        assert supplier_fulfillment_key(assignment) == "printify"

    def test_build_printify_tag(self):
        tag = build_supplier_tag(
            "printify",
            "5bfd0b66a342bcc9b5563216",
            "17887",
        )
        assert tag == {
            "supplier_addon_id": "printify",
            "supplier_product_id": "5bfd0b66a342bcc9b5563216",
            "supplier_variant_id": "17887",
        }

    def test_parse_manual_tag_with_supplier_ref_alias(self):
        tag = {
            "supplier_addon_id": "manual",
            "supplier_ref": "local_workshop",
            "supplier_product_id": "SKU-1",
        }
        assignment = parse_supplier_tag(tag)
        assert assignment is not None
        assert assignment.manual_slug == "local_workshop"
        assert assignment.fulfillment_key == "manual:local_workshop"

    def test_validate_supplier_form_printify_requires_variant(self):
        assert validate_supplier_form("printify", "prod-1", "") is not None
        assert validate_supplier_form("printify", "", "17887") is not None
        assert validate_supplier_form("printify", "prod-1", "17887") is None

    def test_validate_supplier_form_printful_requires_product_id(self):
        assert validate_supplier_form("printful", "", "") is not None
        assert validate_supplier_form("printful", "123", "") is None

    def test_validate_supplier_form_manual_slug_optional_product_id(self):
        assert validate_supplier_form("manual:", "", "") is not None
        assert validate_supplier_form("manual:local_workshop", "", "") is None
        assert validate_supplier_form("manual:local_workshop", "SKU-1", "") is None

    def test_validate_supplier_form_empty_supplier_ok(self):
        assert validate_supplier_form("", "", "") is None


class TestGenericSupplierAddonHooks:
    """New suppliers should work via SupplierAddon defaults without core edits."""

    def test_default_addon_parses_builds_and_validates(self):
        from app.addons.suppliers.base import SupplierAddon

        class AcmeAddon(SupplierAddon):
            addon_id = "acme"
            addon_name = "Acme POD"
            addon_description = "Test supplier"
            version = "1.0.0"

            @classmethod
            def config_schema(cls):
                from pydantic import BaseModel

                return BaseModel

            async def initialize(self, config: dict) -> None:
                pass

            async def shutdown(self) -> None:
                pass

            async def list_products(self, **kwargs):
                return []

            async def get_product(self, product_id: str):
                return {}

            async def create_order(self, items, shipping_address, **kwargs):
                return {"success": True}

            async def get_order_status(self, order_id: str):
                return {"status": "ok"}

            async def sync_inventory(self) -> None:
                pass

        from app.addons.registry import addon_registry

        addon = AcmeAddon()
        addon_registry._registry["acme"] = addon
        try:
            tag = {"supplier_addon_id": "acme", "supplier_product_id": "SKU-42"}
            assignment = parse_supplier_tag(tag)
            assert assignment is not None
            assert assignment.addon_id == "acme"
            assert supplier_fulfillment_key(assignment) == "acme"

            built = build_supplier_tag("acme", "SKU-42")
            assert built == {"supplier_addon_id": "acme", "supplier_product_id": "SKU-42"}

            assert validate_supplier_form("acme", "SKU-42", "") is None
            assert validate_supplier_form("acme", "", "") is not None
        finally:
            addon_registry._registry.pop("acme", None)


@pytest.mark.asyncio
async def test_mixed_order_fans_out_to_multiple_suppliers(db_session):
    """Paid order with Printful and manual items triggers two create_order calls."""
    manual = ManualSupplier(slug="local_workshop", name="Local Workshop", is_active=True)
    db_session.add(manual)

    printful_product = Product(
        name="Printful Tee",
        price_cents=2000,
        tags=[],
    )
    manual_product = Product(
        name="Handmade Mug",
        price_cents=1500,
        tags=[],
    )
    db_session.add(printful_product)
    db_session.add(manual_product)
    await db_session.flush()
    printful_variant = ProductVariant(
        product_id=printful_product.id,
        title="Default",
        position=0,
        price_cents=2000,
        inventory_quantity=10,
        sku="PF-111",
        status="active",
        supplier_addon_id="printful",
        supplier_product_id="111",
    )
    manual_variant = ProductVariant(
        product_id=manual_product.id,
        title="Default",
        position=0,
        price_cents=1500,
        inventory_quantity=10,
        sku="MUG-1",
        status="active",
        supplier_addon_id="manual",
        supplier_product_id="MUG-1",
        supplier_variant_id="local_workshop",
    )
    db_session.add(printful_variant)
    db_session.add(manual_variant)
    await db_session.flush()

    order = Order(
        user_id=1,
        status="paid",
        total_cents=3500,
        shipping_address={
            "first_name": "Jane",
            "last_name": "Doe",
            "line1": "1 Main St",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
            "country": "US",
            "email": "jane@example.com",
        },
    )
    db_session.add(order)
    await db_session.flush()

    items = [
        OrderItem(
            order_id=order.id,
            product_id=printful_product.id,
            variant_id=printful_variant.id,
            product_name=printful_product.name,
            product_sku="PF-111",
            quantity=2,
            unit_price_cents=2000,
            total_price_cents=4000,
        ),
        OrderItem(
            order_id=order.id,
            product_id=manual_product.id,
            variant_id=manual_variant.id,
            product_name=manual_product.name,
            product_sku="MUG-1",
            quantity=1,
            unit_price_cents=1500,
            total_price_cents=1500,
        ),
    ]
    for item in items:
        db_session.add(item)
    await db_session.flush()

    printful_mock = AsyncMock(
        return_value={"success": True, "order_id": "pf-1", "status": "created"}
    )
    manual_mock = AsyncMock(
        return_value={
            "success": True,
            "type": "manual",
            "supplier_slug": "local_workshop",
            "status": "pending_manual_fulfillment",
        }
    )

    class FakePrintfulAddon:
        addon_id = "printful"
        is_enabled = True
        create_order = printful_mock

    class FakeManualAddon:
        addon_id = "manual"
        is_enabled = True
        create_order = manual_mock

    def fake_get_supplier(addon_id=None):
        if addon_id == "printful":
            return FakePrintfulAddon()
        if addon_id == "manual":
            return FakeManualAddon()
        return None

    with patch("app.services.fulfillment.get_supplier_addon", side_effect=fake_get_supplier):
        await fulfill_order_with_suppliers(db_session, order, items)

    assert printful_mock.await_count == 1
    assert manual_mock.await_count == 1

    pf_call = printful_mock.await_args
    assert pf_call.kwargs["external_id"] == str(order.id)
    assert pf_call.args[0] == [
        {
            "supplier_product_id": "111",
            "supplier_variant_id": None,
            "quantity": 2,
            "product_name": "Printful Tee — Default",
        }
    ]

    manual_call = manual_mock.await_args
    assert manual_call.kwargs["supplier_ref"] == "local_workshop"
    assert manual_call.args[0][0]["quantity"] == 1

    assert "printful" in order.notes
    assert "manual:local_workshop" in order.notes


@pytest.mark.asyncio
async def test_disabled_supplier_skipped_other_still_fulfills(db_session):
    product = Product(
        name="Manual only",
        price_cents=1000,
        tags=[
            {
                "supplier_addon_id": "manual",
                "manual_supplier_slug": "local_workshop",
            }
        ],
    )
    db_session.add(product)
    await db_session.flush()

    order = Order(user_id=1, status="paid", total_cents=1000, shipping_address={})
    db_session.add(order)
    await db_session.flush()
    items = [
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            product_sku="MAN-1",
            quantity=1,
            unit_price_cents=1000,
            total_price_cents=1000,
        )
    ]
    db_session.add(items[0])
    await db_session.flush()

    with patch("app.services.fulfillment.get_supplier_addon", return_value=None):
        await fulfill_order_with_suppliers(db_session, order, items)

    assert not order.notes
