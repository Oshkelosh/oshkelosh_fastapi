"""Cart and CartItem schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.base import PaginatedResponse


# ── Helpers ─────────────────────────────────────────────────────────

def cents_to_decimal(value: Optional[int]) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(value) / Decimal(100)


# ── Create ──────────────────────────────────────────────────────────


class CartCreate(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=255)
    user_id: Optional[int] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 255:
            raise ValueError("session_id must be at most 255 characters")
        return v


# ── Item operations ─────────────────────────────────────────────────


class CartItemAdd(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, default=1)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


# ── Read ────────────────────────────────────────────────────────────


class CartItemRead(BaseModel):
    id: int
    cart_id: int
    product_id: int
    quantity: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CartRead(BaseModel):
    id: int
    session_id: Optional[str]
    user_id: Optional[int]
    items: List[CartItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CartItemWithPrice(CartItemRead):
    """CartItem enriched with computed price from the product."""

    unit_price_cents: int
    unit_price: Decimal = Field(default=Decimal("0.00"))
    line_total_cents: int = Field(default=0)
    line_total: Decimal = Field(default=Decimal("0.00"))

    @field_validator("unit_price", mode="before")
    @classmethod
    def compute_unit_price(cls, v: Any, info) -> Decimal:  # type: ignore[name-defined]
        if isinstance(v, Decimal):
            return v
        unit_cents = info.data.get("unit_price_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(unit_cents)

    @field_validator("line_total", mode="before")
    @classmethod
    def compute_line_total(cls, v: Any, info) -> Decimal:  # type: ignore[name-defined]
        if isinstance(v, Decimal):
            return v
        total_cents = info.data.get("line_total_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(total_cents)


class CartReadWithItems(BaseModel):
    id: int
    session_id: Optional[str]
    user_id: Optional[int]
    items: List[CartItemWithPrice] = Field(default_factory=list)
    subtotal_cents: int = Field(default=0)
    subtotal: Decimal = Field(default=Decimal("0.00"))
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CartList(PaginatedResponse["CartRead"]):
    """Paginated cart list (admin use)."""
