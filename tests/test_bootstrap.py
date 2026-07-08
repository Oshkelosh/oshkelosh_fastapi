"""Tests for first-admin bootstrap and /setup flow."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlmodel import col

from app.db.connection import get_session
from app.main import app
from app.services.bootstrap import has_admin_user
from models.user import User

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _teardown_app_state():
    app.dependency_overrides.clear()
    app.state.needs_setup = False


@pytest.mark.asyncio
async def test_root_redirects_to_setup_when_no_admin(db_session):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", follow_redirects=False)
    _teardown_app_state()
    assert response.status_code == 307
    assert response.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_admin_login_redirects_to_setup_when_no_admin(db_session):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/login", follow_redirects=False)
    _teardown_app_state()
    assert response.status_code == 307
    assert response.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_health_not_redirected_when_no_admin(db_session):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health", follow_redirects=False)
    _teardown_app_state()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_setup_get_renders_form(db_session):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/setup")
    _teardown_app_state()
    assert response.status_code == 200
    assert "Create your administrator account" in response.text


@pytest.mark.asyncio
async def test_setup_post_creates_admin_and_redirects(db_session):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        form = await _setup_form_data(
            client,
            email="bootstrap@example.com",
            password="SecurePass123!",
            password_confirm="SecurePass123!",
            full_name="Bootstrap Admin",
        )
        response = await client.post(
            "/setup",
            data=form,
            follow_redirects=False,
        )
    _teardown_app_state()
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/dashboard"
    assert "oshkelosh_admin" in response.cookies

    result = await db_session.execute(
        select(User).where(col(User.email) == "bootstrap@example.com")
    )
    user = result.scalar_one()
    assert user.is_admin is True


@pytest.mark.asyncio
async def test_setup_post_rejected_when_admin_exists(db_session, test_user):
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.state.needs_setup = False
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        form = await _setup_form_data(
            client,
            email="other@example.com",
            password="SecurePass123!",
            password_confirm="SecurePass123!",
        )
        response = await client.post(
            "/setup",
            data=form,
            follow_redirects=False,
        )
    _teardown_app_state()
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/login"


def _session_override(db_session):
    async def override_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    return override_session


async def _setup_form_data(client: AsyncClient, **fields: str) -> dict[str, str]:
    """Fetch setup CSRF cookie and build POST form data."""
    await client.get("/setup")
    csrf = client.cookies.get("_oshkelosh_setup_csrf", "")
    return {"csrf_token": csrf, **fields}


@pytest.mark.asyncio
async def test_has_admin_user_false_on_empty_db(db_session):
    assert await has_admin_user(db_session) is False


@pytest.mark.asyncio
async def test_has_admin_user_true_with_admin(db_session, test_user):
    assert await has_admin_user(db_session) is True


def test_create_admin_cli_idempotent(tmp_path, monkeypatch):
    """CLI exits 0 when admin already exists (uses isolated sqlite file)."""
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")

    from app.config import reload_settings
    from app.db.connection import reset_session_factory

    reload_settings()
    reset_session_factory()

    env = {
        **os.environ,
        "DEPLOYMENT_PROFILE": "local",
        "PYTHONPATH": str(PROJECT_ROOT),
    }
    result1 = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "create_admin.py"),
            "--email",
            "cli@example.com",
            "--password",
            "SecurePass123!",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result1.returncode == 0, result1.stderr

    result2 = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "create_admin.py"),
            "--email",
            "cli2@example.com",
            "--password",
            "SecurePass123!",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0
    assert "already exists" in result2.stdout

    reload_settings()
    reset_session_factory()
