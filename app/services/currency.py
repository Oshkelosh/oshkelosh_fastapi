"""Shop currency helpers and country→currency hints.

Display and charge amounts stay in shop currency until FX or dual price lists exist.
Country/IP hints only feed a soft preference for a future multi-currency path.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request

# ISO 4217: three letters. Shop/order codes are normalized to uppercase here;
# order persistence lowercases for payment processors that expect ``usd``.
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")

# Currencies we accept for shop_currency / formatting. Not a full ISO list —
# unknown 3-letter codes (e.g. ``FOO``) fall back to USD so Intl/payments
# do not throw.
_KNOWN_CURRENCIES = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "CAD",
        "AUD",
        "NZD",
        "JPY",
        "CNY",
        "HKD",
        "SGD",
        "INR",
        "CHF",
        "NOK",
        "SEK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "TRY",
        "MXN",
        "BRL",
        "ARS",
        "CLP",
        "COP",
        "PEN",
        "ZAR",
        "KRW",
        "TWD",
        "THB",
        "MYR",
        "PHP",
        "IDR",
        "VND",
        "ILS",
        "AED",
        "SAR",
        "EGP",
        "NGN",
        "KES",
        "RUB",
        "UAH",
        "ISK",
    }
)

PREFERRED_CURRENCY_COOKIE = "osh_preferred_currency"

# Common tender currency by ISO-3166-1 alpha-2. Incomplete by design — unknown
# countries fall back to shop currency.
_COUNTRY_CURRENCY: dict[str, str] = {
    "US": "USD",
    "CA": "CAD",
    "GB": "GBP",
    "AU": "AUD",
    "NZ": "NZD",
    "JP": "JPY",
    "CN": "CNY",
    "HK": "HKD",
    "SG": "SGD",
    "IN": "INR",
    "CH": "CHF",
    "NO": "NOK",
    "SE": "SEK",
    "DK": "DKK",
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "RO": "RON",
    "BG": "BGN",
    "TR": "TRY",
    "MX": "MXN",
    "BR": "BRL",
    "AR": "ARS",
    "CL": "CLP",
    "CO": "COP",
    "PE": "PEN",
    "ZA": "ZAR",
    "KR": "KRW",
    "TW": "TWD",
    "TH": "THB",
    "MY": "MYR",
    "PH": "PHP",
    "ID": "IDR",
    "VN": "VND",
    "IL": "ILS",
    "AE": "AED",
    "SA": "SAR",
    "EG": "EGP",
    "NG": "NGN",
    "KE": "KES",
    "RU": "RUB",
    "UA": "UAH",
    "IS": "ISK",
    # Eurozone (+ common EUR users)
    "AT": "EUR",
    "BE": "EUR",
    "CY": "EUR",
    "DE": "EUR",
    "EE": "EUR",
    "ES": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "GR": "EUR",
    "HR": "EUR",
    "IE": "EUR",
    "IT": "EUR",
    "LT": "EUR",
    "LU": "EUR",
    "LV": "EUR",
    "MT": "EUR",
    "NL": "EUR",
    "PT": "EUR",
    "SI": "EUR",
    "SK": "EUR",
    "AD": "EUR",
    "MC": "EUR",
    "SM": "EUR",
    "VA": "EUR",
    "XK": "EUR",
    "ME": "EUR",
}


def normalize_currency(value: str | None, *, default: str = "USD") -> str:
    """Return a known 3-letter uppercase currency code, or ``default`` if invalid."""
    raw = (value or "").strip().upper()
    if _CURRENCY_RE.fullmatch(raw) and raw in _KNOWN_CURRENCIES:
        return raw
    fallback = (default or "USD").strip().upper()
    if _CURRENCY_RE.fullmatch(fallback) and fallback in _KNOWN_CURRENCIES:
        return fallback
    return "USD"


def currency_for_country(country_code: str | None) -> str | None:
    """Map an ISO country code to a typical tender currency, if known."""
    from app.services.countries import normalize_country_code

    code = normalize_country_code(country_code)
    if not code:
        return None
    return _COUNTRY_CURRENCY.get(code)


def client_country_from_request(request: Request | None) -> str | None:
    """Soft geo hint from CDN/proxy headers (no MaxMind dependency)."""
    if request is None:
        return None
    from app.services.countries import normalize_country_code

    for header in ("cf-ipcountry", "cloudfront-viewer-country", "x-vercel-ip-country"):
        raw = request.headers.get(header)
        if not raw:
            continue
        # Cloudflare uses XX for unknown / T1 for tor
        if raw.strip().upper() in {"XX", "T1", "A1", "A2"}:
            continue
        code = normalize_country_code(raw)
        if code:
            return code
    return None


def cookie_currency_preference(request: Request | None) -> str | None:
    """Read soft preferred-currency cookie from the request, if valid."""
    if request is None:
        return None
    raw = request.cookies.get(PREFERRED_CURRENCY_COOKIE)
    if not raw:
        return None
    candidate = raw.strip().upper()
    return candidate if candidate in _KNOWN_CURRENCIES else None


def preferred_currency_hint(
    *,
    shop_currency: str,
    address_country: str | None = None,
    ip_country: str | None = None,
    cookie_preference: str | None = None,
) -> str:
    """Resolve a soft preferred currency without changing charge currency.

    Priority: address country → cookie → IP country → shop currency.
    """
    shop = normalize_currency(shop_currency)
    mapped = currency_for_country(address_country)
    if mapped:
        return mapped
    if cookie_preference:
        return normalize_currency(cookie_preference, default=shop)
    mapped = currency_for_country(ip_country)
    if mapped:
        return mapped
    return shop


def order_currency_code(shop_currency: str) -> str:
    """Lowercase ISO code for ``Order.currency`` / payment addons."""
    return normalize_currency(shop_currency).lower()


def shop_currency_from_settings(site: Any) -> str:
    """Read ``shop_currency`` from a SiteSettings-like object."""
    return normalize_currency(getattr(site, "shop_currency", None))
