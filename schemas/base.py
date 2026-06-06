"""Shared / base schemas."""

from decimal import Decimal
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict


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
