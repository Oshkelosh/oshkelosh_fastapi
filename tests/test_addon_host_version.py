"""Tests for addon host version compatibility."""

from __future__ import annotations

import pytest

from app.addons.base import AddonConfig, BaseAddon
from app.addons.registry import AddonRegistry
from app.core.exceptions import ValidationError


class _FutureAddon(BaseAddon):
    addon_id = "future_addon"
    addon_name = "Future"
    addon_category = "tool"
    version = "1.0.0"
    min_host_version = "99.0.0"

    @classmethod
    def config_schema(cls):
        class _Cfg(AddonConfig):
            pass

        return _Cfg

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_enable_async_rejects_incompatible_host(monkeypatch):
    registry = AddonRegistry()
    registry.register(_FutureAddon)
    monkeypatch.setattr(
        "app.addons.registry.settings.app_version",
        "0.1.0",
    )
    with pytest.raises(ValidationError, match="requires Oshkelosh 99.0.0"):
        await registry.enable_async("future_addon", {})
