"""Shared helpers for supplier checkout shipping quotes.

Each supplier addon parses its provider's own rate response shape; the only
truly shared concern is converting a money amount to integer cents, where an
unparseable or negative amount must be distinguishable from a real zero. That
is why this returns ``None`` on failure, unlike ``catalog_utils`` helpers which
return ``0`` for missing catalog prices.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def to_cents(value: Any) -> int | None:
    """Convert a currency-unit amount (e.g. ``"13.60"``) to cents.

    Returns ``None`` when the value is missing, unparseable, or negative so the
    caller can fall back to Site Settings instead of quoting a bogus amount.
    """
    if value is None:
        return None
    try:
        cents = int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return cents if cents >= 0 else None


def pick_shipping_option(
    options: list[dict[str, Any]],
    *,
    selected_id: str | None = None,
    preferred_ids: tuple[str, ...] = ("standard",),
) -> dict[str, Any] | None:
    """Resolve a selected method, else first matching preferred id, else cheapest.

    Option rows must include ``id`` and ``cents``. Matching is case-insensitive.
    ``preferred_ids`` is ordered: the first preference that matches any option wins
    (cheapest among that preference's matches).
    """
    if not options:
        return None
    if selected_id:
        needle = str(selected_id).strip().lower()
        for option in options:
            if str(option.get("id") or "").strip().lower() == needle:
                return option
    for pref in preferred_ids:
        pref_l = str(pref).lower()
        matches = [
            option
            for option in options
            if str(option.get("id") or "").strip().lower() == pref_l
            or pref_l in str(option.get("name") or "").strip().lower()
        ]
        if matches:
            return min(matches, key=lambda row: int(row["cents"]))
    return min(options, key=lambda row: int(row["cents"]))
