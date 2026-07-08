"""Tests for checkout tax and shipping orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.base import SupplierAddon
from app.services.pricing.protocols import TaxQuote
from app.addons.tools.base import ToolAddon
from app.services.checkout_pricing import (
    OrderCharges,
    _cart_subtotal_cents,
    compute_order_total_cents,
    compute_site_shipping_cents,
    compute_site_tax_cents,
    quote_order_charges,
    try_tax_tool_quote,
)
from models.site_settings import SiteSettings


def _site(**overrides) -> SiteSettings:
    defaults = {
        "id": 1,
        "store_name": "Test",
        "tax_enabled": True,
        "tax_inclusive": False,
        "tax_rate_bps": 800,
        "tax_zones_json": [],
        "shipping_mode": "flat",
        "shipping_flat_cents": 500,
        "shipping_free_threshold_cents": None,
        "shipping_zones_json": [],
    }
    defaults.update(overrides)
    return SiteSettings(**defaults)


class _CartItem:
    def __init__(self, product_id: int, variant_id: int, quantity: int) -> None:
        self.product_id = product_id
        self.variant_id = variant_id
        self.quantity = quantity


class _Product:
    def __init__(
        self,
        product_id: int,
        price_cents: int,
        name: str = "Item",
        tags: list | None = None,
    ) -> None:
        self.id = product_id
        self.price_cents = price_cents
        self.name = name
        self.tags = tags or []


class _Variant:
    def __init__(
        self,
        variant_id: int,
        product_id: int,
        price_cents: int,
        title: str = "Default",
        supplier_addon_id: str | None = None,
        supplier_product_id: str | None = None,
        supplier_variant_id: str | None = None,
    ) -> None:
        self.id = variant_id
        self.product_id = product_id
        self.price_cents = price_cents
        self.title = title
        self.sku = f"SKU-{variant_id}"
        self.supplier_addon_id = supplier_addon_id
        self.supplier_product_id = supplier_product_id
        self.supplier_variant_id = supplier_variant_id
        self.attributes: dict[str, str] = {}


class TestSiteTaxRules:
    def test_flat_tax_rate(self):
        site = _site(tax_rate_bps=1000)
        tax, source = compute_site_tax_cents(10000, site, {"country": "US"})
        assert tax == 1000
        assert source == "site_settings"

    def test_tax_disabled(self):
        site = _site(tax_enabled=False)
        tax, source = compute_site_tax_cents(10000, site, None)
        assert tax == 0
        assert source == "disabled"

    def test_country_zone_override(self):
        site = _site(
            tax_rate_bps=500,
            tax_zones_json=[{"countries": ["DE"], "rate_bps": 1900}],
        )
        tax, _ = compute_site_tax_cents(10000, site, {"country": "de"})
        assert tax == 1900

    def test_tax_inclusive(self):
        site = _site(tax_inclusive=True, tax_rate_bps=1000)
        tax, _ = compute_site_tax_cents(11000, site, None)
        assert tax == 1000


class TestOrderTotal:
    def test_tax_exclusive_adds_tax(self):
        site = _site(tax_inclusive=False)
        charges = OrderCharges(tax_cents=800, shipping_cents=500, tax_source="site_settings")
        assert compute_order_total_cents(10000, charges, site) == 11300

    def test_tax_inclusive_does_not_double_count(self):
        site = _site(tax_inclusive=True, tax_rate_bps=1000)
        charges = OrderCharges(tax_cents=1000, shipping_cents=500, tax_source="site_settings")
        # Subtotal 11000 already includes tax; total is subtotal + shipping only.
        assert compute_order_total_cents(11000, charges, site) == 11500


class TestSiteShippingRules:
    def test_flat_shipping(self):
        site = _site(shipping_flat_cents=799)
        assert compute_site_shipping_cents(2000, site, None) == 799

    def test_free_shipping(self):
        site = _site(shipping_mode="free")
        assert compute_site_shipping_cents(2000, site, None) == 0

    def test_free_over_threshold(self):
        site = _site(
            shipping_mode="free_over_threshold",
            shipping_free_threshold_cents=5000,
            shipping_flat_cents=500,
        )
        assert compute_site_shipping_cents(4999, site, None) == 500
        assert compute_site_shipping_cents(5000, site, None) == 0

    def test_shipping_zone(self):
        site = _site(
            shipping_zones_json=[{"countries": ["CA"], "flat_cents": 1200}],
            shipping_flat_cents=500,
        )
        assert compute_site_shipping_cents(1000, site, {"country": "CA"}) == 1200
        assert compute_site_shipping_cents(1000, site, {"country": "US"}) == 500


class MockShippingSupplier(SupplierAddon):
    addon_id = "mock_ship"
    addon_name = "Mock Ship"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__()
        self.is_enabled = True
        self.quote_shipping = AsyncMock(return_value=250)

    @classmethod
    def config_schema(cls):
        from pydantic import BaseModel

        return BaseModel

    def supports_shipping_quotes(self) -> bool:
        return True

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def list_products(self, **kwargs):
        return []

    async def get_product(self, product_id: str):
        return {}

    async def create_order(self, items, shipping_address, **kwargs):
        return {}

    async def get_order_status(self, order_id: str):
        return {}

    async def sync_inventory(self) -> None:
        pass

    def parse_assignment(self, tag):
        from schemas.supplier import SupplierAssignment

        if tag.get("supplier_addon_id") != self.addon_id:
            return None
        return SupplierAssignment(
            addon_id=self.addon_id,
            supplier_product_id=str(tag.get("supplier_product_id", "")),
        )


class MockTaxTool(ToolAddon):
    addon_id = "mock_tax"
    addon_name = "Mock Tax"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__()
        self.is_enabled = True
        self.quote_tax = AsyncMock(return_value=TaxQuote(tax_cents=321))

    @classmethod
    def config_schema(cls):
        from pydantic import BaseModel

        return BaseModel

    def supports_tax_quotes(self) -> bool:
        return True

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
class TestQuoteOrderCharges:
    async def test_merchant_cart_uses_site_settings(self):
        site = _site()
        items = [_CartItem(1, 1, 2)]
        products = {1: _Product(1, 1000)}
        variants = {1: _Variant(1, 1, 1000)}
        charges = await quote_order_charges(items, products, {"country": "US"}, site, variants)
        assert charges.tax_cents == 160
        assert charges.shipping_cents == 500
        assert charges.tax_source == "site_settings"

    async def test_supplier_shipping_quote(self, monkeypatch):
        from app.addons.registry import addon_registry

        supplier = MockShippingSupplier()
        addon_registry._registry["mock_ship"] = supplier
        monkeypatch.setattr(
            "app.services.pricing.shipping.get_supplier_addon",
            lambda addon_id: supplier if addon_id == "mock_ship" else None,
        )
        try:
            site = _site(shipping_flat_cents=999)
            items = [_CartItem(1, 1, 1)]
            products = {1: _Product(1, 1000)}
            variants = {
                1: _Variant(
                    1,
                    1,
                    1000,
                    supplier_addon_id="mock_ship",
                    supplier_product_id="p1",
                )
            }
            charges = await quote_order_charges(items, products, {"country": "US"}, site, variants)
            assert charges.shipping_cents == 250
            assert charges.shipping_breakdown[0]["source"] == "supplier"
        finally:
            addon_registry._registry.pop("mock_ship", None)

    async def test_mixed_cart_supplier_and_merchant(self, monkeypatch):
        from app.addons.registry import addon_registry

        supplier = MockShippingSupplier()
        addon_registry._registry["mock_ship"] = supplier
        monkeypatch.setattr(
            "app.services.pricing.shipping.get_supplier_addon",
            lambda addon_id: supplier if addon_id == "mock_ship" else None,
        )
        try:
            site = _site(shipping_flat_cents=400)
            items = [_CartItem(1, 1, 1), _CartItem(2, 2, 1)]
            products = {1: _Product(1, 1000), 2: _Product(2, 2000)}
            variants = {
                1: _Variant(
                    1,
                    1,
                    1000,
                    supplier_addon_id="mock_ship",
                    supplier_product_id="p1",
                ),
                2: _Variant(2, 2, 2000),
            }
            charges = await quote_order_charges(items, products, None, site, variants)
            assert charges.shipping_cents == 250 + 400
        finally:
            addon_registry._registry.pop("mock_ship", None)

    async def test_tax_tool_overrides_site_settings(self, monkeypatch):
        tool = MockTaxTool()
        monkeypatch.setattr(
            "app.services.checkout_pricing.get_tax_tool",
            lambda: tool,
        )
        site = _site(tax_rate_bps=800)
        items = [_CartItem(1, 1, 1)]
        products = {1: _Product(1, 10000)}
        variants = {1: _Variant(1, 1, 10000)}
        charges = await quote_order_charges(items, products, None, site, variants)
        assert charges.tax_cents == 321
        assert charges.tax_source == "tax_tool"

    async def test_tax_tool_fallback_when_returns_none(self, monkeypatch):
        tool = MockTaxTool()
        tool.quote_tax = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.services.checkout_pricing.get_tax_tool",
            lambda: tool,
        )
        site = _site(tax_rate_bps=1000)
        items = [_CartItem(1, 1, 1)]
        products = {1: _Product(1, 10000)}
        variants = {1: _Variant(1, 1, 10000)}
        charges = await quote_order_charges(items, products, None, site, variants)
        assert charges.tax_cents == 1000
        assert charges.tax_source == "site_settings"


def test_tax_truncates_fractional_cents():
    site = _site(tax_rate_bps=825)
    tax_cents, _source = compute_site_tax_cents(100, site, None)
    assert tax_cents == 8


class TestCheckoutHelpers:
    def test_cart_subtotal_cents(self):
        items = [_CartItem(1, 1, 2), _CartItem(2, 2, 1)]
        products = {1: _Product(1, 500), 2: _Product(2, 1000)}
        variants = {1: _Variant(1, 1, 500), 2: _Variant(2, 2, 1000)}
        assert _cart_subtotal_cents(items, products, variants) == 2000

    @pytest.mark.asyncio
    async def test_try_tax_tool_quote_returns_none_on_exception(self):
        tool = MockTaxTool()
        tool.quote_tax = AsyncMock(side_effect=RuntimeError("boom"))
        result = await try_tax_tool_quote(tool, [], None, 1000)
        assert result is None

    @pytest.mark.asyncio
    async def test_try_tax_tool_quote_skips_zero_subtotal(self):
        tool = MockTaxTool()
        result = await try_tax_tool_quote(tool, [], None, 0)
        assert result is None
        tool.quote_tax.assert_not_called()
