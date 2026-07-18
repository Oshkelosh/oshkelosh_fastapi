"""Shared canonical reader for Oshkelosh shipping addresses.

Order shipping addresses arrive with alias keys (``line1``/``address1``,
``zip``/``postal_code``, ``state``/``state_code``, ``country``/``country_code``)
and optionally a composed or split name. Every supplier addon needs the same
resolution before mapping to its provider's field names, so it lives here once.
"""

from __future__ import annotations

from typing import Any


def canonical_address(shipping_address: dict[str, Any] | None) -> dict[str, str]:
    """Resolve alias keys into one canonical dict of plain strings.

    Keys: name, first_name, last_name, line1, line2, city, state, zip,
    country_code (ISO-2 when recognizable, else the raw value), email, phone.
    Missing values are "".
    """
    from app.services.countries import normalize_country_code

    a = shipping_address or {}
    first = str(a.get("first_name") or "")
    last = str(a.get("last_name") or "")
    name = str(
        a.get("full_name")
        or a.get("name")
        or f"{first} {last}".strip()
        or "Customer"
    )
    country_raw = str(a.get("country") or a.get("country_code") or "").strip()
    # Fall back to the raw value when unrecognized so the provider API sees
    # (and rejects) what was actually entered instead of an empty field.
    country = normalize_country_code(country_raw) or country_raw
    return {
        "name": name,
        "first_name": first or "Customer",
        "last_name": last,
        "line1": str(a.get("line1") or a.get("address1") or ""),
        "line2": str(a.get("line2") or a.get("address2") or ""),
        "city": str(a.get("city") or ""),
        "state": str(a.get("state") or a.get("state_code") or ""),
        "zip": str(a.get("zip") or a.get("postal_code") or ""),
        "country_code": country,
        "email": str(a.get("email") or ""),
        "phone": str(a.get("phone") or ""),
    }
