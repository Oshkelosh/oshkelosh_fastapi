"""Narrow interfaces for tax and shipping quote providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from models.product import Product
from models.site_settings import SiteSettings


@dataclass
class TaxQuote:
    """Tax amount from site settings or a third-party tax tool."""

    tax_cents: int
    source: str = "site_settings"


@dataclass
class ShippingQuote:
    """Resolved shipping amount for a cart."""

    shipping_cents: int
    breakdown: list[dict[str, Any]] = field(default_factory=list)


class TaxQuoter(Protocol):
    async def quote(
        self,
        line_items: list[dict[str, Any]],
        shipping_address: dict[str, Any] | None,
        subtotal_cents: int,
    ) -> TaxQuote | None:
        """Return tax for the cart, or None to defer to the next quoter."""


class ShippingQuoter(Protocol):
    async def quote(
        self,
        cart_items: list[Any],
        products: dict[int, Product],
        shipping_address: dict[str, Any] | None,
    ) -> ShippingQuote:
        """Return shipping for the cart."""
