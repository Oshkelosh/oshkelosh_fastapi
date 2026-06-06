"""Addon resolution and persisted configuration helpers."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import col, select

from app.addons.base import BaseAddon
from app.addons.frontends.base import FrontendAddon
from app.addons.notifications.base import NotificationAddon
from app.addons.payments.base import PaymentAddon
from app.addons.registry import addon_registry
from app.addons.suppliers.base import SupplierAddon
from app.addons.tools.base import ToolAddon
from app.core.exceptions import ValidationError
from models.addon_config import AddonConfig


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
    """Return the first enabled notification addon, or None."""
    enabled = get_enabled("notification")
    if not enabled:
        return None
    return enabled[0]  # type: ignore[return-value]


def get_frontend_addon() -> FrontendAddon | None:
    """Return the active storefront frontend addon, or None."""
    enabled = get_enabled("frontend")
    if not enabled:
        return None
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

    result = await session.execute(
        select(AddonConfig).where(col(AddonConfig.addon_id) == addon_id)
    )
    row = result.scalar_one_or_none()

    if enabled:
        await addon_registry.enable_async(addon_id, config)
    else:
        if addon.is_enabled:
            await addon_registry.disable_async(addon_id)
        addon_registry.save_config(addon_id, config)

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
