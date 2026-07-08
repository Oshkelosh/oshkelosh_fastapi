"""Site-wide storefront branding and contact settings (singleton row)."""

from typing import Any, List, Optional

from sqlalchemy import Boolean, Column, Integer, JSON, String, Text
from sqlmodel import Field

from app.db.base import ModelBase


class SiteSettings(ModelBase, table=True):
    """Global site branding used by storefront, admin, and notifications."""

    __tablename__ = "site_settings"

    store_name: str = Field(
        default="Oshkelosh",
        sa_column=Column(String(255), nullable=False, server_default="Oshkelosh"),
    )
    logo_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    favicon_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    primary_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(32), nullable=False, server_default="#2563eb"),
    )
    secondary_color: str = Field(
        default="#64748b",
        sa_column=Column(String(32), nullable=False, server_default="#64748b"),
    )
    font_family: str = Field(
        default="system-ui, sans-serif",
        sa_column=Column(String(255), nullable=False, server_default="system-ui, sans-serif"),
    )
    support_email: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    meta_description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    site_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))

    # Built-in tax rules (defaults: 8% tax enabled)
    tax_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
    tax_inclusive: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    tax_rate_bps: int = Field(
        default=800,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="800"),
    )
    tax_zones_json: List[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

    # Built-in shipping rules (defaults: $5 flat shipping)
    shipping_mode: str = Field(
        default="flat",
        sa_column=Column(String(32), nullable=False, server_default="flat"),
    )
    shipping_flat_cents: int = Field(
        default=500,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="500"),
    )
    shipping_free_threshold_cents: Optional[int] = Field(
        default=None,
        ge=0,
        sa_column=Column(Integer, nullable=True),
    )
    shipping_zones_json: List[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

    # Native abandoned cart recovery
    abandoned_cart_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    abandoned_cart_delay_hours: int = Field(
        default=24,
        ge=1,
        sa_column=Column(Integer, nullable=False, server_default="24"),
    )
    abandoned_cart_max_reminders: int = Field(
        default=1,
        ge=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
