"""Resolve an enabled bot-challenge tool and enforce it on anonymous auth."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from app.addons.tools.base import ToolAddon
from app.core.rate_limit import _client_key
from app.services.addons import get_enabled_tools

logger = logging.getLogger(__name__)


def _tool_for(action: str) -> ToolAddon | None:
    # ponytail: first enabled tool that protects the action wins. Enable one challenge addon.
    for tool in get_enabled_tools():
        try:
            protects = tool.protects_challenge(action)
        except Exception:
            logger.exception("Tool '%s' protects_challenge failed", tool.addon_id)
            continue
        if protects:
            return tool
    return None


def public_bot_challenge() -> dict[str, Any] | None:
    """Return storefront widget config from the first tool that publishes one."""
    for tool in get_enabled_tools():
        try:
            raw = tool.challenge_public_config()
        except Exception:
            logger.exception("Tool '%s' challenge_public_config failed", tool.addon_id)
            continue
        if not isinstance(raw, dict):
            continue
        site_key = str(raw.get("site_key") or "").strip()
        script_url = str(raw.get("script_url") or "").strip()
        actions = raw.get("actions") or []
        if not site_key or not script_url.startswith("https://") or not isinstance(actions, list):
            logger.warning("Tool '%s' returned invalid challenge config", tool.addon_id)
            continue
        return {
            "site_key": site_key,
            "script_url": script_url,
            "actions": [str(item) for item in actions if isinstance(item, str) and item.strip()],
        }
    return None


def admin_challenge_widget_html() -> str:
    """Return the admin login widget from the tool that protects that action."""
    tool = _tool_for("admin_login")
    if tool is None:
        return ""
    try:
        return tool.admin_challenge_widget_html() or ""
    except Exception:
        logger.exception("Tool '%s' admin_challenge_widget_html failed", tool.addon_id)
        return ""


async def enforce_bot_challenge(
    request: Request,
    action: str,
    token: str | None = None,
) -> None:
    """No-op when no tool protects ``action``. Otherwise verify the token.

    JSON clients send ``X-Bot-Challenge``. Admin login passes the ``bot_challenge``
    form field as ``token``.
    """
    tool = _tool_for(action)
    if tool is None:
        return
    if token is None:
        token = request.headers.get("x-bot-challenge")
    cleaned = (token or "").strip() or None
    remote_ip = _client_key(request)
    await tool.verify_bot_challenge(
        cleaned,
        None if remote_ip == "unknown" else remote_ip,
        action,
    )
