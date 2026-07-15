"""Pydantic model for oshkelosh-addon.json in distributable addon packages."""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AddonCategory = Literal["supplier", "payment", "notification", "frontend", "tool"]

_ADDON_ID_RE = re.compile(r"^[a-z0-9_]+$")


class AddonManifest(BaseModel):
    """Manifest shipped inside an addon ZIP."""

    addon_id: str = Field(min_length=1, max_length=100)
    addon_name: str = Field(min_length=1, max_length=255)
    addon_description: str = Field(default="", max_length=2000)
    category: AddonCategory
    version: str = Field(min_length=1, max_length=50)
    min_oshkelosh_version: str = Field(min_length=1, max_length=50)
    max_oshkelosh_version: Optional[str] = Field(default=None, max_length=50)
    python_requires: str = Field(default=">=3.11", max_length=100)
    source_url: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="HTTPS URL to reinstall/update this addon (GitHub repo or ZIP)",
    )

    @field_validator("addon_id")
    @classmethod
    def validate_addon_id(cls, value: str) -> str:
        if not _ADDON_ID_RE.match(value):
            raise ValueError("addon_id must contain only lowercase letters, digits, and underscores")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not cleaned.lower().startswith("https://"):
            raise ValueError("source_url must be an HTTPS URL")
        return cleaned
