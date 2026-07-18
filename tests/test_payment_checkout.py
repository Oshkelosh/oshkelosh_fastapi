"""Tests for payment checkout redirect URL helpers and orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.addons.payments.helpers import (
    build_checkout_redirect_urls,
    effective_redirect_url,
    resolve_storefront_base_url,
)
from app.services.payment_checkout import start_checkout
from app.services.site_settings import update_site_settings
from models.site_settings import SiteSettings


class TestRedirectUrlHelpers:
    def test_resolve_storefront_base_url_prefers_public_app_url(self):
        site = SiteSettings(site_url="https://legacy.example.com")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = "https://env.example.com"
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_storefront_base_url(site) == "https://env.example.com"

    def test_resolve_storefront_base_url_falls_back_to_legacy_site_url(self):
        site = SiteSettings(site_url="https://shop.example.com/")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_storefront_base_url(site) == "https://shop.example.com"

    def test_resolve_storefront_base_url_falls_back_to_public_app_url(self):
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = "https://env.example.com"
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_storefront_base_url(None) == "https://env.example.com"

    def test_resolve_storefront_base_url_falls_back_to_cors(self):
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_storefront_base_url(None) == "https://cors.example.com"

    def test_resolve_storefront_base_url_dev_fallback(self):
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            assert resolve_storefront_base_url(None) == "http://localhost:8000"

    def test_build_checkout_redirect_urls(self):
        site = SiteSettings(site_url="https://shop.example.com")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            return_url, cancel_url = build_checkout_redirect_urls(site, 42)
            assert return_url == "https://shop.example.com/orders/42?payment=return"
            assert cancel_url == "https://shop.example.com/checkout"

    def test_effective_redirect_url_uses_configured(self):
        assert (
            effective_redirect_url(
                "https://custom.example/success",
                fallback="https://auto.example/success",
            )
            == "https://custom.example/success"
        )

    def test_effective_redirect_url_uses_fallback_when_empty(self):
        assert (
            effective_redirect_url("", fallback="https://auto.example/success")
            == "https://auto.example/success"
        )
        assert (
            effective_redirect_url(None, fallback="https://auto.example/success")
            == "https://auto.example/success"
        )


class TestStartCheckout:
    async def test_start_checkout_passes_redirect_urls(self, db_session):
        await update_site_settings(
            db_session, {"site_url": "https://shop.example.com"}
        )

        order = MagicMock()
        order.id = 7
        order.total_cents = 1500
        order.currency = "usd"
        order.payment_processor_id = None
        order.payment_id = None

        mock_addon = AsyncMock()
        mock_addon.addon_id = "mock"
        mock_addon.create_payment = AsyncMock(
            return_value={"success": True, "session_id": "sess_1", "url": "https://pay.test"}
        )

        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            await start_checkout(
                db_session,
                order,
                mock_addon,
                customer_email="buyer@example.com",
            )

        mock_addon.create_payment.assert_awaited_once_with(
            amount=1500,
            currency="usd",
            order_id="7",
            customer_email="buyer@example.com",
            return_url="https://shop.example.com/orders/7?payment=return",
            cancel_url="https://shop.example.com/checkout",
        )
