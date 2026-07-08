"""Built-in SSO / social login tool addon."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from app.addons.log import info
from app.addons.tools.base import ToolAddon
from app.addons.tools.sso.config import SsoConfig
from app.addons.tools.sso.providers.base import OAuthProvider
from app.addons.tools.sso.service import (
    build_provider_registry,
    build_public_providers,
    prepare_providers,
)
from app.addons.config_serialization import dump_addon_config
from app.addons.tools.sso.validation import validate_sso_config


class SsoToolAddon(ToolAddon):
    """Social sign-in via Google, Facebook, or generic OIDC providers."""

    addon_id: str = "sso"
    addon_name: str = "SSO Login"
    addon_description: str = (
        "Sign in with Google, Facebook, or a custom OpenID Connect provider."
    )
    addon_category: str = "tool"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None
    providers: Dict[str, OAuthProvider]

    def __init__(self) -> None:
        super().__init__()
        self.providers = {}

    @classmethod
    def config_schema(cls):
        return SsoConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self.providers = build_provider_registry(validated)
        await prepare_providers(self.providers)
        self.is_enabled = validated.is_active and bool(self.providers)
        info("SSO", "Initialized with {} provider(s)", len(self.providers))

    async def validate_config(self, config: dict) -> None:
        validated = self.config_schema()(**config)
        await validate_sso_config(validated)

    async def shutdown(self) -> None:
        self._config = None
        self.providers = {}
        self.is_enabled = False

    def list_public_providers(self) -> list[dict[str, str]]:
        if not self.is_enabled:
            return []
        return build_public_providers(self.providers)

    def get_routers(self) -> List[APIRouter]:
        from app.addons.tools.sso.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.tools.sso.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")
