"""Product model.

Products are the core sellable entity in the catalogue.  Prices are stored
as integers (cents) to avoid floating-point rounding issues.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.cart_item import CartItem
    from models.category import Category
    from models.order_item import OrderItem
    from models.product_image import ProductImage
    from models.product_variant import ProductVariant
    from models.user import User


class Product(ModelBase, table=True):
    """A sellable product."""

    __tablename__ = "products"

    name: str = Field(sa_column=Column(String(255), nullable=False))
    slug: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), unique=True, nullable=True, index=True),
    )
    meta_title: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    meta_description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    price_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False),
    )
    compare_at_price_cents: Optional[int] = Field(
        default=None,
        ge=0,
        sa_column=Column(Integer, nullable=True),
    )
    sku: Optional[str] = Field(
        default=None,
        sa_column=Column(String(100), unique=True, nullable=True),
    )
    inventory_quantity: int = Field(
        default=0,
        ge=0,
        sa_column=Column(Integer, nullable=False),
    )
    units_sold: int = Field(
        default=0,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    # Stored as a Python str but validated in the schema layer against a
    # small enum; the column type is simply VARCHAR to keep it simple.
    status: str = Field(
        default="draft",
        sa_column=Column(String(20), nullable=False, server_default="draft"),
    )

    has_variants: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    supplier_external_product_key: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, index=True),
    )

    # Creator additional info (material, care, specs) — not sellable, not client picker
    options: Dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )

    # Free-form JSON fields
    tags: List[Dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )

    # ── Foreign keys ───────────────────────────────────────────────
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    category_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True),
    )

    # ── Relationships ──────────────────────────────────────────────
    created_by_user: Optional["User"] = Relationship(
        back_populates="products",
        sa_relationship_kwargs={"foreign_keys": "Product.created_by"},
    )
    images_rel: List["ProductImage"] = Relationship(
        back_populates="product",
        cascade_delete=True,
    )
    variants: List["ProductVariant"] = Relationship(
        back_populates="product",
        cascade_delete=True,
    )
    cart_items: List["CartItem"] = Relationship(back_populates="product")
    order_items: List["OrderItem"] = Relationship(back_populates="product")
    category_rel: Optional["Category"] = Relationship(back_populates="products")
