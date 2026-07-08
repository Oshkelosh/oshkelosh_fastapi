"""Tests for admin dashboard and supplier global actions."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.services.audit import log_change


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


@pytest.mark.asyncio
async def test_dashboard_renders_system_health(client: AsyncClient, test_user):
    cookies, _csrf = _admin_session(test_user.id)
    with patch(
        "app.services.system_health.build_health_summary",
        AsyncMock(
            return_value=MagicMock(
                overall="degraded",
                checks=[
                    MagicMock(id="database", label="Database", status="ok", detail="Reachable"),
                ],
            )
        ),
    ):
        response = await client.get("/admin/dashboard", cookies=cookies)

    assert response.status_code == 200
    assert "System health" in response.text
    assert "Degraded" in response.text


@pytest.mark.asyncio
async def test_suppliers_sync_all_starts_job_and_redirects(
    client: AsyncClient, test_user, db_session
):
    cookies, csrf = _admin_session(test_user.id)
    mock_addon = MagicMock()
    mock_addon.addon_id = "printful"
    mock_addon.addon_name = "Printful"
    mock_addon.supports_catalog_sync = MagicMock(return_value=True)

    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=[mock_addon]):
        with patch(
            "app.services.background_jobs.get_active_supplier_sync_job",
            AsyncMock(return_value=None),
        ):
            response = await client.post(
                "/admin/suppliers/sync-all",
                cookies=cookies,
                data={
                    "csrf_token": csrf,
                    "import_status": "draft",
                },
                follow_redirects=False,
            )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/jobs/")


@pytest.mark.asyncio
async def test_admin_health_api(client: AsyncClient, test_user):
    from tests.test_supplier_catalog_sync import _auth_headers

    headers = await _auth_headers(client, test_user.email, "SecurePass123!")
    with patch(
        "app.services.system_health.build_health_summary",
        AsyncMock(
            return_value=MagicMock(
                overall="healthy",
                checks=[MagicMock(id="database", label="Database", status="ok", detail="Reachable")],
            )
        ),
    ):
        response = await client.get("/api/v1/admin/health", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "healthy"
    assert body["checks"][0]["id"] == "database"


@pytest.mark.asyncio
async def test_get_last_sync_times_from_audit(db_session):
    from app.services.supplier_catalog_sync import get_last_sync_times

    await log_change(
        db_session,
        actor_user_id=1,
        action="supplier_catalog_sync",
        resource_type="supplier",
        resource_id="printful",
        detail="synced",
    )
    await db_session.commit()

    times = await get_last_sync_times(db_session)
    assert "printful" in times
    assert isinstance(times["printful"], datetime)


@pytest.mark.asyncio
async def test_list_syncable_suppliers_excludes_manual():
    from app.services.supplier_catalog_sync import list_syncable_suppliers

    manual = MagicMock()
    manual.addon_id = "manual"
    manual.supports_catalog_sync = MagicMock(return_value=False)
    printful = MagicMock()
    printful.addon_id = "printful"
    printful.supports_catalog_sync = MagicMock(return_value=True)

    with patch("app.services.supplier_catalog_sync.get_enabled", return_value=[manual, printful]):
        syncable = list_syncable_suppliers()

    assert len(syncable) == 1
    assert syncable[0].addon_id == "printful"
