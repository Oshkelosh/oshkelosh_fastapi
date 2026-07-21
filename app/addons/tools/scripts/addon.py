"""Built-in Scripts tool addon — inject external storefront <script> tags."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

from app.addons.config_serialization import dump_addon_config
from app.addons.log import info
from app.addons.tools.base import ToolAddon
from app.addons.tools.scripts.config import ScriptsConfig


class ScriptsToolAddon(ToolAddon):
    """Manage pasted external script tags for the storefront."""

    addon_id: str = "scripts"
    addon_name: str = "Scripts"
    addon_description: str = (
        "Inject external storefront script tags (analytics, chat widgets, etc.) "
        "with public/private route scope."
    )
    addon_category: str = "tool"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None

    def __init__(self) -> None:
        super().__init__()
        self._config = None

    @classmethod
    def config_schema(cls):
        return ScriptsConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self.is_enabled = True
        info("Scripts", "Initialized with {} script(s)", len(validated.scripts))

    async def shutdown(self) -> None:
        self._config = None
        self.is_enabled = False

    def list_storefront_scripts(self) -> list[dict[str, Any]]:
        if not self.is_enabled or not self._config:
            return []
        out: list[dict[str, Any]] = []
        for entry in self._config.get("scripts") or []:
            if not entry.get("enabled"):
                continue
            src = entry.get("src")
            script_id = entry.get("id")
            if not src or not script_id:
                continue
            out.append(
                {
                    "id": script_id,
                    "src": src,
                    "attrs": dict(entry.get("attrs") or {}),
                    "routes": entry.get("routes") or "all",
                }
            )
        return out

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.tools.scripts.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        return str(Path(__file__).resolve().parent / "templates")
