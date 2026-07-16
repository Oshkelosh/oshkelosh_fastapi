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
