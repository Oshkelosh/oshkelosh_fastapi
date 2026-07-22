"""Site-wide settings singleton helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlmodel import select

from app.config import settings
from app.services.currency import normalize_currency, shop_currency_from_settings
from models.site_settings import (
    DEFAULT_ABOUT_PAGE_TITLE,
    DEFAULT_PRIVACY_POLICY_TITLE,
    SiteSettings,
)

if TYPE_CHECKING:
    from starlette.requests import Request

_SINGLETON_ID = 1
_DEV_FALLBACK_BASE_URL = "http://localhost:8000"

_VALID_SHIPPING_MODES = frozenset({"flat", "free", "free_over_threshold"})


def resolve_public_site_url(
    *,
    site_settings: SiteSettings | None = None,
    request: Request | None = None,
) -> str:
    """Resolve the canonical public storefront URL for links, SEO, and redirects."""
    if settings.public_app_url and settings.public_app_url.strip():
        return settings.public_app_url.strip().rstrip("/")

    if site_settings and site_settings.site_url and site_settings.site_url.strip():
        return site_settings.site_url.strip().rstrip("/")

    if settings.cors_origins:
        return settings.cors_origins[0].rstrip("/")

    if request is not None:
        return str(request.base_url).rstrip("/")

    return _DEV_FALLBACK_BASE_URL


def is_dev_fallback_site_url(url: str) -> bool:
    """True when the resolved URL is the built-in localhost fallback."""
    return url.rstrip("/") == _DEV_FALLBACK_BASE_URL


async def get_site_settings(session: Any) -> SiteSettings:
    """Return the site settings row, creating defaults if missing."""
    result = await session.execute(
        select(SiteSettings).where(SiteSettings.id == _SINGLETON_ID)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = SiteSettings(id=_SINGLETON_ID)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


def _parse_zones_json(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [z for z in parsed if isinstance(z, dict)]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


async def update_site_settings(session: Any, data: dict) -> SiteSettings:
    """Update allowed site settings fields."""
    row = await get_site_settings(session)
    allowed = {
        "store_name",
        "logo_url",
        "favicon_url",
        "primary_color",
        "secondary_color",
        "font_family",
        "support_email",
        "meta_description",
        "site_url",
        "shop_currency",
        "tax_enabled",
        "tax_inclusive",
        "tax_rate_bps",
        "tax_zones_json",
        "shipping_mode",
        "shipping_flat_cents",
        "shipping_free_threshold_cents",
        "shipping_zones_json",
        "abandoned_cart_enabled",
        "abandoned_cart_delay_hours",
        "abandoned_cart_max_reminders",
        "gdpr_banner_enabled",
        "gdpr_banner_text",
        "privacy_policy_enabled",
        "privacy_policy_title",
        "privacy_policy_body",
        "privacy_policy_effective_date",
        "about_page_enabled",
        "about_page_title",
        "about_page_body",
        "about_contact_body",
    }
    optional_fields = {
        "logo_url",
        "favicon_url",
        "support_email",
        "meta_description",
        "site_url",
        "shipping_free_threshold_cents",
        "gdpr_banner_text",
        "privacy_policy_body",
        "privacy_policy_effective_date",
        "about_page_body",
        "about_contact_body",
    }
    bool_fields = {
        "tax_enabled",
        "tax_inclusive",
        "abandoned_cart_enabled",
        "gdpr_banner_enabled",
        "privacy_policy_enabled",
        "about_page_enabled",
    }
    json_list_fields = {"tax_zones_json", "shipping_zones_json"}

    for key, value in data.items():
        if key not in allowed:
            continue
        if key in optional_fields and value in ("", None):
            setattr(row, key, None)
        elif key in bool_fields:
            setattr(row, key, _coerce_bool(value))
        elif key in json_list_fields:
            if isinstance(value, str):
                setattr(row, key, _parse_zones_json(value))
            elif isinstance(value, list):
                setattr(row, key, value)
        elif key == "shipping_mode":
            mode = str(value).strip() if value is not None else "flat"
            setattr(row, key, mode if mode in _VALID_SHIPPING_MODES else "flat")
        elif key in ("tax_rate_bps", "shipping_flat_cents", "shipping_free_threshold_cents"):
            if value in ("", None) and key == "shipping_free_threshold_cents":
                setattr(row, key, None)
            else:
                setattr(row, key, max(0, int(value)))
        elif key in ("abandoned_cart_delay_hours", "abandoned_cart_max_reminders"):
            setattr(row, key, max(1, int(value)))
        elif key == "shop_currency":
            setattr(row, key, normalize_currency(str(value) if value is not None else None))
        elif key == "privacy_policy_title":
            title = str(value).strip() if value is not None else ""
            setattr(row, key, title or DEFAULT_PRIVACY_POLICY_TITLE)
        elif key == "about_page_title":
            title = str(value).strip() if value is not None else ""
            setattr(row, key, title or DEFAULT_ABOUT_PAGE_TITLE)
        else:
            setattr(row, key, value)

    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    await session.flush()
    await session.refresh(row)
    return row


def site_settings_to_dict(row: SiteSettings) -> dict:
    """Serialize site settings for audit and internal use (raw DB values)."""
    return {
        "store_name": row.store_name,
        "logo_url": row.logo_url,
        "favicon_url": row.favicon_url,
        "primary_color": row.primary_color,
        "secondary_color": row.secondary_color,
        "font_family": row.font_family,
        "support_email": row.support_email,
        "meta_description": row.meta_description,
        "site_url": row.site_url,
        "shop_currency": shop_currency_from_settings(row),
        "tax_enabled": row.tax_enabled,
        "tax_inclusive": row.tax_inclusive,
        "tax_rate_bps": row.tax_rate_bps,
        "tax_zones_json": row.tax_zones_json or [],
        "shipping_mode": row.shipping_mode,
        "shipping_flat_cents": row.shipping_flat_cents,
        "shipping_free_threshold_cents": row.shipping_free_threshold_cents,
        "shipping_zones_json": row.shipping_zones_json or [],
        "abandoned_cart_enabled": row.abandoned_cart_enabled,
        "abandoned_cart_delay_hours": row.abandoned_cart_delay_hours,
        "abandoned_cart_max_reminders": row.abandoned_cart_max_reminders,
        "gdpr_banner_enabled": row.gdpr_banner_enabled,
        "gdpr_banner_text": row.gdpr_banner_text,
        "privacy_policy_enabled": row.privacy_policy_enabled,
        "privacy_policy_title": row.privacy_policy_title,
        "privacy_policy_body": row.privacy_policy_body,
        "privacy_policy_effective_date": row.privacy_policy_effective_date,
        "about_page_enabled": row.about_page_enabled,
        "about_page_title": row.about_page_title,
        "about_page_body": row.about_page_body,
        "about_contact_body": row.about_contact_body,
    }


def site_settings_to_public_dict(
    row: SiteSettings,
    *,
    request: Request | None = None,
) -> dict:
    """Serialize site settings for storefront clients with resolved public URL."""
    data = site_settings_to_dict(row)
    data["site_url"] = resolve_public_site_url(site_settings=row, request=request)
    return data
