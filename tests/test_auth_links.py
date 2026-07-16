"""Tests for storefront auth email deep-link handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.services.user_accounts import (
    issue_email_verification,
    issue_password_reset,
)
from models.user import User


class TestVerifyEmailLink:
    @pytest.fixture(autouse=True)
    def _enable_verification(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.require_email_verification", True)

    async def test_valid_token_redirects_and_verifies(
        self, client: AsyncClient, db_session
    ):
        user = User(
            email="link-verify@example.com",
            password_hash=hash_password("SecurePass123!"),
            verified=False,
        )
        token = issue_email_verification(user)
        db_session.add(user)
        await db_session.commit()

        response = await client.get(
            f"/verify-email?token={token}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login?auth=verified"

        await db_session.refresh(user)
        assert user.verified is True
        assert user.email_verification_token is None

    async def test_invalid_token_redirects_to_login(self, client: AsyncClient):
        response = await client.get(
            "/verify-email?token=not-a-real-token-at-all-xx",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login?auth=verify_failed&reason=invalid"

    async def test_missing_token_redirects_to_login(self, client: AsyncClient):
        response = await client.get("/verify-email", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login?auth=verify_failed&reason=missing"

    async def test_expired_token_redirects_to_login(
        self, client: AsyncClient, db_session
    ):
        user = User(
            email="link-expired@example.com",
            password_hash=hash_password("SecurePass123!"),
            verified=False,
            email_verification_token="expired-token-value-xxxx",
            email_verification_expires_at=datetime.now(timezone.utc)
            - timedelta(hours=1),
        )
        db_session.add(user)
        await db_session.commit()

        response = await client.get(
            "/verify-email?token=expired-token-value-xxxx",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login?auth=verify_failed&reason=invalid"


class TestResetPasswordLink:
    async def test_valid_token_serves_spa_and_keeps_token(
        self, client: AsyncClient, db_session
    ):
        user = User(
            email="link-reset@example.com",
            password_hash=hash_password("SecurePass123!"),
            verified=True,
        )
        token = issue_password_reset(user)
        db_session.add(user)
        await db_session.commit()

        response = await client.get(
            f"/reset-password?token={token}",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        await db_session.refresh(user)
        assert user.password_reset_token == token

        reset = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "NewSecure456!"},
        )
        assert reset.status_code == 200

    async def test_invalid_token_redirects_to_forgot_password(
        self, client: AsyncClient
    ):
        response = await client.get(
            "/reset-password?token=not-a-real-token-at-all-xx",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "/forgot-password?auth=reset_failed&reason=invalid"
        )

    async def test_missing_token_redirects_to_forgot_password(
        self, client: AsyncClient
    ):
        response = await client.get("/reset-password", follow_redirects=False)
        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "/forgot-password?auth=reset_failed&reason=missing"
        )
