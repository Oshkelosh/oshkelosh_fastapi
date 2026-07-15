"""Unit tests for SSO service helpers."""

import pytest

from app.addons.tools.sso.addon import SsoToolAddon
from app.addons.tools.sso.service import (
    build_authorize_url,
    create_sso_exchange_token,
    decode_sso_exchange_token,
    generate_pkce_pair,
)
from models.user import User

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


class TestSsoService:
    def test_generate_pkce_pair(self):
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) > 0
        assert len(challenge) > 0

    def test_exchange_token_roundtrip(self):
        token = create_sso_exchange_token(42)
        assert decode_sso_exchange_token(token) == 42

    @pytest.mark.asyncio
    async def test_build_authorize_url_contains_pkce_params(self):
        addon = SsoToolAddon()
        await addon.initialize(GOOGLE_CONFIG)
        url = build_authorize_url(addon.providers, "google", "/")
        assert "accounts.google.com" in url
        assert "code_challenge=" in url
        assert "state=" in url

    def test_exchange_token_for_user(self):
        user = User(id=99, email="u@example.com", password_hash=None, verified=True)
        token = create_sso_exchange_token(user.id)
        assert decode_sso_exchange_token(token) == 99
