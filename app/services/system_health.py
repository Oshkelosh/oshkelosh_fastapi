"""System and store health checks for admin dashboard and probes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import settings

CheckStatus = Literal["ok", "warning", "error"]
OverallStatus = Literal["healthy", "degraded", "unhealthy"]


@dataclass
class HealthCheck:
    id: str
    label: str
    status: CheckStatus
    detail: str = ""


@dataclass
class HealthSummary:
    overall: OverallStatus
    checks: list[HealthCheck] = field(default_factory=list)


@dataclass
class IntegrationSummary:
    payment_name: str | None = None
    frontend_name: str | None = None
    notification_channels: list[str] = field(default_factory=list)
    enabled_supplier_count: int = 0
    syncable_supplier_count: int = 0


async def run_infrastructure_checks() -> tuple[dict[str, str], bool]:
    """Run database and storage readiness checks. Returns (checks dict, ok bool)."""
    from sqlalchemy import text

    from app.db.connection import session_scope
    from app.storage import get_storage

    checks: dict[str, str] = {}
    ok = True

    try:
        async with session_scope() as session:
            if hasattr(session, "execute_raw"):
                await session.execute_raw("SELECT 1")
            else:
                await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ok = False

    try:
        storage = get_storage()
        if settings.storage_backend == "local":
            path = settings.local_media_path
            path.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                raise OSError(f"media path missing: {path}")
        elif hasattr(storage, "bucket_name"):
            checks["storage"] = "ok"
        else:
            checks["storage"] = "ok"
        if "storage" not in checks:
            checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"error: {exc}"
        ok = False

    return checks, ok


def _check_from_infra(key: str, label: str, value: str) -> HealthCheck:
    if value == "ok":
        return HealthCheck(id=key, label=label, status="ok", detail="Reachable")
    return HealthCheck(id=key, label=label, status="error", detail=value.removeprefix("error: "))


async def run_store_health_checks(session: Any | None = None) -> list[HealthCheck]:
    """Operational readiness checks (warnings when integrations are missing)."""
    from app.services.addons import (
        get_frontend_addon,
        get_notification_addon_for_channel,
        get_payment_addon,
        get_enabled,
    )

    checks: list[HealthCheck] = []

    payment = get_payment_addon()
    if payment:
        checks.append(
            HealthCheck(
                id="payment",
                label="Payment processor",
                status="ok",
                detail=payment.addon_name,
            )
        )
        if session is not None:
            from app.services.site_settings import (
                get_site_settings,
                is_dev_fallback_site_url,
                resolve_public_site_url,
            )

            site = await get_site_settings(session)
            resolved = resolve_public_site_url(site_settings=site)
            if is_dev_fallback_site_url(resolved):
                checks.append(
                    HealthCheck(
                        id="site_url",
                        label="Site URL",
                        status="warning",
                        detail=(
                            "Set PUBLIC_APP_URL in the environment for payment checkout redirects"
                        ),
                    )
                )
    else:
        checks.append(
            HealthCheck(
                id="payment",
                label="Payment processor",
                status="warning",
                detail="No payment processor enabled",
            )
        )

    frontend = get_frontend_addon()
    if frontend:
        checks.append(
            HealthCheck(
                id="frontend",
                label="Storefront frontend",
                status="ok",
                detail=frontend.addon_name,
            )
        )
    else:
        checks.append(
            HealthCheck(
                id="frontend",
                label="Storefront frontend",
                status="warning",
                detail="No storefront frontend enabled",
            )
        )

    email = get_notification_addon_for_channel("email")
    if email:
        checks.append(
            HealthCheck(
                id="email_notifications",
                label="Email notifications",
                status="ok",
                detail=email.addon_name,
            )
        )
    else:
        checks.append(
            HealthCheck(
                id="email_notifications",
                label="Email notifications",
                status="warning",
                detail="No email notification provider enabled",
            )
        )

    enabled_suppliers = [
        a for a in get_enabled("supplier") if a.addon_id != "manual"
    ]
    if enabled_suppliers:
        names = ", ".join(a.addon_name for a in enabled_suppliers)
        checks.append(
            HealthCheck(
                id="suppliers",
                label="Suppliers",
                status="ok",
                detail=names,
            )
        )
    else:
        checks.append(
            HealthCheck(
                id="suppliers",
                label="Suppliers",
                status="warning",
                detail="No supplier integrations enabled",
            )
        )

    return checks


def _compute_overall(infra_ok: bool, store_checks: list[HealthCheck]) -> OverallStatus:
    if not infra_ok:
        return "unhealthy"
    if any(c.status == "warning" for c in store_checks):
        return "degraded"
    return "healthy"


async def build_health_summary(session: Any | None = None) -> HealthSummary:
    """Build combined infrastructure + store health summary."""
    infra_raw, infra_ok = await run_infrastructure_checks()
    checks: list[HealthCheck] = [
        _check_from_infra("database", "Database", infra_raw.get("database", "error: unknown")),
        _check_from_infra("storage", "Storage", infra_raw.get("storage", "error: unknown")),
    ]
    store_checks = await run_store_health_checks(session)
    checks.extend(store_checks)
    return HealthSummary(overall=_compute_overall(infra_ok, store_checks), checks=checks)


async def build_integration_summary() -> IntegrationSummary:
    """Compact integration status for dashboard display."""
    from app.services.addons import (
        get_frontend_addon,
        get_notification_addon_for_channel,
        get_payment_addon,
        get_enabled,
    )
    from app.services.supplier_catalog_sync import list_syncable_suppliers

    payment = get_payment_addon()
    frontend = get_frontend_addon()
    channels: list[str] = []
    for channel in ("email", "sms", "push"):
        if get_notification_addon_for_channel(channel):
            channels.append(channel)

    enabled_suppliers = [
        a for a in get_enabled("supplier") if a.addon_id != "manual"
    ]
    syncable = list_syncable_suppliers()

    return IntegrationSummary(
        payment_name=payment.addon_name if payment else None,
        frontend_name=frontend.addon_name if frontend else None,
        notification_channels=channels,
        enabled_supplier_count=len(enabled_suppliers),
        syncable_supplier_count=len(syncable),
    )
