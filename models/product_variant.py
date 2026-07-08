"""ProductVariant model — client-facing sellable unit linked to a base product."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.cart_item import CartItem
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_image import ProductImage


class ProductVariant(ModelBase, table=True):
    """A purchasable variant of a product (size, color, format, etc.)."""

    __tablename__ = "product_variants"

    product_id: int = Field(
        sa_column=Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    )
    title: str = Field(sa_column=Column(String(255), nullable=False))
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    price_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False),
    )
    compare_at_price_cents: Optional[int] = Field(
        default=None,
        ge=0,
        sa_column=Column(Integer, nullable=True),
    )
    inventory_quantity: int = Field(
        default=0,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    sku: Optional[str] = Field(
        default=None,
        sa_column=Column(String(100), nullable=True),
    )
    status: str = Field(
        default="active",
        sa_column=Column(String(20), nullable=False, server_default="active"),
    )
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    supplier_addon_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    supplier_product_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    supplier_variant_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    supplier_external_key: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, index=True),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )

    product: "Product" = Relationship(back_populates="variants")
    images_rel: list["ProductImage"] = Relationship(
        back_populates="variant",
        cascade_delete=True,
    )
    cart_items: list["CartItem"] = Relationship(back_populates="variant")
    order_items: list["OrderItem"] = Relationship(back_populates="variant")
