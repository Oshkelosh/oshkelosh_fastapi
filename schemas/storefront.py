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
    site_url: str | None = Field(
        default=None,
        description="Resolved public storefront URL (from PUBLIC_APP_URL env and fallbacks).",
    )
    tax_enabled: bool = Field(
        default=True,
        description="Whether built-in tax is applied at checkout.",
    )
    tax_inclusive: bool = Field(
        default=False,
        description="When true, catalog prices are treated as tax-inclusive.",
    )
    tax_rate_bps: int = Field(
        default=800,
        description="Default tax rate in basis points (800 = 8%).",
    )
    shipping_mode: str = Field(
        default="flat",
        description="Built-in shipping mode: flat, free, or free_over_threshold.",
    )
    shipping_flat_cents: int = Field(
        default=500,
        description="Flat shipping amount in cents when mode is flat.",
    )
    shipping_free_threshold_cents: int | None = Field(
        default=None,
        description="Subtotal in cents above which shipping is free (free_over_threshold mode).",
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


class SsoProviderPublic(BaseModel):
    """Public SSO provider exposed to the storefront."""

    id: str = Field(description="Provider slug used in authorize URLs.", examples=["google"])
    label: str = Field(description="Button label.", examples=["Google"])
    authorize_url: str = Field(
        description="URL that starts the OAuth flow for this provider.",
        examples=["/api/v1/tools/sso/google/authorize"],
    )


class AuthConfigPublic(BaseModel):
    """Authentication options for the storefront."""

    sso_providers: list[SsoProviderPublic] = Field(
        default_factory=list,
        description="Enabled social sign-in providers (empty when SSO addon is off).",
    )
    email_verification_enabled: bool = Field(
        default=True,
        description=(
            "When true, the shop sends verification emails after registration. "
            "Verification is optional and never blocks shopping."
        ),
    )


class PushConfigPublic(BaseModel):
    """Public web push client configuration (no secrets)."""

    provider: str = Field(
        description="Push addon id (fcm, onesignal, pusher_beams).",
        examples=["fcm"],
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific public client config for browser SDK initialization.",
    )


class NotificationsConfigPublic(BaseModel):
    """Notification options exposed to the storefront."""

    push: PushConfigPublic | None = Field(
        default=None,
        description="Enabled push provider and client config, or null when push is off.",
    )


class ToolsConfigPublic(BaseModel):
    """Optional tool scripts and consent metadata for the storefront."""

    scripts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Enabled tool script descriptors (analytics, chat, consent banner, etc.).",
    )
    consent_categories: list[str] = Field(
        default_factory=lambda: ["necessary", "analytics", "marketing"],
        description="Consent categories tools may register under (placeholder until consent tool ships).",
    )


class StorefrontConfigResponse(BaseModel):
    """Merged configuration returned to the active storefront SPA."""

    site: SiteSettingsPublic = Field(description="Site-wide branding from Site Settings.")
    frontend: ActiveFrontendInfo = Field(
        description="Active frontend addon and its validated configuration."
    )
    auth: AuthConfigPublic = Field(
        default_factory=AuthConfigPublic,
        description="Storefront authentication options.",
    )
    notifications: NotificationsConfigPublic = Field(
        default_factory=NotificationsConfigPublic,
        description="Storefront notification options (push subscription UI).",
    )
    tools: ToolsConfigPublic = Field(
        default_factory=ToolsConfigPublic,
        description="Optional tool scripts and consent categories for storefront injection.",
    )


class StorefrontUnavailableResponse(BaseModel):
    """Returned when no frontend addon is enabled."""

    detail: str = Field(
        default="No storefront frontend is enabled",
        description="Enable a frontend addon at /admin/addons.",
    )
