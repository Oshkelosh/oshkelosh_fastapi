"""Smoke tests for storefront script aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.tool_discovery import list_storefront_scripts


def test_list_storefront_scripts_keeps_entries_with_id():
    tool = MagicMock()
    tool.addon_id = "scripts"
    tool.list_storefront_scripts.return_value = [
        {"id": "umami", "src": "https://analytics.example.com/script.js", "routes": "all"},
        {"src": "https://missing-id.example/x.js"},
        "not-a-dict",
    ]
    with patch("app.services.tool_discovery.get_enabled_tools", return_value=[tool]):
        scripts = list_storefront_scripts()
    assert scripts == [
        {"id": "umami", "src": "https://analytics.example.com/script.js", "routes": "all"}
    ]
