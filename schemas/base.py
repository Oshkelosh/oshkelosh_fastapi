"""Shared / base schemas."""

from decimal import Decimal
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict


# ── Money helpers ───────────────────────────────────────────────────


def cents_to_decimal(value: int | None) -> Decimal | None:
    """Convert a cents integer to a decimal (e.g. 1999 → 19.99)."""
    if value is None:
        return None
    return Decimal(value) / Decimal(100)


def inject_cents_decimals(payload: dict, pairs: list[tuple[str, str]]) -> dict:
    """Map decimal field names to ``*_cents`` keys when decimals are absent."""
    for field, cents_key in pairs:
        if field not in payload and cents_key in payload:
            payload[field] = cents_to_decimal(payload[cents_key])
    return payload


# ── Generic pagination ──────────────────────────────────────────────

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope."""

    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


# ── Simple message ──────────────────────────────────────────────────


class MessageResponse(BaseModel):
    """A minimal JSON response carrying only a message."""

    message: str
