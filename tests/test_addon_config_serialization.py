"""Tests for addon config serialization (SecretStr preservation)."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr

from app.addons.config_serialization import dump_addon_config
from app.addons.registry import AddonRegistry
from app.addons.suppliers.printful.addon import PrintfulAddon, PrintfulConfig
from app.addons.tools.sso.config import SsoConfig


class _SecretConfig(BaseModel):
    api_key: SecretStr = Field(default=...)
    label: str = "test"


def test_dump_addon_config_preserves_secret_str():
    token = "smk_real_printful_token_12345"
    dumped = dump_addon_config(_SecretConfig(api_key=token))
    assert dumped["api_key"] == token
    assert dumped["api_key"] != "**********"


def test_dump_addon_config_preserves_nested_secret_str():
    dumped = dump_addon_config(
        SsoConfig(
            google={
                "enabled": True,
                "client_id": "google-client",
                "client_secret": "google-secret",
            }
        )
    )
    assert dumped["google"]["client_secret"] == "google-secret"


def test_registry_validate_and_store_config_preserves_printful_api_key():
    registry = AddonRegistry()
    addon = PrintfulAddon()
    registry._registry["printful"] = addon
    token = "pf-live-token-abc"

    stored = registry._validate_and_store_config(
        addon,
        {"api_key": token, "is_active": True, "auto_confirm": True},
    )

    assert stored["api_key"] == token
    assert registry.get_config("printful")["api_key"] == token


def test_printful_config_model_dump_json_masks_but_dump_addon_config_does_not():
    token = "pf-live-token-abc"
    model = PrintfulConfig(api_key=token, is_active=True)
    assert model.model_dump(mode="json")["api_key"] == "**********"
    assert dump_addon_config(model)["api_key"] == token
