"""Tests for SPA fallback routing (unknown paths serve index.html)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestSpaFallback:
    @pytest.mark.parametrize(
        "path",
        ["/account", "/account/orders/42", "/login", "/cart"],
    )
    async def test_client_side_routes_serve_spa_shell(
        self, client: AsyncClient, path: str
    ):
        response = await client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    async def test_missing_asset_still_404s(self, client: AsyncClient):
        response = await client.get("/assets/missing.js")
        assert response.status_code == 404

    async def test_missing_root_level_file_still_404s(self, client: AsyncClient):
        response = await client.get("/logo.png")
        assert response.status_code == 404


class TestAdminNoTrailingSlash:
    async def test_admin_without_slash_redirects_to_admin(self, client: AsyncClient):
        response = await client.get("/admin", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/admin/"

    async def test_admin_without_slash_reaches_login(self, client: AsyncClient):
        response = await client.get("/admin", follow_redirects=True)
        assert response.status_code == 200
        assert str(response.url).endswith("/admin/login")
