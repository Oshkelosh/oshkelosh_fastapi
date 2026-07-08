"""Resolve enabled third-party tax tools for checkout."""

from __future__ import annotations

from app.addons.tools.base import ToolAddon
from app.services.addons import get_enabled_tools


def get_tax_tool() -> ToolAddon | None:
    """Return the first enabled tool that supports third-party tax quotes."""
    for tool in get_enabled_tools():
        if tool.supports_tax_quotes():
            return tool
    return None
