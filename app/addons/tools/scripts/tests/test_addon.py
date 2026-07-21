"""Unit tests for the Scripts tool addon."""

from __future__ import annotations

import pytest

from app.addons.tools.scripts.addon import ScriptsToolAddon
from app.addons.tools.scripts.parse import ScriptTagError, format_script_tag, parse_script_tag

UMAMI = (
    '<script defer src="https://analytics.bmd-studios.com/script.js" '
    'data-website-id="0eff5de2-4ddd-4398-a440-a8ecc0da3d13"></script>'
)


class TestParseScriptTag:
    def test_umami_tag(self):
        src, attrs = parse_script_tag(UMAMI)
        assert src == "https://analytics.bmd-studios.com/script.js"
        assert attrs["defer"] is True
        assert attrs["data-website-id"] == "0eff5de2-4ddd-4398-a440-a8ecc0da3d13"
        rebuilt = format_script_tag(src, attrs)
        assert 'src="https://analytics.bmd-studios.com/script.js"' in rebuilt
        assert "defer" in rebuilt

    def test_rejects_inline(self):
        with pytest.raises(ScriptTagError, match="Inline"):
            parse_script_tag("<script>alert(1)</script>")

    def test_rejects_http(self):
        with pytest.raises(ScriptTagError, match="https"):
            parse_script_tag('<script src="http://example.com/a.js"></script>')

    def test_rejects_onclick(self):
        with pytest.raises(ScriptTagError, match="Event-handler"):
            parse_script_tag('<script src="https://example.com/a.js" onclick="x"></script>')

    def test_rejects_multiple_tags(self):
        with pytest.raises(ScriptTagError, match="exactly one"):
            parse_script_tag(
                '<script src="https://a.example/a.js"></script>'
                '<script src="https://b.example/b.js"></script>'
            )

    def test_rejects_non_script(self):
        with pytest.raises(ScriptTagError, match="script"):
            parse_script_tag("<div></div>")


class TestScriptsToolAddon:
    def test_required_attrs(self):
        assert ScriptsToolAddon.addon_id == "scripts"
        assert ScriptsToolAddon.addon_category == "tool"

    @pytest.mark.asyncio
    async def test_list_storefront_scripts_filters_disabled(self):
        addon = ScriptsToolAddon()
        await addon.initialize(
            {
                "scripts": [
                    {
                        "id": "one",
                        "name": "Umami",
                        "enabled": True,
                        "routes": "all",
                        "src": "https://analytics.example.com/script.js",
                        "attrs": {"defer": True, "data-website-id": "abc"},
                    },
                    {
                        "id": "two",
                        "name": "Off",
                        "enabled": False,
                        "routes": "public",
                        "src": "https://example.com/off.js",
                        "attrs": {},
                    },
                ]
            }
        )
        scripts = addon.list_storefront_scripts()
        assert len(scripts) == 1
        assert scripts[0]["id"] == "one"
        assert scripts[0]["src"] == "https://analytics.example.com/script.js"
        assert scripts[0]["attrs"]["defer"] is True
        assert scripts[0]["routes"] == "all"

    @pytest.mark.asyncio
    async def test_list_empty_when_disabled(self):
        addon = ScriptsToolAddon()
        await addon.initialize(
            {
                "scripts": [
                    {
                        "id": "one",
                        "name": "Umami",
                        "enabled": True,
                        "routes": "all",
                        "src": "https://analytics.example.com/script.js",
                        "attrs": {},
                    }
                ]
            }
        )
        await addon.shutdown()
        assert addon.list_storefront_scripts() == []
