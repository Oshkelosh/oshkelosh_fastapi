"""Tests for background job orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
