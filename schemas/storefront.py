"""Pydantic schemas for storefront config API (OpenAPI + type safety)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SiteSettingsPublic(BaseModel):
    """Site-wide branding exposed to the storefront SPA."""

    store_name: str = Field(description="Display name shown in title, header, and emails.")
    logo_url: str | None = Field(default=None, description="Absolute URL to logo image.")
    favicon_url: str | None = Field(default=None, description="Absolute URL to favicon.")
    primary_color: str = Field(
        default="#2563eb",
        description="Primary brand color (hex). Mapped to CSS `--color-primary`.",
        examples=["#2563eb"],
    )
    secondary_color: str = Field(
        default="#64748b",
        description="Secondary brand color (hex). Mapped to CSS `--color-secondary`.",
    )
    font_family: str = Field(
        default="system-ui, sans-serif",
        description="CSS font-family stack. Mapped to CSS `--font-sans`.",
    )
    support_email: str | None = Field(default=None, description="Customer support contact.")
    meta_description: str | None = Field(
        default=None,
        description="Default HTML meta description for SEO.",
    )

    model_config = ConfigDict(from_attributes=True)


class ActiveFrontendInfo(BaseModel):
    """Metadata and config for the currently enabled frontend addon."""

    addon_id: str = Field(description="Unique frontend addon identifier.", examples=["default"])
    addon_name: str = Field(description="Human-readable frontend name.")
    version: str = Field(description="Frontend addon semver.", examples=["1.0.0"])
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Frontend-specific settings from the addon's Pydantic config_schema. "
            "Shape varies per frontend; see that addon's README."
        ),
    )


class StorefrontConfigResponse(BaseModel):
    """Merged configuration returned to the active storefront SPA."""

    site: SiteSettingsPublic = Field(description="Site-wide branding from Site Settings.")
    frontend: ActiveFrontendInfo = Field(
        description="Active frontend addon and its validated configuration."
    )


class StorefrontUnavailableResponse(BaseModel):
    """Returned when no frontend addon is enabled."""

    detail: str = Field(
        default="No storefront frontend is enabled",
        description="Enable a frontend addon at /admin/addons.",
    )
