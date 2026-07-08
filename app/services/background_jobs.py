"""DB-backed background jobs for admin operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlmodel import col

from app.core.exceptions import NotFound, ValidationError
from app.db.connection import mark_instance_dirty
from app.services.supplier_catalog_sync import (
    SupplierCatalogSyncOptions,
    SupplierCatalogSyncResult,
    list_syncable_suppliers,
    sync_supplier_catalog,
)
from models.background_job import BackgroundJob

JOB_TYPE_SUPPLIER_CATALOG_SYNC = "supplier_catalog_sync"


@dataclass
class SupplierCatalogSyncJobOptions:
    import_status: str = "draft"
    archive_missing: bool = False
    addon_ids: list[str] | None = None
    actor_user_id: int | None = None
    ip_address: str | None = None


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _sync_result_from_dict(data: dict[str, Any] | None) -> SupplierCatalogSyncResult:
    if not data:
        return SupplierCatalogSyncResult()
    return SupplierCatalogSyncResult(
        created=int(data.get("created", 0)),
        updated=int(data.get("updated", 0)),
        skipped=int(data.get("skipped", 0)),
        archived=int(data.get("archived", 0)),
        errors=list(data.get("errors") or []),
    )


def _resolve_addon_ids(payload: dict[str, Any]) -> list[str]:
    requested = payload.get("addon_ids")
    syncable = [a.addon_id for a in list_syncable_suppliers()]
    if not syncable:
        return []
    if not requested:
        return syncable
    allowed = set(syncable)
    return [addon_id for addon_id in requested if addon_id in allowed]


async def start_supplier_catalog_sync_job(
    session: Any,
    options: SupplierCatalogSyncJobOptions,
) -> BackgroundJob:
    """Create a pending supplier catalog sync job."""
    if options.import_status not in ("draft", "published"):
        raise ValidationError(message="import_status must be 'draft' or 'published'")

    addon_ids = _resolve_addon_ids(
        {
            "addon_ids": options.addon_ids,
        }
    )
    if not addon_ids:
        raise ValidationError(message="No syncable supplier addons are enabled")

    job_id = str(uuid.uuid4())
    now = _utc_now()
    job = BackgroundJob(
        id=job_id,
        job_type=JOB_TYPE_SUPPLIER_CATALOG_SYNC,
        status="pending",
        payload={
            "import_status": options.import_status,
            "archive_missing": options.archive_missing,
            "addon_ids": addon_ids,
            "actor_user_id": options.actor_user_id,
            "ip_address": options.ip_address,
        },
        progress={
            "total": len(addon_ids),
            "done": 0,
            "current_addon_id": None,
            "addon_ids": addon_ids,
            "results": {},
        },
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: Any, job_id: str) -> BackgroundJob:
    """Load a background job by id."""
    result = await session.execute(
        select(BackgroundJob).where(col(BackgroundJob.id) == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise NotFound(message=f"Job not found: {job_id}")
    return job


async def get_active_supplier_sync_job(session: Any) -> BackgroundJob | None:
    """Return the most recent running/pending supplier sync job, if any."""
    result = await session.execute(
        select(BackgroundJob)
        .where(col(BackgroundJob.job_type) == JOB_TYPE_SUPPLIER_CATALOG_SYNC)
        .where(col(BackgroundJob.status).in_(("pending", "running")))
        .order_by(col(BackgroundJob.created_at).desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def tick_supplier_catalog_sync_job(session: Any, job_id: str) -> BackgroundJob:
    """Process the next supplier in a catalog sync job."""
    job = await get_job(session, job_id)
    if job.job_type != JOB_TYPE_SUPPLIER_CATALOG_SYNC:
        raise ValidationError(message=f"Unsupported job type: {job.job_type}")
    if job.status in ("completed", "failed"):
        return job

    payload = job.payload or {}
    progress = dict(job.progress or {})
    addon_ids: list[str] = list(progress.get("addon_ids") or payload.get("addon_ids") or [])
    results: dict[str, Any] = dict(progress.get("results") or {})
    done = int(progress.get("done", 0))

    if job.status == "pending":
        job.status = "running"

    pending_ids = [addon_id for addon_id in addon_ids if addon_id not in results]
    if not pending_ids:
        job.status = "completed"
        progress["done"] = len(addon_ids)
        progress["current_addon_id"] = None
        job.progress = progress
        job.updated_at = _utc_now()
        mark_instance_dirty(session, job)
        await session.commit()
        return job

    addon_id = pending_ids[0]
    progress["current_addon_id"] = addon_id
    job.progress = progress
    job.updated_at = _utc_now()
    mark_instance_dirty(session, job)
    await session.flush()

    sync_options = SupplierCatalogSyncOptions(
        import_status=str(payload.get("import_status", "draft")),
        archive_missing=bool(payload.get("archive_missing")),
    )
    try:
        result = await sync_supplier_catalog(
            session,
            addon_id,
            sync_options,
            actor_user_id=payload.get("actor_user_id"),
            ip_address=payload.get("ip_address"),
        )
        results[addon_id] = result.to_dict()
    except Exception as exc:
        failed = SupplierCatalogSyncResult(errors=[str(exc)])
        results[addon_id] = failed.to_dict()

    done += 1
    progress["results"] = results
    progress["done"] = done
    progress["current_addon_id"] = None
    job.progress = progress
    job.updated_at = _utc_now()

    if done >= len(addon_ids):
        job.status = "completed"
        if all(_sync_result_from_dict(results.get(aid)).errors for aid in addon_ids):
            job.status = "failed"
            job.error = "All supplier syncs failed"

    mark_instance_dirty(session, job)
    await session.commit()
    return job


async def run_supplier_catalog_sync_job_to_completion(
    session: Any,
    job_id: str,
    *,
    max_ticks: int = 50,
) -> BackgroundJob:
    """Run all ticks until the job completes (for cron/automation)."""
    for _ in range(max_ticks):
        job = await get_job(session, job_id)
        if job.status in ("completed", "failed"):
            return job
        job = await tick_supplier_catalog_sync_job(session, job_id)
        if job.status in ("completed", "failed"):
            return job
    return await get_job(session, job_id)


def job_progress_percent(job: BackgroundJob) -> int:
    """Return completion percentage for a job."""
    progress = job.progress or {}
    total = int(progress.get("total", 0))
    if total <= 0:
        return 0
    done = int(progress.get("done", 0))
    return min(100, int((done / total) * 100))


def addon_display_name(addon_id: str) -> str:
    from app.addons.registry import addon_registry

    addon = addon_registry.get(addon_id)
    return addon.addon_name if addon else addon_id
