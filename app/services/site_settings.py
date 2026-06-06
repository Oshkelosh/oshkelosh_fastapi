"""Site-wide settings singleton helpers."""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from models.site_settings import SiteSettings

_SINGLETON_ID = 1


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
    }
    optional_fields = {"logo_url", "favicon_url", "support_email", "meta_description"}
    for key, value in data.items():
        if key not in allowed:
            continue
        if key in optional_fields and value == "":
            setattr(row, key, None)
        else:
            setattr(row, key, value)

    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    await session.flush()
    await session.refresh(row)
    return row


def site_settings_to_dict(row: SiteSettings) -> dict:
    """Serialize site settings for API responses."""
    return {
        "store_name": row.store_name,
        "logo_url": row.logo_url,
        "favicon_url": row.favicon_url,
        "primary_color": row.primary_color,
        "secondary_color": row.secondary_color,
        "font_family": row.font_family,
        "support_email": row.support_email,
        "meta_description": row.meta_description,
    }
