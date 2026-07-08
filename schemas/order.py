"""Order and OrderItem schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.base import PaginatedResponse, cents_to_decimal, inject_cents_decimals


# ── Helpers ─────────────────────────────────────────────────────────

VALID_ORDER_STATUSES = {
    "pending",
    "paid",
    "shipped",
    "delivered",
    "cancelled",
}


# ── Create ──────────────────────────────────────────────────────────


class OrderCreateFromCart(BaseModel):
    """Storefront order creation from the authenticated user's cart."""

    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None
    notes: Optional[str] = Field(default=None, max_length=10000)
    currency: str = Field(default="usd", max_length=10)


class OrderCheckoutUpdate(BaseModel):
    """Optional address updates before payment."""

    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None


# ── Update ──────────────────────────────────────────────────────────


class OrderUpdateStatus(BaseModel):
    status: str = Field(pattern="^(pending|paid|shipped|delivered|cancelled)$")
    tracking_number: Optional[str] = Field(default=None, max_length=128)
    tracking_url: Optional[str] = Field(default=None, max_length=2048)
    carrier: Optional[str] = Field(default=None, max_length=128)

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
        pairs = [("unit_price", "unit_price_cents"), ("total_price", "total_price_cents")]
        if hasattr(data, "unit_price_cents"):
            payload = data.model_dump()
            inject_cents_decimals(payload, pairs)
            return payload
        if isinstance(data, dict):
            return inject_cents_decimals(dict(data), pairs)
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
    total_cents: int = Field(
        description="Grand total in cents (merchandise + tax + shipping)."
    )
    total: Decimal = Field(
        default=Decimal("0.00"),
        description="Grand total as decimal (merchandise + tax + shipping).",
    )
    subtotal_cents: int = Field(
        default=0,
        description="Merchandise subtotal in cents (sum of line items).",
    )
    subtotal: Decimal = Field(
        default=Decimal("0.00"),
        description="Merchandise subtotal as decimal.",
    )
    tax_cents: int
    tax: Decimal = Field(default=Decimal("0.00"))
    shipping_cents: int
    shipping: Decimal = Field(default=Decimal("0.00"))
    currency: str
    shipping_address: Optional[Dict[str, Any]]
    billing_address: Optional[Dict[str, Any]]
    notes: Optional[str]
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    carrier: Optional[str] = None
    payment_processor_id: Optional[str] = None
    payment_id: Optional[str] = None
    payment_charge_id: Optional[str] = None
    items: List[OrderItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def inject_decimal_amounts(cls, data: Any) -> Any:
        pairs = [
            ("total", "total_cents"),
            ("subtotal", "subtotal_cents"),
            ("tax", "tax_cents"),
            ("shipping", "shipping_cents"),
        ]
        if hasattr(data, "total_cents"):
            return inject_cents_decimals(data.model_dump(), pairs)
        if isinstance(data, dict):
            return inject_cents_decimals(dict(data), pairs)
        return data

    @field_validator("subtotal", mode="before")
    @classmethod
    def compute_subtotal(cls, v: Any, info) -> Decimal:
        if isinstance(v, Decimal):
            return v
        cents = info.data.get("subtotal_cents", 0) if isinstance(info.data, dict) else 0
        return cents_to_decimal(cents)

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
