"""Unit tests for the SSO tool addon."""

import pytest

from app.addons.tools.sso.addon import SsoToolAddon

GOOGLE_CONFIG = {
    "is_active": True,
    "google": {
        "enabled": True,
        "client_id": "google-client-id",
        "client_secret": "google-client-secret",
    },
    "facebook": {"enabled": False, "app_id": "", "app_secret": ""},
    "oidc_providers": [],
}


class TestSsoToolAddon:
    def test_sso_addon_has_required_attrs(self):
        assert SsoToolAddon.addon_id == "sso"
        assert SsoToolAddon.addon_category == "tool"

    @pytest.mark.asyncio
    async def test_initialize_registers_google_provider(self):
        addon = SsoToolAddon()
        await addon.initialize(GOOGLE_CONFIG)
        assert addon.is_enabled is True
        assert "google" in addon.providers
        assert addon.list_public_providers()[0]["id"] == "google"
