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


def build_fcm_service_worker_js() -> str | None:
    """Return generated FCM service worker JavaScript, or None if FCM is not active."""
    import json

    push = get_public_push_config()
    if not push or push.get("provider") != "fcm":
        return None
    firebase_config = json.dumps(push.get("config") or {})
    return f"""importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-messaging-compat.js');
firebase.initializeApp({firebase_config});
firebase.messaging();
"""
