"""Built-in Site Settings tax and shipping rules."""

from __future__ import annotations

from typing import Any

from app.services.countries import normalize_country_code
from models.site_settings import SiteSettings


def normalize_country(address: dict[str, Any] | None) -> str | None:
    if not address:
        return None
    return normalize_country_code(
        address.get("country") or address.get("country_code")
    )


def match_tax_rate_bps(
    zones: list[dict[str, Any]],
    country: str | None,
    default_bps: int,
) -> int:
    if not country or not zones:
        return default_bps
    for zone in zones:
        countries = [str(c).upper() for c in (zone.get("countries") or [])]
        if country in countries:
            return max(0, int(zone.get("rate_bps", default_bps)))
    return default_bps


def compute_site_tax_cents(
    subtotal_cents: int,
    site: SiteSettings,
    shipping_address: dict[str, Any] | None,
) -> tuple[int, str]:
    """Apply built-in Site Settings tax rules to merchandise subtotal."""
    if not site.tax_enabled or subtotal_cents <= 0:
        return 0, "disabled"

    country = normalize_country(shipping_address)
    rate_bps = match_tax_rate_bps(
        site.tax_zones_json or [],
        country,
        site.tax_rate_bps,
    )
    if rate_bps <= 0:
        return 0, "site_settings"

    if site.tax_inclusive:
        tax_cents = subtotal_cents - int(subtotal_cents * 10000 / (10000 + rate_bps))
    else:
        tax_cents = int(subtotal_cents * rate_bps / 10000)
    return max(0, tax_cents), "site_settings"


def compute_site_shipping_cents(
    subtotal_cents: int,
    site: SiteSettings,
    shipping_address: dict[str, Any] | None,
) -> int:
    """Apply built-in Site Settings shipping rules to a merchandise subtotal."""
    mode = (site.shipping_mode or "flat").strip()
    if mode == "free":
        return 0
    if mode == "free_over_threshold":
        threshold = site.shipping_free_threshold_cents
        if threshold is not None and subtotal_cents >= threshold:
            return 0

    country = normalize_country(shipping_address)
    zones = site.shipping_zones_json or []
    if country and zones:
        for zone in zones:
            countries = [str(c).upper() for c in (zone.get("countries") or [])]
            if country in countries:
                return max(0, int(zone.get("flat_cents", site.shipping_flat_cents)))

    return max(0, int(site.shipping_flat_cents))
