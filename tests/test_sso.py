"""Tests for SSO account linking and HTTP integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.addons.registry import addon_registry
from app.addons.tools.sso.addon import SsoToolAddon
from app.addons.tools.sso.service import (
    create_sso_exchange_token,
    create_sso_state_token,
    decode_sso_exchange_token,
    generate_pkce_pair,
    handle_oauth_callback,
)
from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.services.addons import persist_addon_config
from app.services.sso_accounts import SsoProfile, find_or_create_sso_user
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


@pytest.fixture
async def enabled_sso(db_session):
    if addon_registry.get("sso") is None:
        addon_registry.register(SsoToolAddon)
    await persist_addon_config(db_session, "sso", GOOGLE_CONFIG, enabled=True)
    yield addon_registry.get("sso")
    await addon_registry.disable_async("sso")


class TestSsoAccounts:
    @pytest.mark.asyncio
    async def test_create_verified_sso_user(self, db_session):
        profile = SsoProfile(
            provider="google",
            subject="google-sub-1",
            email="sso-new@example.com",
            email_verified=True,
            full_name="SSO User",
        )
        user = await find_or_create_sso_user(db_session, profile)
        assert user.email == "sso-new@example.com"
        assert user.verified is True
        assert user.verified_at is not None
        assert user.password_hash is None
        assert user.oauth_identities == {"google": "google-sub-1"}

    @pytest.mark.asyncio
    async def test_auto_link_existing_email(self, db_session):
        existing = User(
            email="existing@example.com",
            password_hash=hash_password("SecurePass123!"),
            verified=False,
        )
        db_session.add(existing)
        await db_session.flush()

        profile = SsoProfile(
            provider="google",
            subject="google-sub-2",
            email="existing@example.com",
            email_verified=True,
            full_name="Linked User",
        )
        user = await find_or_create_sso_user(db_session, profile)
        assert user.id == existing.id
        assert user.verified is True
        assert user.oauth_identities == {"google": "google-sub-2"}

    @pytest.mark.asyncio
    async def test_banned_user_rejected(self, db_session):
        banned = User(
            email="banned@example.com",
            password_hash=hash_password("SecurePass123!"),
            banned=True,
            verified=True,
        )
        db_session.add(banned)
        await db_session.flush()

        profile = SsoProfile(
            provider="google",
            subject="google-sub-3",
            email="banned@example.com",
            email_verified=True,
        )
        with pytest.raises(AuthenticationError, match="banned"):
            await find_or_create_sso_user(db_session, profile)


class TestSsoApi:
    @pytest.mark.asyncio
    async def test_providers_empty_when_disabled(self, client: AsyncClient):
        resp = await client.get("/api/v1/tools/sso/providers")
        assert resp.status_code == 200
        assert resp.json()["providers"] == []

    @pytest.mark.asyncio
    async def test_providers_list_when_enabled(self, client: AsyncClient, enabled_sso):
        resp = await client.get("/api/v1/tools/sso/providers")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        assert len(providers) == 1
        assert providers[0]["id"] == "google"
        assert providers[0]["label"] == "Google"
        assert "/api/v1/tools/sso/google/authorize" in providers[0]["authorize_url"]

    @pytest.mark.asyncio
    async def test_sso_discovery_returns_providers(self, enabled_sso):
        from app.services.sso_discovery import get_public_sso_providers

        providers = get_public_sso_providers()
        assert len(providers) == 1
        assert providers[0]["id"] == "google"

    @pytest.mark.asyncio
    async def test_exchange_returns_tokens(self, client: AsyncClient, db_session, enabled_sso):
        user = User(
            email="exchange@example.com",
            password_hash=None,
            verified=True,
            oauth_identities={"google": "sub-x"},
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)

        token = create_sso_exchange_token(user.id)
        resp = await client.post(
            "/api/v1/tools/sso/exchange",
            json={"exchange_token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["refresh_token"]

    @pytest.mark.asyncio
    async def test_oauth_callback_creates_user(self, client: AsyncClient, db_session, enabled_sso):
        addon = enabled_sso
        verifier, _ = generate_pkce_pair()
        state = create_sso_state_token("google", "/orders", verifier)

        mock_profile = SsoProfile(
            provider="google",
            subject="callback-sub",
            email="callback@example.com",
            email_verified=True,
            full_name="Callback User",
        )

        with patch.object(
            addon.providers["google"],
            "exchange_code",
            new=AsyncMock(return_value=mock_profile),
        ):
            user_id, redirect_after = await handle_oauth_callback(
                db_session,
                addon.providers,
                "google",
                "auth-code",
                state,
            )

        assert redirect_after == "/orders"
        user = await db_session.get(User, user_id)
        assert user is not None
        assert user.email == "callback@example.com"
        assert user.verified is True
        assert decode_sso_exchange_token(create_sso_exchange_token(user_id)) == user_id
