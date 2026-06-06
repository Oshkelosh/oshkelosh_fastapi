"""Order and OrderItem schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.base import PaginatedResponse


# ── Helpers ─────────────────────────────────────────────────────────

VALID_ORDER_STATUSES = {
    "pending",
    "paid",
    "shipped",
    "delivered",
    "cancelled",
}


def cents_to_decimal(value: Optional[int]) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(value) / Decimal(100)


# ── Create ──────────────────────────────────────────────────────────


class OrderCreate(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=255)
    user_id: Optional[int] = Field(default=None)
    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None
    notes: Optional[str] = Field(default=None, max_length=10000)
    currency: str = Field(default="usd", max_length=10)


# ── Update ──────────────────────────────────────────────────────────


class OrderUpdateStatus(BaseModel):
    status: str = Field(pattern="^(pending|paid|shipped|delivered|cancelled)$")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_ORDER_STATUSES:
            raise ValueError(f"status must be one of {VALID_ORDER_STATUSES}")
        return v


# ── Read ────────────────────────────────────────────────────────────


class OrderItemRead(BaseModel):
    id: int
    order_id: int
    product_id: Optional[int]
    product_name: str
    product_sku: str
    quantity: int
    unit_price_cents: int
    unit_price: Decimal = Field(default=Decimal("0.00"))
    total_price_cents: int
    total_price: Decimal = Field(default=Decimal("0.00"))
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def inject_decimal_prices(cls, data: Any) -> Any:
        if hasattr(data, "unit_price_cents"):
            payload = data.model_dump()
            payload.setdefault("unit_price", cents_to_decimal(payload["unit_price_cents"]))
            payload.setdefault(
                "total_price", cents_to_decimal(payload["total_price_cents"])
            )
            return payload
        if isinstance(data, dict):
            payload = dict(data)
            if "unit_price" not in payload and "unit_price_cents" in payload:
                payload["unit_price"] = cents_to_decimal(payload["unit_price_cents"])
            if "total_price" not in payload and "total_price_cents" in payload:
                payload["total_price"] = cents_to_decimal(payload["total_price_cents"])
            return payload
        return data

    @field_validator("unit_price", mode="before")
    @classmethod
    def compute_unit_price(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("unit_price_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)

    @field_validator("total_price", mode="before")
    @classmethod
    def compute_total_price(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("total_price_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)


class OrderRead(BaseModel):
    id: int
    session_id: Optional[str]
    user_id: Optional[int]
    status: str
    total_cents: int
    total: Decimal = Field(default=Decimal("0.00"))
    tax_cents: int
    tax: Decimal = Field(default=Decimal("0.00"))
    shipping_cents: int
    shipping: Decimal = Field(default=Decimal("0.00"))
    currency: str
    shipping_address: Optional[Dict[str, Any]]
    billing_address: Optional[Dict[str, Any]]
    notes: Optional[str]
    items: List[OrderItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def inject_decimal_amounts(cls, data: Any) -> Any:
        if hasattr(data, "total_cents"):
            payload = data.model_dump()
            for field, cents_key in (
                ("total", "total_cents"),
                ("tax", "tax_cents"),
                ("shipping", "shipping_cents"),
            ):
                if field not in payload and cents_key in payload:
                    payload[field] = cents_to_decimal(payload[cents_key])
            return payload
        if isinstance(data, dict):
            payload = dict(data)
            for field, cents_key in (
                ("total", "total_cents"),
                ("tax", "tax_cents"),
                ("shipping", "shipping_cents"),
            ):
                if field not in payload and cents_key in payload:
                    payload[field] = cents_to_decimal(payload[cents_key])
            return payload
        return data

    @field_validator("total", mode="before")
    @classmethod
    def compute_total(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("total_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)

    @field_validator("tax", mode="before")
    @classmethod
    def compute_tax(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("tax_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)

    @field_validator("shipping", mode="before")
    @classmethod
    def compute_shipping(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("shipping_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)


class OrderList(PaginatedResponse["OrderRead"]):
    """Paginated order list (admin use)."""
