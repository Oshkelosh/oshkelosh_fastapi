"""Tests for auth refresh, admin login, and production config validation."""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

from app.config import Settings, validate_backends
from app.core.security import create_refresh_token, hash_password
from models.user import User


async def _login_csrf_token(client: AsyncClient) -> str:
    """Fetch the admin login page and extract the CSRF form token."""
    page = await client.get("/admin/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match is not None
    return match.group(1)


@pytest.mark.asyncio
async def test_auth_refresh_returns_new_tokens(client: AsyncClient, test_user):
    refresh = create_refresh_token(test_user.id)
    response = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_auth_refresh_rejects_banned_user(client: AsyncClient, db_session, test_user):
    test_user.banned = True
    db_session.add(test_user)
    await db_session.flush()

    refresh = create_refresh_token(test_user.id)
    response = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_success(client: AsyncClient, test_user):
    csrf = await _login_csrf_token(client)
    response = await client.post(
        "/admin/login",
        data={"email": test_user.email, "password": "SecurePass123!", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "oshkelosh_admin" in response.cookies


@pytest.mark.asyncio
async def test_admin_login_rejects_non_admin(client: AsyncClient, db_session):
    user = User(
        email="shopper@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_admin=False,
        verified=True,
        banned=False,
    )
    db_session.add(user)
    await db_session.flush()

    csrf = await _login_csrf_token(client)
    response = await client.post(
        "/admin/login",
        data={"email": user.email, "password": "SecurePass123!", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 200


def test_validate_backends_rejects_default_jwt_in_production():
    cfg = Settings(app_env="production")
    with pytest.raises(ValueError):
        validate_backends(cfg)
