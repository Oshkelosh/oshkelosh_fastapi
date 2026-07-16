"""Quote result types shared with tax/shipping providers and tool addons."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
