"""Site-wide storefront branding and contact settings (singleton row)."""

from typing import Optional

from sqlalchemy import Column, String, Text
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
