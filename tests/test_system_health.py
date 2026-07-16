"""Tests for system health checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.system_health import (
    build_health_summary,
    build_integration_summary,
    run_store_health_checks,
)


@pytest.mark.asyncio
async def test_build_health_summary_healthy_when_infra_ok(db_session):
    from app.services.site_settings import update_site_settings

    await update_site_settings(db_session, {"site_url": "https://shop.example.com"})

    # Neutralize env-provided PUBLIC_APP_URL so the configured site_url wins.
    with patch("app.services.site_settings.settings") as mock_settings:
        mock_settings.public_app_url = None
        mock_settings.cors_origins = []
        with patch(
            "app.services.system_health.run_infrastructure_checks",
            AsyncMock(return_value=({"database": "ok", "storage": "ok"}, True)),
        ):
            with patch("app.services.addons.get_payment_addon", return_value=_mock_addon("Stripe")):
                with patch("app.services.addons.get_frontend_addon", return_value=_mock_addon("Default")):
                    with patch(
                        "app.services.addons.get_notification_addon_for_channel",
                        return_value=_mock_addon("Postmark"),
                    ):
                        with patch(
                            "app.services.addons.get_enabled",
                            return_value=[_mock_addon("Printful", addon_id="printful")],
                        ):
                            summary = await build_health_summary(db_session)

    assert summary.overall == "healthy"
    assert any(c.id == "database" and c.status == "ok" for c in summary.checks)


@pytest.mark.asyncio
async def test_build_health_summary_warns_without_site_url_when_payment_enabled(db_session):
    with patch("app.services.site_settings.settings") as mock_settings:
        mock_settings.public_app_url = None
        mock_settings.cors_origins = []
        with patch(
            "app.services.system_health.run_infrastructure_checks",
            AsyncMock(return_value=({"database": "ok", "storage": "ok"}, True)),
        ):
            with patch("app.services.addons.get_payment_addon", return_value=_mock_addon("Stripe")):
                with patch("app.services.addons.get_frontend_addon", return_value=_mock_addon("Default")):
                    with patch(
                        "app.services.addons.get_notification_addon_for_channel",
                        return_value=_mock_addon("Postmark"),
                    ):
                        with patch("app.services.addons.get_enabled", return_value=[]):
                            summary = await build_health_summary(db_session)

    assert summary.overall == "degraded"
    site_url = next(c for c in summary.checks if c.id == "site_url")
    assert site_url.status == "warning"
    assert "PUBLIC_APP_URL" in site_url.detail


@pytest.mark.asyncio
async def test_build_health_summary_degraded_without_payment(db_session):
    with patch(
        "app.services.system_health.run_infrastructure_checks",
        AsyncMock(return_value=({"database": "ok", "storage": "ok"}, True)),
    ):
        with patch("app.services.addons.get_payment_addon", return_value=None):
            with patch("app.services.addons.get_frontend_addon", return_value=_mock_addon("Default")):
                with patch(
                    "app.services.addons.get_notification_addon_for_channel",
                    return_value=_mock_addon("Postmark"),
                ):
                    with patch("app.services.addons.get_enabled", return_value=[]):
                        summary = await build_health_summary(db_session)

    assert summary.overall == "degraded"
    payment = next(c for c in summary.checks if c.id == "payment")
    assert payment.status == "warning"


@pytest.mark.asyncio
async def test_build_health_summary_unhealthy_when_database_fails(db_session):
    with patch(
        "app.services.system_health.run_infrastructure_checks",
        AsyncMock(return_value=({"database": "error: down", "storage": "ok"}, False)),
    ):
        with patch("app.services.addons.get_payment_addon", return_value=None):
            with patch("app.services.addons.get_frontend_addon", return_value=None):
                with patch(
                    "app.services.addons.get_notification_addon_for_channel",
                    return_value=None,
                ):
                    with patch("app.services.addons.get_enabled", return_value=[]):
                        summary = await build_health_summary(db_session)

    assert summary.overall == "unhealthy"


@pytest.mark.asyncio
async def test_run_store_health_checks_lists_warnings():
    with patch("app.services.addons.get_payment_addon", return_value=None):
        with patch("app.services.addons.get_frontend_addon", return_value=None):
            with patch(
                "app.services.addons.get_notification_addon_for_channel",
                return_value=None,
            ):
                with patch("app.services.addons.get_enabled", return_value=[]):
                    checks = await run_store_health_checks()

    assert len(checks) == 4
    assert all(c.status == "warning" for c in checks)


def _mock_addon(name: str, addon_id: str = "mock"):
    from unittest.mock import MagicMock

    addon = MagicMock()
    addon.addon_name = name
    addon.addon_id = addon_id
    return addon


@pytest.mark.asyncio
async def test_build_integration_summary_counts_suppliers():
    with patch("app.services.addons.get_payment_addon", return_value=_mock_addon("Stripe")):
        with patch("app.services.addons.get_frontend_addon", return_value=_mock_addon("Theme")):
            with patch(
                "app.services.addons.get_notification_addon_for_channel",
                side_effect=lambda ch: _mock_addon("Email") if ch == "email" else None,
            ):
                with patch(
                    "app.services.addons.get_enabled",
                    return_value=[_mock_addon("Printful", "printful")],
                ):
                    with patch(
                        "app.services.supplier_catalog_sync.list_syncable_suppliers",
                        return_value=[_mock_addon("Printful", "printful")],
                    ):
                        summary = await build_integration_summary()

    assert summary.payment_name == "Stripe"
    assert summary.frontend_name == "Theme"
    assert summary.notification_channels == ["email"]
    assert summary.enabled_supplier_count == 1
    assert summary.syncable_supplier_count == 1
