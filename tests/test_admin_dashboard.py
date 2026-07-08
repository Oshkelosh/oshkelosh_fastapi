"""Tests for admin dashboard and supplier global actions."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.services.audit import log_change
from models.order import Order


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
async def test_fetch_revenue_trend_zero_fills_and_excludes_statuses(db_session, test_user):
    from app.services.admin_dashboard import fetch_revenue_trend

    anchor = date(2026, 7, 8)
    db_session.add_all(
        [
            Order(
                user_id=test_user.id,
                status="paid",
                total_cents=1200,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
                created_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            ),
            Order(
                user_id=test_user.id,
                status="shipped",
                total_cents=800,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
                created_at=datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
            ),
            Order(
                user_id=test_user.id,
                status="pending",
                total_cents=5000,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
                created_at=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc),
            ),
            Order(
                user_id=test_user.id,
                status="cancelled",
                total_cents=9000,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
                created_at=datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc),
            ),
            Order(
                user_id=test_user.id,
                status="delivered",
                total_cents=700,
                tax_cents=0,
                shipping_cents=0,
                currency="usd",
                created_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    await db_session.commit()

    trend = await fetch_revenue_trend(db_session, days=5, anchor=anchor)

    assert len(trend["days"]) == 5
    assert [point["date"] for point in trend["days"]] == [
        (anchor - timedelta(days=offset)).isoformat() for offset in range(4, -1, -1)
    ]
    assert [point["revenue_cents"] for point in trend["days"]] == [0, 0, 800, 0, 1200]
    assert trend["max_cents"] == 1200
    assert trend["total_cents"] == 2000


@pytest.mark.asyncio
async def test_dashboard_renders_revenue_trend(client: AsyncClient, test_user, db_session):
    cookies, _csrf = _admin_session(test_user.id)
    db_session.add(
        Order(
            user_id=test_user.id,
            status="paid",
            total_cents=2500,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
    )
    await db_session.commit()

    response = await client.get("/admin/dashboard", cookies=cookies)

    assert response.status_code == 200
    assert "Revenue Trend" in response.text
    assert "placeholder" not in response.text
    assert "Collected $25.00 over the last 30 days." in response.text
    assert "<circle" in response.text


@pytest.mark.asyncio
async def test_dashboard_supports_revenue_trend_range_options(client: AsyncClient, test_user, db_session):
    cookies, _csrf = _admin_session(test_user.id)
    db_session.add(
        Order(
            user_id=test_user.id,
            status="paid",
            total_cents=4000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
    )
    await db_session.commit()

    response = await client.get("/admin/dashboard?range_days=90", cookies=cookies)

    assert response.status_code == 200
    assert 'href="/admin/dashboard?range_days=30"' in response.text
    assert 'href="/admin/dashboard?range_days=90"' in response.text
    assert 'href="/admin/dashboard?range_days=180"' in response.text
    assert "Collected $40.00 over the last 90 days." in response.text
    assert 'href="/admin/dashboard?range_days=90"' in response.text
    assert 'aria-current="page"' in response.text


@pytest.mark.asyncio
async def test_dashboard_invalid_revenue_trend_range_falls_back_to_30_days(
    client: AsyncClient, test_user, db_session
):
    cookies, _csrf = _admin_session(test_user.id)
    db_session.add(
        Order(
            user_id=test_user.id,
            status="paid",
            total_cents=4000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
    )
    await db_session.commit()

    response = await client.get("/admin/dashboard?range_days=365", cookies=cookies)

    assert response.status_code == 200
    assert "No collected revenue in the last 30 days." in response.text


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
