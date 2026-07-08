"""Tests for addon credential validation on config save."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, Field, SecretStr
import httpx

from app.addons.base import BaseAddon
from app.addons.config_serialization import (
    dump_addon_config,
    get_config_at_path,
    iter_secret_field_paths,
    secret_fields_changed,
)
from app.addons.registry import AddonRegistry
from app.core.exceptions import ValidationError
from app.services.addons import merge_config_updates, persist_addon_config


class _NestedSecretConfig(BaseModel):
    google: dict = Field(default_factory=lambda: {"client_secret": ""})


class _SecretConfig(BaseModel):
    api_key: SecretStr = Field(default=...)
    label: str = "test"


class _ValidatingAddon(BaseAddon):
    addon_id = "validating_addon"
    addon_name = "Validating Addon"
    addon_description = "Test"
    addon_category = "notification"
    version = "0.0.1"

    def __init__(self) -> None:
        super().__init__()
        self.validate_calls = 0

    @classmethod
    def config_schema(cls):
        return _SecretConfig

    async def initialize(self, config: dict) -> None:
        self._config = config
        self.is_enabled = True

    async def shutdown(self) -> None:
        self.is_enabled = False

    async def validate_config(self, config: dict) -> None:
        self.validate_calls += 1
        if config.get("api_key") == "bad-key":
            raise ValidationError(message="Invalid API key — check your credentials")
        if config.get("api_key") == "limited-key":
            raise ValidationError(
                message="API key is valid but missing required permissions: catalog:read"
            )


class TestSecretFieldHelpers:
    def test_iter_secret_field_paths_nested(self):
        from app.addons.tools.sso.config import SsoConfig

        paths = iter_secret_field_paths(SsoConfig)
        assert ("google", "client_secret") in paths
        assert ("facebook", "app_secret") in paths

    def test_get_config_at_path(self):
        config = {"google": {"client_secret": "abc"}}
        assert get_config_at_path(config, ("google", "client_secret")) == "abc"

    def test_secret_fields_changed_detects_updates(self):
        paths = [("api_key",)]
        before = {"api_key": "old"}
        after = {"api_key": "new"}
        assert secret_fields_changed(before, after, paths) is True

    def test_secret_fields_changed_ignores_unchanged(self):
        paths = [("api_key",)]
        config = {"api_key": "same"}
        assert secret_fields_changed(config, dict(config), paths) is False

    def test_merge_config_updates_skips_redacted_secret(self):
        from app.addons.registry import addon_registry

        addon = _ValidatingAddon()
        addon._config = {"api_key": "stored-secret", "label": "x"}
        addon_registry._registry["validating_addon"] = addon

        merged = merge_config_updates(
            "validating_addon",
            {"api_key": "abcd1234…", "label": "updated"},
        )
        assert merged["api_key"] == "stored-secret"
        assert merged["label"] == "updated"

        addon_registry._registry.pop("validating_addon", None)


class TestPersistAddonConfigValidation:
    async def test_validate_config_called_when_secret_changes(self, db_session):
        from app.addons.registry import addon_registry

        addon = _ValidatingAddon()
        addon._config = {"api_key": "old-key", "label": "x"}
        addon_registry._registry["validating_addon"] = addon

        await persist_addon_config(
            db_session,
            "validating_addon",
            {"api_key": "new-key", "label": "x"},
            enabled=False,
        )
        assert addon.validate_calls == 1

        addon_registry._registry.pop("validating_addon", None)

    async def test_validate_config_not_called_when_secret_unchanged(self, db_session):
        from app.addons.registry import addon_registry

        addon = _ValidatingAddon()
        addon._config = {"api_key": "same-key", "label": "x"}
        addon_registry._registry["validating_addon"] = addon

        await persist_addon_config(
            db_session,
            "validating_addon",
            {"api_key": "same-key", "label": "changed"},
            enabled=False,
        )
        assert addon.validate_calls == 0

        addon_registry._registry.pop("validating_addon", None)

    async def test_invalid_secret_blocks_persist(self, db_session):
        from app.addons.registry import addon_registry
        from models.addon_config import AddonConfig
        from sqlmodel import select

        addon = _ValidatingAddon()
        addon._config = {"api_key": "old-key", "label": "x"}
        addon_registry._registry["validating_addon"] = addon

        with pytest.raises(ValidationError, match="Invalid API key"):
            await persist_addon_config(
                db_session,
                "validating_addon",
                {"api_key": "bad-key", "label": "x"},
                enabled=False,
            )

        result = await db_session.execute(
            select(AddonConfig).where(AddonConfig.addon_id == "validating_addon")
        )
        assert result.scalar_one_or_none() is None
        assert addon_registry.get_config("validating_addon")["api_key"] == "old-key"

        addon_registry._registry.pop("validating_addon", None)

    async def test_permission_error_blocks_persist(self, db_session):
        from app.addons.registry import addon_registry

        addon = _ValidatingAddon()
        addon._config = {"api_key": "old-key", "label": "x"}
        addon_registry._registry["validating_addon"] = addon

        with pytest.raises(ValidationError, match="missing required permissions"):
            await persist_addon_config(
                db_session,
                "validating_addon",
                {"api_key": "limited-key", "label": "x"},
                enabled=False,
            )

        addon_registry._registry.pop("validating_addon", None)


class TestSsoValidateConfig:
    @pytest.mark.asyncio
    async def test_oidc_discovery_failure_raises(self):
        from app.addons.tools.sso.addon import SsoToolAddon
        from app.addons.tools.sso.config import SsoConfig

        addon = SsoToolAddon()
        config = dump_addon_config(
            SsoConfig(
                oidc_providers=[
                    {
                        "provider_id": "custom",
                        "enabled": True,
                        "issuer_url": "https://issuer.example.com",
                        "client_id": "client",
                        "client_secret": "secret",
                    }
                ]
            )
        )

        with patch("app.addons.tools.sso.validation.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=httpx.RequestError("unreachable"))

            with pytest.raises(ValidationError, match="issuer is unreachable"):
                await addon.validate_config(config)

    @pytest.mark.asyncio
    async def test_missing_oidc_scopes_raises(self):
        from app.addons.tools.sso.addon import SsoToolAddon
        from app.addons.tools.sso.config import SsoConfig

        addon = SsoToolAddon()
        config = dump_addon_config(
            SsoConfig(
                oidc_providers=[
                    {
                        "provider_id": "custom",
                        "enabled": True,
                        "issuer_url": "https://issuer.example.com",
                        "client_id": "client",
                        "client_secret": "secret",
                        "scopes": "openid",
                    }
                ]
            )
        )

        with pytest.raises(ValidationError, match="missing required scopes"):
            await addon.validate_config(config)


class TestRegistryParseConfig:
    def test_parse_config_does_not_mutate_instance(self):
        registry = AddonRegistry()
        addon = _ValidatingAddon()
        registry._registry["validating_addon"] = addon

        stored = registry.parse_config(addon, {"api_key": "parsed", "label": "x"})
        assert stored["api_key"] == "parsed"
        assert not getattr(addon, "_config", None)
