"""Cart and CartItem schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.base import cents_to_decimal


# ── Item operations ─────────────────────────────────────────────────


class CartItemAdd(BaseModel):
    product_id: int = Field(gt=0)
    variant_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=999, default=1)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0, le=999)


# ── Read ────────────────────────────────────────────────────────────


class CartItemRead(BaseModel):
    id: int
    cart_id: int
    product_id: int
    variant_id: int
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
    """CartItem enriched with computed price from the variant."""

    product_name: str = ""
    variant_title: str = ""
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


class CartQuoteRequest(BaseModel):
    """Optional shipping address for checkout tax/shipping preview."""

    shipping_address: dict | None = None
    shipping_selections: dict[str, str] | None = None


class ShippingRateOption(BaseModel):
    """One selectable shipping method for a supplier fulfillment group."""

    id: str
    name: str
    cents: int
    min_delivery_days: int | None = None
    max_delivery_days: int | None = None


class ShippingBreakdownItem(BaseModel):
    """One shipping bucket (supplier quote or site-settings fallback)."""

    source: str
    fulfillment_key: str
    cents: int
    label: str = ""
    cart_item_ids: list[int] = Field(default_factory=list)
    addon_id: str | None = None
    subtotal_cents: int | None = None
    options: list[ShippingRateOption] = Field(default_factory=list)
    selected_id: str | None = None


class CartQuoteResponse(BaseModel):
    """Estimated tax and shipping for the current cart."""

    subtotal_cents: int
    tax_cents: int
    shipping_cents: int
    total_cents: int = Field(
        default=0,
        description=(
            "Chargeable total. Under tax-inclusive pricing tax is already inside "
            "subtotal_cents — clients must not add tax_cents again."
        ),
    )
    tax_inclusive: bool = Field(
        default=False,
        description="True when prices already include tax (tax_cents is informational).",
    )
    tax_source: str
    currency: str = Field(default="USD", description="Shop currency (ISO 4217).")
    preferred_currency: str | None = Field(
        default=None,
        description="Soft currency hint from address/IP; charge currency stays shop currency until FX.",
    )
    shipping_breakdown: list[ShippingBreakdownItem] = Field(default_factory=list)


class CartItemShippingEstimateResponse(BaseModel):
    """Standalone per-line shipping estimate (not used for checkout totals)."""

    cart_item_id: int
    shipping_cents: int
    currency: str = Field(default="USD", description="Shop currency (ISO 4217).")
    label: str = ""
    source: str = ""
