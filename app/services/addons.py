"""Addon resolution and persisted configuration helpers."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import col, select

from app.addons.base import BaseAddon
from app.addons.compat import check_min_host_version
from app.addons.config_serialization import iter_secret_field_paths, secret_fields_changed
from app.addons.frontends.base import FrontendAddon
from app.addons.notifications.base import NotificationAddon
from app.addons.payments.base import PaymentAddon
from app.addons.registry import addon_registry
from app.addons.suppliers.base import SupplierAddon
from app.addons.tools.base import ToolAddon
from app.config import settings
from app.core.exceptions import ValidationError
from models.addon_config import AddonConfig


_frontend_addon_id: str | None = None


def invalidate_frontend_cache() -> None:
    """Clear cached active frontend addon id (after enable/disable)."""
    global _frontend_addon_id
    _frontend_addon_id = None


def get_enabled(category: str) -> list[BaseAddon]:
    """Return all enabled addons in a category."""
    return addon_registry.get_enabled(category)


def get_payment_addon() -> PaymentAddon | None:
    """Return the first enabled payment addon, or None."""
    enabled = get_enabled("payment")
    if not enabled:
        return None
    return enabled[0]  # type: ignore[return-value]


def require_payment_addon() -> PaymentAddon:
    """Return the active payment addon or raise."""
    addon = get_payment_addon()
    if addon is None:
        raise ValidationError(message="No payment processor is enabled")
    return addon


def get_notification_addon() -> NotificationAddon | None:
    """Return the first enabled notification addon, or None.

    Prefer ``get_notification_addon_for_channel`` for multi-channel dispatch.
    """
    enabled = get_enabled("notification")
    if not enabled:
        return None
    return enabled[0]  # type: ignore[return-value]


def get_notification_addon_for_channel(channel: str) -> NotificationAddon | None:
    """Return the enabled notification addon that supports ``channel``."""
    for addon in get_enabled("notification"):
        channels = getattr(addon, "supported_channels", None) or ["email"]
        if channel in channels:
            return addon  # type: ignore[return-value]
    return None


async def _disable_conflicting_notification_addons(
    session: Any,
    keep_addon_id: str,
    channels: list[str],
) -> None:
    """Disable other notification addons that share any channel with the one being enabled."""
    for other in addon_registry.get_enabled("notification"):
        if other.addon_id == keep_addon_id:
            continue
        other_channels = getattr(other, "supported_channels", None) or ["email"]
        if not set(other_channels) & set(channels):
            continue
        await addon_registry.disable_async(other.addon_id)
        result = await session.execute(
            select(AddonConfig).where(col(AddonConfig.addon_id) == other.addon_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.is_enabled = False
            if hasattr(session, "mark_dirty"):
                session.mark_dirty(row)


def get_frontend_addon() -> FrontendAddon | None:
    """Return the active storefront frontend addon, or None."""
    global _frontend_addon_id
    if _frontend_addon_id:
        cached = addon_registry.get(_frontend_addon_id)
        if (
            cached is not None
            and cached.is_enabled
            and cached.addon_category == "frontend"
        ):
            return cached  # type: ignore[return-value]
        _frontend_addon_id = None

    enabled = get_enabled("frontend")
    if not enabled:
        return None
    _frontend_addon_id = enabled[0].addon_id
    return enabled[0]  # type: ignore[return-value]


def get_tool_addon(tool_id: Optional[str] = None) -> ToolAddon | None:
    """Return a tool addon by id, or the first enabled tool."""
    if tool_id:
        addon = addon_registry.get(tool_id)
        if addon is None or not addon.is_enabled:
            return None
        return addon  # type: ignore[return-value]
    enabled = get_enabled("tool")
    if not enabled:
        return None
    return enabled[0]  # type: ignore[return-value]


def get_enabled_tools() -> list[ToolAddon]:
    """Return all enabled tool addons."""
    return get_enabled("tool")  # type: ignore[return-value]


def get_sso_addon() -> ToolAddon | None:
    """Return the SSO tool addon when enabled."""
    return get_tool_addon("sso")


def get_supplier_addon(supplier_id: Optional[str] = None) -> SupplierAddon | None:
    """Return a supplier addon by id, or the first enabled supplier."""
    if supplier_id:
        addon = addon_registry.get(supplier_id)
        if addon is None or not addon.is_enabled:
            return None
        return addon  # type: ignore[return-value]
    enabled = get_enabled("supplier")
    if not enabled:
        return None
    return enabled[0]  # type: ignore[return-value]


def merge_config_updates(addon_id: str, updates: dict) -> dict:
    """Merge form updates onto existing config, preserving secrets when redacted."""
    merged = dict(addon_registry.get_config(addon_id))
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and (not value.strip() or value.endswith("…")):
            continue
        merged[key] = value
    return merged


async def _disable_other_addons_in_category(
    session: Any,
    category: str,
    keep_addon_id: str,
) -> None:
    """Disable other enabled addons in the same category (e.g. one frontend at a time)."""
    for other in addon_registry.get_enabled(category):
        if other.addon_id == keep_addon_id:
            continue
        await addon_registry.disable_async(other.addon_id)
        result = await session.execute(
            select(AddonConfig).where(col(AddonConfig.addon_id) == other.addon_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.is_enabled = False
            if hasattr(session, "mark_dirty"):
                session.mark_dirty(row)


async def persist_addon_config(
    session: Any,
    addon_id: str,
    config: dict,
    enabled: bool,
) -> AddonConfig:
    """Upsert DB config and sync the in-memory registry."""
    addon = addon_registry.get(addon_id)
    if addon is None:
        raise ValidationError(message=f"Unknown addon: {addon_id}")

    if enabled and addon.addon_category in ("frontend", "payment"):
        await _disable_other_addons_in_category(session, addon.addon_category, addon_id)

    if enabled and addon.addon_category == "notification":
        channels = getattr(addon, "supported_channels", None) or ["email"]
        await _disable_conflicting_notification_addons(session, addon_id, list(channels))

    result = await session.execute(
        select(AddonConfig).where(col(AddonConfig.addon_id) == addon_id)
    )
    row = result.scalar_one_or_none()

    previous_config = addon_registry.get_config(addon_id)
    stored = addon_registry.parse_config(addon, config)
    secret_paths = iter_secret_field_paths(addon.config_schema())
    if secret_paths and secret_fields_changed(previous_config, stored, secret_paths):
        await addon.validate_config(stored)

    if enabled:
        check_min_host_version(addon, settings.app_version)
        addon_registry.apply_config(addon, stored)
        addon.is_enabled = True
        await addon.initialize(stored)
    else:
        if addon.is_enabled:
            await addon_registry.disable_async(addon_id)
        addon_registry.apply_config(addon, stored)

    if row:
        row.config = addon_registry.get_config(addon_id)
        row.is_enabled = enabled
        row.addon_type = addon.addon_category
    else:
        row = AddonConfig(
            addon_id=addon_id,
            addon_type=addon.addon_category,
            config=addon_registry.get_config(addon_id),
            is_enabled=enabled,
        )
        session.add(row)

    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    await session.flush()
    if addon.addon_category == "frontend":
        invalidate_frontend_cache()
    return row


def merge_addon_list(db_rows: dict[str, AddonConfig]) -> list[dict]:
    """Merge registry metadata with persisted DB state for admin listing."""
    items: list[dict] = []
    for meta in addon_registry.list_addons():
        addon_id = meta["addon_id"]
        stored = db_rows.get(addon_id)
        config = stored.config if stored else addon_registry.get_config(addon_id)
        items.append(
            {
                **meta,
                "is_enabled": stored.is_enabled if stored else meta["is_enabled"],
                "has_config": bool(config),
                "config": config,
            }
        )
    return items
