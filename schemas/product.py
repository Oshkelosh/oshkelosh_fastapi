"""Product and ProductImage schemas.

All prices are stored as ``int`` (cents) in the database.  In the response
schemas they are exposed as ``Decimal`` for precise monetary representation
on the API consumer side.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.base import PaginatedResponse, cents_to_decimal, inject_cents_decimals


VALID_STATUSES = {"draft", "published", "archived"}


# ── Create ──────────────────────────────────────────────────────────


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    meta_title: Optional[str] = Field(default=None, max_length=255)
    meta_description: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=10000)
    price_cents: int = Field(ge=0, description="Default variant price in cents")
    compare_at_price_cents: Optional[int] = Field(default=None, ge=0)
    sku: Optional[str] = Field(default=None, max_length=100)
    inventory_quantity: int = Field(default=0, ge=0)
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")
    category_id: Optional[int] = Field(default=None)
    options: Dict[str, str] = Field(
        default_factory=dict,
        description="Creator additional info (material, care, specs)",
    )
    tags: List[Dict[str, Any]] = Field(default_factory=list)
    created_by: Optional[int] = Field(default=None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v


class ProductImageCreate(BaseModel):
    """Canonical product image — stored as a ProductImage row."""

    url: str = Field(min_length=1, max_length=2000)
    alt_text: Optional[str] = Field(default=None, max_length=500)
    sort_order: int = Field(default=0)


# ── Update ──────────────────────────────────────────────────────────


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    meta_title: Optional[str] = Field(default=None, max_length=255)
    meta_description: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=10000)
    price_cents: Optional[int] = Field(default=None, ge=0)
    compare_at_price_cents: Optional[int] = Field(default=None, ge=0)
    sku: Optional[str] = Field(default=None, max_length=100)
    inventory_quantity: Optional[int] = Field(default=None, ge=0)
    status: Optional[str] = Field(default=None, pattern="^(draft|published|archived)$")
    category_id: Optional[int] = Field(default=None)
    options: Optional[Dict[str, str]] = None
    tags: Optional[List[Dict[str, Any]]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v


# ── Read ────────────────────────────────────────────────────────────


class ProductImageRead(BaseModel):
    id: int
    url: str
    variants: Dict[str, str] = Field(default_factory=dict)
    alt_text: Optional[str]
    sort_order: int
    variant_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductVariantRead(BaseModel):
    id: int
    product_id: int
    title: str
    position: int
    price_cents: int
    price: Decimal = Field(description="Price in standard currency units")
    compare_at_price_cents: Optional[int] = None
    compare_at_price: Optional[Decimal] = None
    inventory_quantity: int
    sku: Optional[str] = None
    status: str
    attributes: Dict[str, str] = Field(default_factory=dict)
    images: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def inject_decimal_prices(cls, data: Any) -> Any:
        if hasattr(data, "price_cents"):
            payload = data.model_dump()
            inject_cents_decimals(payload, [("price", "price_cents")])
            cap = payload.get("compare_at_price_cents")
            if cap is not None:
                payload.setdefault("compare_at_price", cents_to_decimal(cap))
            return payload
        if isinstance(data, dict):
            payload = dict(data)
            inject_cents_decimals(payload, [("price", "price_cents")])
            cap = payload.get("compare_at_price_cents")
            if cap is not None and "compare_at_price" not in payload:
                payload["compare_at_price"] = cents_to_decimal(cap)
            return payload
        return data


class ProductRead(BaseModel):
    id: int
    name: str
    slug: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    description: Optional[str]
    price_cents: int
    price: Decimal = Field(
        description="Price in standard currency units",
    )
    compare_at_price_cents: Optional[int]
    compare_at_price: Optional[Decimal] = Field(default=None, description="Compare-at price in standard currency units")
    sku: Optional[str]
    inventory_quantity: int
    units_sold: int = 0
    popularity_score: float = Field(
        default=0.0,
        description="units_sold divided by days since created_at (min 1 day)",
    )
    status: str
    category_id: Optional[int]
    has_variants: bool = False
    options: Dict[str, str] = Field(default_factory=dict)
    tags: List[Dict[str, Any]]
    images: List[Dict[str, Any]]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def inject_decimal_prices(cls, data: Any) -> Any:
        if hasattr(data, "price_cents"):
            payload = data.model_dump()
            inject_cents_decimals(payload, [("price", "price_cents")])
            cap = payload.get("compare_at_price_cents")
            if cap is not None:
                payload.setdefault("compare_at_price", cents_to_decimal(cap))
            return payload
        if isinstance(data, dict):
            payload = dict(data)
            inject_cents_decimals(payload, [("price", "price_cents")])
            cap = payload.get("compare_at_price_cents")
            if cap is not None and "compare_at_price" not in payload:
                payload["compare_at_price"] = cents_to_decimal(cap)
            return payload
        return data

    @field_validator("price", mode="before")
    @classmethod
    def compute_price(cls, v: Any, info) -> Decimal:
        """Compute ``price`` from ``price_cents`` if not provided."""
        if isinstance(v, Decimal):
            return v
        if isinstance(v, int):
            return cents_to_decimal(v)
        # Called with the whole model when from_attributes=True
        price_cents = info.data.get("price_cents") if isinstance(info.data, dict) else None
        if price_cents is not None:
            return cents_to_decimal(price_cents)
        return Decimal(0)

    @field_validator("compare_at_price", mode="before")
    @classmethod
    def compute_compare_at_price(cls, v: Any, info) -> Decimal | None:
        if isinstance(v, Decimal):
            return v
        price_cents = info.data.get("compare_at_price_cents") if isinstance(info.data, dict) else None
        if price_cents is None:
            return None
        if isinstance(v, int):
            return cents_to_decimal(v)
        return cents_to_decimal(price_cents)


class ProductDetailRead(ProductRead):
    variants: List[ProductVariantRead] = Field(default_factory=list)


class ProductList(PaginatedResponse["ProductRead"]):
    """Paginated product list."""
