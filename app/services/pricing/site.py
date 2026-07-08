"""Site-settings tax quoter implementation."""

from __future__ import annotations

from typing import Any

from app.services.pricing.protocols import TaxQuote
from app.services.pricing.tax_rules import compute_site_tax_cents
from models.site_settings import SiteSettings


class SiteTaxQuoter:
    """Apply built-in Site Settings tax rules."""

    def __init__(self, site: SiteSettings) -> None:
        self._site = site

    async def quote(
        self,
        line_items: list[dict[str, Any]],
        shipping_address: dict[str, Any] | None,
        subtotal_cents: int,
    ) -> TaxQuote | None:
        del line_items
        tax_cents, source = compute_site_tax_cents(
            subtotal_cents,
            self._site,
            shipping_address,
        )
        if source == "disabled":
            return None
        return TaxQuote(tax_cents=tax_cents, source=source)
