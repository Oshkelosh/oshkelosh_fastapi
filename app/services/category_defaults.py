"""Category creation defaults (SEO meta fields)."""

from __future__ import annotations

from typing import Any

from app.db.connection import mark_instance_dirty
from app.storefront.seo import truncate_text
from models.category import Category

_DESCRIPTION_MAX = 160


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def default_category_meta(
    category: Category,
    store_name: str,
    *,
    site_default_description: str | None = None,
) -> tuple[str, str | None]:
    """Return default meta_title and meta_description for a category."""
    title = f"{category.name} | {store_name}"
    description = truncate_text(category.description, _DESCRIPTION_MAX)
    if not description:
        description = truncate_text(site_default_description, _DESCRIPTION_MAX)
    return title, description


async def apply_category_creation_defaults(
    session: Any,
    category: Category,
    *,
    store_name: str,
    site_default_description: str | None = None,
) -> None:
    """Persist SEO meta fields when missing at category creation."""
    if site_default_description is None:
        from app.services.site_settings import get_site_settings

        site_settings = await get_site_settings(session)
        site_default_description = site_settings.meta_description

    if not _normalize_optional(category.meta_title):
        meta_title, meta_description = default_category_meta(
            category,
            store_name,
            site_default_description=site_default_description,
        )
        category.meta_title = meta_title
        if not _normalize_optional(category.meta_description):
            category.meta_description = meta_description
    elif not _normalize_optional(category.meta_description):
        _, meta_description = default_category_meta(
            category,
            store_name,
            site_default_description=site_default_description,
        )
        category.meta_description = meta_description

    mark_instance_dirty(session, category)
