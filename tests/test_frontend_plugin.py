"""Tests for site settings, storefront config API, and frontend addons."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.addons.frontends.default.addon import DefaultFrontendAddon
from app.addons.registry import AddonRegistry
from app.services.addons import persist_addon_config
from app.services.site_settings import get_site_settings, update_site_settings

OTHER_FIXTURE_DIST = Path(__file__).parent / "fixtures" / "frontends" / "other"


class OtherFixtureFrontend(DefaultFrontendAddon):
    """Test frontend with a distinct static bundle."""

    addon_id = "other_fixture"
    addon_name = "Other Fixture Frontend"

    def get_static_directory(self) -> str:
        return str(OTHER_FIXTURE_DIST)


@pytest.fixture
def disable_legacy_storefront(monkeypatch):
    """Prevent legacy frontend/dist from masking disabled-addon behavior."""
    missing = Path(__file__).parent / "fixtures" / "frontends" / "missing"
    monkeypatch.setattr(
        "app.services.storefront_resolver._LEGACY_DIST",
        missing,
    )


@pytest.fixture
def other_fixture_frontend():
    from app.addons.registry import addon_registry

    if addon_registry.get("other_fixture") is None:
        addon_registry.register(OtherFixtureFrontend)
    yield addon_registry.get("other_fixture")
    addon_registry._registry.pop("other_fixture", None)


class TestSiteSettings:
    async def test_get_or_create_defaults(self, db_session):
        site = await get_site_settings(db_session)
        assert site.store_name == "Oshkelosh"
        assert site.primary_color == "#2563eb"
        assert site.tax_rate_bps == 800
        assert site.shipping_flat_cents == 500
        assert site.shipping_mode == "flat"

    async def test_update_site_settings(self, db_session):
        await update_site_settings(
            db_session,
            {"store_name": "My Shop", "primary_color": "#ff0000"},
        )
        site = await get_site_settings(db_session)
        assert site.store_name == "My Shop"
        assert site.primary_color == "#ff0000"


class TestFrontendAddon:
    def test_default_frontend_config_defaults(self):
        from app.addons.frontends.default.addon import DefaultFrontendConfig

        config = DefaultFrontendConfig()
        assert config.products_per_page == 12
        assert config.hero_products == 5
        assert config.category_products == 8

    def test_default_frontend_discovered(self):
        registry = AddonRegistry()
        registry.discover()
        assert "default" in [a["addon_id"] for a in registry.list_addons()]

    def test_default_static_directory_exists(self):
        addon = DefaultFrontendAddon()
        from pathlib import Path

        dist = Path(addon.get_static_directory())
        assert (dist / "index.html").exists()


class TestOnlyOneFrontendEnabled:
    async def test_enabling_default_disables_other_frontends(self, db_session):
        from app.addons.registry import addon_registry

        class OtherTestFrontend(DefaultFrontendAddon):
            addon_id = "other_test"
            addon_name = "Other Test"

        addon_registry.register(OtherTestFrontend)
        other = addon_registry.get("other_test")
        if addon_registry.get("default") is None:
            addon_registry.register(DefaultFrontendAddon())
        default = addon_registry.get("default")

        await persist_addon_config(
            db_session,
            "other_test",
            {"layout": "list", "products_per_page": 8, "show_category_nav": True},
            enabled=True,
        )
        assert other.is_enabled is True

        await persist_addon_config(
            db_session,
            "default",
            {"layout": "grid", "products_per_page": 12, "show_category_nav": True},
            enabled=True,
        )
        assert default.is_enabled is True
        assert other.is_enabled is False

        addon_registry._registry.pop("other_test", None)


class TestStorefrontAPI:
    async def test_config_503_when_no_frontend(self, client: AsyncClient, db_session):
        from app.addons.registry import addon_registry

        for addon in list(addon_registry.get_enabled("frontend")):
            await addon_registry.disable_async(addon.addon_id)

        resp = await client.get("/api/v1/storefront/config")
        assert resp.status_code == 503

    async def test_config_merges_site_and_frontend(self, client: AsyncClient, db_session):
        from app.addons.registry import addon_registry

        await update_site_settings(db_session, {"store_name": "Merged Shop"})
        await db_session.commit()

        addon = addon_registry.get("default")
        if addon is None:
            addon_registry.register(DefaultFrontendAddon())
            addon = addon_registry.get("default")

        await persist_addon_config(
            db_session,
            "default",
            {"layout": "list", "products_per_page": 6, "show_category_nav": False},
            enabled=True,
        )
        await db_session.commit()

        resp = await client.get("/api/v1/storefront/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["site"]["store_name"] == "Merged Shop"
        assert data["frontend"]["addon_id"] == "default"
        assert data["frontend"]["config"]["layout"] == "list"

    async def test_theme_css_returns_variables(self, client: AsyncClient, db_session):
        await update_site_settings(db_session, {"primary_color": "#aabbcc"})
        await db_session.commit()

        resp = await client.get("/api/v1/storefront/theme.css")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")
        assert "#aabbcc" in resp.text


class TestStorefrontMount:
    def test_openapi_lists_storefront_routes(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/api/v1/storefront/config" in paths
        assert "/api/v1/storefront/theme.css" in paths

    def test_storefront_dynamic_handler_registered(self):
        from app.main import create_app
        from app.storefront.static import DynamicStorefrontStatic

        app = create_app()
        spa_routes = [r for r in app.routes if getattr(r, "name", None) == "spa"]
        assert len(spa_routes) == 1
        assert isinstance(spa_routes[0].app, DynamicStorefrontStatic)


class TestDynamicStorefrontStatic:
    async def test_root_503_when_no_frontend_enabled(
        self,
        client: AsyncClient,
        db_session,
        disable_legacy_storefront,
    ):
        from app.addons.registry import addon_registry

        for addon in list(addon_registry.get_enabled("frontend")):
            await addon_registry.disable_async(addon.addon_id)
        await db_session.commit()

        resp = await client.get("/")
        assert resp.status_code == 503
        assert "Storefront unavailable" in resp.text

    async def test_switching_frontend_serves_new_static_without_restart(
        self,
        client: AsyncClient,
        db_session,
        other_fixture_frontend,
    ):
        from app.addons.registry import addon_registry
        from app.main import app

        app.state.needs_setup = False
        if addon_registry.get("default") is None:
            addon_registry.register(DefaultFrontendAddon())

        await persist_addon_config(
            db_session,
            "default",
            {"layout": "grid", "products_per_page": 12, "show_category_nav": True},
            enabled=True,
        )
        await db_session.commit()

        resp = await client.get("/")
        assert resp.status_code == 200
        assert "data-sveltekit-preload-data" in resp.text
        assert "OTHER-FRONTEND-MARKER" not in resp.text

        await persist_addon_config(
            db_session,
            "other_fixture",
            {"layout": "list", "products_per_page": 8, "show_category_nav": True},
            enabled=True,
        )
        await db_session.commit()

        resp = await client.get("/")
        assert resp.status_code == 200
        assert "OTHER-FRONTEND-MARKER" in resp.text
        assert "data-sveltekit-preload-data" not in resp.text

    async def test_config_and_static_use_same_resolver(
        self,
        client: AsyncClient,
        db_session,
        other_fixture_frontend,
    ):
        from app.addons.registry import addon_registry
        from app.main import app

        app.state.needs_setup = False
        if addon_registry.get("default") is None:
            addon_registry.register(DefaultFrontendAddon())

        await persist_addon_config(
            db_session,
            "other_fixture",
            {"layout": "list", "products_per_page": 8, "show_category_nav": True},
            enabled=True,
        )
        await db_session.commit()

        config_resp = await client.get("/api/v1/storefront/config")
        root_resp = await client.get("/")

        assert config_resp.status_code == 200
        assert config_resp.json()["frontend"]["addon_id"] == "other_fixture"
        assert root_resp.status_code == 200
        assert "OTHER-FRONTEND-MARKER" in root_resp.text


class TestFrontendAdminConfigure:
    async def test_configure_url_not_404_without_trailing_slash(
        self, client: AsyncClient, test_user
    ):
        """Setup button links to /admin/frontends/default (no trailing slash)."""
        from app.main import app

        app.state.needs_setup = False
        resp = await client.get("/admin/frontends/default", follow_redirects=False)
        assert resp.status_code != 404

    async def test_configure_page_renders_with_admin_session(
        self, client: AsyncClient, test_user
    ):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/frontends/default",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "Default Storefront" in resp.text
        assert "Enable this storefront" in resp.text
        assert "Main page" in resp.text
        assert "Hero products" in resp.text
        assert "Category products" in resp.text
        assert 'name="csrf_token"' in resp.text
        import re

        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
        assert match is not None, "csrf_token input missing from form"
        assert len(match.group(1)) > 10, "csrf_token rendered empty"

    async def test_save_config_with_valid_csrf_redirects(
        self, client: AsyncClient, test_user
    ):
        from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        csrf = decode_session(token)["csrf"]
        resp = await client.post(
            "/admin/frontends/default/save",
            cookies={SESSION_COOKIE_NAME: token},
            data={
                "csrf_token": csrf,
                "layout": "list",
                "products_per_page": "12",
                "hero_products": "5",
                "category_products": "8",
                "show_category_nav": "on",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/frontends/default"
        assert "Invalid CSRF token" not in resp.text

    async def test_trailing_slash_redirects_to_configure_url(
        self, client: AsyncClient, test_user
    ):
        from app.main import app

        app.state.needs_setup = False
        resp = await client.get(
            "/admin/frontends/default/",
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert resp.headers["location"] == "/admin/frontends/default"

    def test_openapi_lists_configure_route_without_trailing_slash(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/admin/frontends/default" in paths
