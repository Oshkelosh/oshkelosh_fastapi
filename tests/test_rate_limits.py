"""Rate limiting on auth endpoints."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.connection import get_session
from app.main import app


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429(db_session, monkeypatch):
    from app.config import settings
    from app.core.rate_limit import limiter

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    limiter.enabled = True
    # Decorator uses settings.rate_limit_login at import (default 5/minute).
    attempts = 6

    async def override_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"email": "nobody@example.com", "password": "wrong"}
            for _ in range(attempts - 1):
                r = await client.post("/api/v1/auth/login", json=payload)
                assert r.status_code in (401, 422)
            r = await client.post("/api/v1/auth/login", json=payload)
            assert r.status_code == 429
            body = r.json()
            assert body.get("error") == "rate_limit_exceeded"
    finally:
        app.dependency_overrides.clear()
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        limiter.enabled = False
