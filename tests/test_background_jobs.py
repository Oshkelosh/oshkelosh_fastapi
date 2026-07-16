"""Tests for background job orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.background_jobs import (
    SupplierCatalogSyncJobOptions,
    get_job,
    job_progress_percent,
    run_supplier_catalog_sync_job_to_completion,
    start_supplier_catalog_sync_job,
    tick_supplier_catalog_sync_job,
)
from app.services.supplier_catalog_sync import SupplierCatalogSyncResult


def _mock_syncable(addon_id: str, name: str) -> MagicMock:
    addon = MagicMock()
    addon.addon_id = addon_id
    addon.addon_name = name
    addon.supports_catalog_sync = MagicMock(return_value=True)
    return addon


@pytest.mark.asyncio
async def test_start_job_requires_syncable_suppliers(db_session):
    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=[]):
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="No syncable"):
            await start_supplier_catalog_sync_job(
                db_session,
                SupplierCatalogSyncJobOptions(),
            )


@pytest.mark.asyncio
async def test_tick_job_processes_suppliers_incrementally(db_session):
    syncable = [_mock_syncable("alpha", "Alpha"), _mock_syncable("beta", "Beta")]
    result_alpha = SupplierCatalogSyncResult(created=1)
    result_beta = SupplierCatalogSyncResult(updated=2)

    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=syncable):
        job = await start_supplier_catalog_sync_job(
            db_session,
            SupplierCatalogSyncJobOptions(import_status="draft"),
        )
        await db_session.commit()

    with patch(
        "app.services.background_jobs.sync_supplier_catalog",
        AsyncMock(side_effect=[result_alpha, result_beta]),
    ):
        job = await tick_supplier_catalog_sync_job(db_session, job.id)
        assert job.status == "running"
        assert job.progress["done"] == 1
        assert "alpha" in job.progress["results"]

        job = await tick_supplier_catalog_sync_job(db_session, job.id)
        assert job.status == "completed"
        assert job.progress["done"] == 2
        assert job.progress["results"]["beta"]["updated"] == 2


@pytest.mark.asyncio
async def test_run_job_to_completion(db_session):
    syncable = [_mock_syncable("only", "Only")]
    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=syncable):
        job = await start_supplier_catalog_sync_job(db_session, SupplierCatalogSyncJobOptions())
        await db_session.commit()

    with patch(
        "app.services.background_jobs.sync_supplier_catalog",
        AsyncMock(return_value=SupplierCatalogSyncResult(created=3)),
    ):
        job = await run_supplier_catalog_sync_job_to_completion(db_session, job.id)

    assert job.status == "completed"
    assert job_progress_percent(job) == 100


@pytest.mark.asyncio
async def test_get_job_not_found(db_session):
    from app.core.exceptions import NotFound

    with pytest.raises(NotFound):
        await get_job(db_session, "missing-id")


@pytest.mark.asyncio
async def test_start_job_rejects_when_already_running(db_session):
    from app.core.exceptions import ValidationError

    syncable = [_mock_syncable("only", "Only")]
    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=syncable):
        job = await start_supplier_catalog_sync_job(
            db_session,
            SupplierCatalogSyncJobOptions(),
        )
        await db_session.commit()

        with pytest.raises(ValidationError, match="already running") as exc_info:
            await start_supplier_catalog_sync_job(
                db_session,
                SupplierCatalogSyncJobOptions(),
            )

    assert exc_info.value.details == {"job_id": job.id}


@pytest.mark.asyncio
async def test_sync_supplier_catalog_rejects_when_job_running(db_session):
    from app.core.exceptions import ValidationError
    from app.services.supplier_catalog_sync import (
        SupplierCatalogSyncOptions,
        sync_supplier_catalog,
    )

    syncable = [_mock_syncable("only", "Only")]
    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=syncable):
        job = await start_supplier_catalog_sync_job(
            db_session,
            SupplierCatalogSyncJobOptions(),
        )
        await db_session.commit()

    with pytest.raises(ValidationError, match="already running") as exc_info:
        await sync_supplier_catalog(
            db_session,
            "only",
            SupplierCatalogSyncOptions(),
        )

    assert exc_info.value.details == {"job_id": job.id}


@pytest.mark.asyncio
async def test_sync_supplier_catalog_allows_matching_job_id(db_session, test_user):
    from app.services.supplier_catalog_sync import (
        SupplierCatalogSyncOptions,
        sync_supplier_catalog,
    )

    syncable = [_mock_syncable("only", "Only")]
    with patch("app.services.background_jobs.list_syncable_suppliers", return_value=syncable):
        job = await start_supplier_catalog_sync_job(
            db_session,
            SupplierCatalogSyncJobOptions(),
        )
        await db_session.commit()

    mock_addon = MagicMock()
    mock_addon.is_enabled = True
    mock_addon.supports_catalog_sync = MagicMock(return_value=True)
    mock_addon.fetch_catalog_for_import = AsyncMock(return_value=[])

    with patch(
        "app.services.supplier_catalog_sync.get_supplier_addon",
        return_value=mock_addon,
    ):
        result = await sync_supplier_catalog(
            db_session,
            "only",
            SupplierCatalogSyncOptions(),
            actor_user_id=test_user.id,
            for_job_id=job.id,
        )

    assert result.errors == []
    assert result.created == 0


async def _auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_pending_order_cleanup_job_requires_admin_auth(client: AsyncClient):
    response = await client.post("/api/v1/admin/jobs/pending-orders")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_abandoned_cart_job_runs_with_admin_jwt(client: AsyncClient, test_user):
    headers = await _auth_headers(client, test_user.email, "SecurePass123!")
    fake_result = MagicMock(scanned=3, sent=2, skipped=1)
    fake_result.summary_message.return_value = "Scanned 3; sent 2; skipped 1."

    with patch(
        "app.services.abandoned_cart.process_abandoned_carts",
        AsyncMock(return_value=fake_result),
    ):
        response = await client.post(
            "/api/v1/admin/jobs/abandoned-cart",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "scanned": 3,
        "sent": 2,
        "skipped": 1,
        "message": "Scanned 3; sent 2; skipped 1.",
    }


@pytest.mark.asyncio
async def test_pending_order_cleanup_job_runs_with_admin_jwt(client: AsyncClient, test_user):
    headers = await _auth_headers(client, test_user.email, "SecurePass123!")
    fake_result = MagicMock(scanned=4, cancelled=3, skipped=1)
    fake_result.summary_message.return_value = "Scanned 4 stale pending order(s); cancelled 3; skipped 1."

    with patch(
        "app.services.pending_order_cleanup.process_stale_pending_orders",
        AsyncMock(return_value=fake_result),
    ):
        response = await client.post(
            "/api/v1/admin/jobs/pending-orders",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "scanned": 4,
        "cancelled": 3,
        "skipped": 1,
        "message": "Scanned 4 stale pending order(s); cancelled 3; skipped 1.",
    }
