"""Shared customer address schema for profiles and orders."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.countries import require_iso_country


class Address(BaseModel):
    """Postal address used for shipping and billing."""

    line1: str = Field(min_length=1, max_length=255)
    line2: Optional[str] = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=128)
    state: Optional[str] = Field(default=None, max_length=128)
    postal_code: str = Field(min_length=1, max_length=32)
    country: str = Field(
        min_length=2,
        max_length=64,
        description="ISO-3166-1 alpha-2 country code (aliases like 'USA' accepted).",
    )
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)

    model_config = ConfigDict(extra="ignore")

    @field_validator("country", mode="before")
    @classmethod
    def _normalize_country(cls, v: Any) -> str:
        return require_iso_country(v)

    def to_storage_dict(self) -> dict:
        """JSON-serializable dict for DB columns (omit empty optionals)."""
        return self.model_dump(exclude_none=True)
