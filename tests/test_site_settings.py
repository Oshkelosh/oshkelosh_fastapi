"""Tests for site settings URL resolution and public serialization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.site_settings import (
    is_dev_fallback_site_url,
    resolve_public_site_url,
    site_settings_to_public_dict,
)
from models.site_settings import SiteSettings


class TestResolvePublicSiteUrl:
    def test_prefers_public_app_url(self):
        site = SiteSettings(site_url="https://legacy.example.com")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = "https://env.example.com/"
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_public_site_url(site_settings=site) == "https://env.example.com"

    def test_falls_back_to_legacy_site_url(self):
        site = SiteSettings(site_url="https://legacy.example.com")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = ["https://cors.example.com"]
            assert resolve_public_site_url(site_settings=site) == "https://legacy.example.com"

    def test_falls_back_to_cors_origin(self):
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = ["https://cors.example.com/"]
            assert resolve_public_site_url() == "https://cors.example.com"

    def test_falls_back_to_request_base_url(self):
        request = MagicMock()
        request.base_url = "https://request.example/"
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            assert (
                resolve_public_site_url(request=request) == "https://request.example"
            )

    def test_dev_fallback_when_nothing_configured(self):
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = None
            mock_settings.cors_origins = []
            assert resolve_public_site_url() == "http://localhost:8000"

    def test_is_dev_fallback_site_url(self):
        assert is_dev_fallback_site_url("http://localhost:8000")
        assert is_dev_fallback_site_url("http://localhost:8000/")
        assert not is_dev_fallback_site_url("https://shop.example.com")


class TestSiteSettingsPublicDict:
    def test_injects_resolved_site_url(self):
        site = SiteSettings(store_name="Shop", site_url="https://legacy.example.com")
        with patch("app.services.site_settings.settings") as mock_settings:
            mock_settings.public_app_url = "https://env.example.com"
            mock_settings.cors_origins = []
            data = site_settings_to_public_dict(site)
        assert data["site_url"] == "https://env.example.com"
        assert data["store_name"] == "Shop"
        assert data["shop_currency"] == "USD"
