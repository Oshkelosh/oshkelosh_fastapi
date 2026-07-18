"""Resolve enabled push notification config for the storefront."""

from __future__ import annotations

from typing import Any

from app.services.addons import get_notification_addon_for_channel


def get_public_push_config() -> dict[str, Any] | None:
    """Return public push provider metadata for storefront subscription UI."""
    addon = get_notification_addon_for_channel("push")
    if addon is None:
        return None
    config = addon.list_public_push_config()
    if not config:
        return None
    return config


def build_push_service_worker_js() -> str | None:
    """Return the active push addon's service worker JS, or None if unavailable.

    Provider specifics (e.g. Firebase importScripts) live in the addon via
    ``NotificationAddon.push_service_worker_js``; core only serves the result.
    """
    addon = get_notification_addon_for_channel("push")
    if addon is None:
        return None
    return addon.push_service_worker_js()
