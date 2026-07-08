"""Tests for the addon registry and base interfaces."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.addons.base import BaseAddon
from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from fastapi.responses import RedirectResponse

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ADDON_TEMPLATES = _REPO_ROOT / "app" / "addons"


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


class TestBaseAddon:
    """Test the abstract base addon interface."""

    def test_base_addon_requires_subclass(self):
        """BaseAddon should be abstract and not instantiable directly."""
        with pytest.raises(TypeError):
            BaseAddon()


class TestManualSupplierAddon:
    @pytest.mark.asyncio
    async def test_manual_create_order(self, db_session):
        from contextlib import asynccontextmanager

        from app.addons.suppliers.manual.addon import ManualSupplierAddon
        from models.manual_supplier import ManualSupplier

        db_session.add(
            ManualSupplier(slug="local_workshop", name="Local Workshop", is_active=True)
        )
        await db_session.commit()

        @asynccontextmanager
        async def test_scope():
            yield db_session

        addon = ManualSupplierAddon()
        await addon.initialize({"is_active": True})

        with patch("app.db.connection.session_scope", test_scope):
            result = await addon.create_order(
                [{"supplier_product_id": "SKU-1", "quantity": 1, "product_name": "Mug"}],
                {"line1": "1 Main St", "city": "Portland"},
                external_id="42",
                supplier_ref="local_workshop",
            )
        assert result["success"] is True
        assert result["supplier_slug"] == "local_workshop"
        assert result["external_id"] == "42"


class TestAllAddonAdminConfigurePages:
    """Every addon with dedicated admin UI must render without template errors."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "configure_url,expected_snippet",
        [
            ("/admin/suppliers/printful", "Printful"),
            ("/admin/suppliers/printify", "Printify"),
            ("/admin/suppliers/manual", "Manual Suppliers"),
            ("/admin/payments/stripe", "Stripe"),
            ("/admin/payments/rapyd", "Rapyd"),
            ("/admin/payments/adyen", "Adyen"),
            ("/admin/payments/checkout", "Checkout"),
            ("/admin/payments/mangopay", "Mangopay"),
            ("/admin/payments/paypal", "PayPal"),
            ("/admin/payments/mollie", "Mollie"),
            ("/admin/payments/airwallex", "Airwallex"),
            ("/admin/payments/worldpay", "Worldpay"),
            ("/admin/notifications/postmark", "Postmark"),
            ("/admin/notifications/smtp", "SMTP"),
            ("/admin/notifications/resend", "Resend"),
            ("/admin/notifications/sendgrid", "SendGrid"),
            ("/admin/notifications/mailgun", "Mailgun"),
            ("/admin/notifications/ses", "Amazon SES"),
            ("/admin/notifications/twilio", "Twilio"),
            ("/admin/notifications/vonage", "Vonage"),
            ("/admin/notifications/messagebird", "MessageBird"),
            ("/admin/notifications/fcm", "FCM"),
            ("/admin/notifications/onesignal", "OneSignal"),
            ("/admin/notifications/pusher_beams", "Pusher Beams"),
            ("/admin/frontends/default", "Default Storefront"),
            ("/admin/tools/sso", "SSO"),
        ],
    )
    async def test_configure_page_renders_html(
        self, client, test_user, configure_url, expected_snippet
    ):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            configure_url,
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200, resp.text[:500]
        assert "text/html" in resp.headers.get("content-type", "")
        assert expected_snippet in resp.text
        assert "internal_error" not in resp.text
        if 'name="csrf_token"' in resp.text:
            match = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
            assert match is not None
            assert len(match.group(1)) > 10, (
                f"{configure_url}: csrf_token field rendered empty"
            )

    def test_all_registered_addons_with_admin_routes_have_smoke_urls(self):
        from app.addons.registry import addon_registry

        urls = {
            meta["configure_url"]
            for meta in addon_registry.list_addons()
            if meta.get("has_admin_routes")
        }
        assert "/admin/suppliers/printful" in urls
        assert "/admin/payments/stripe" in urls
        assert "/admin/payments/adyen" in urls
        assert "/admin/payments/paypal" in urls
        assert "/admin/tools/sso" in urls


class TestAddonAdminTemplateCsrf:
    """Every addon admin template with a form must include csrf_token."""

    def test_all_addon_admin_forms_include_csrf_token(self):
        violations: list[str] = []
        for path in sorted(_ADDON_TEMPLATES.glob("**/templates/*.html")):
            if "node_modules" in path.parts:
                continue
            text = path.read_text()
            form_count = len(re.findall(r"<form\b", text, flags=re.IGNORECASE))
            if form_count == 0:
                continue
            csrf_count = text.count("csrf_token") + text.count("csrf_field()")
            if csrf_count < form_count:
                violations.append(
                    f"{path.relative_to(_REPO_ROOT)}: {form_count} form(s), {csrf_count} csrf_token(s)"
                )
        assert not violations, "Missing CSRF fields:\n" + "\n".join(violations)


class TestAddonAdminRouteCsrf:
    """Custom addon routes must not hand-roll /save without CSRF validation."""

    _SHARED_FACTORIES = (
        "build_supplier_routers",
        "build_payment_routers",
        "build_notification_routers",
    )

    def test_custom_save_routes_validate_csrf_or_use_shared_factory(self):
        violations: list[str] = []
        for path in sorted(_ADDON_TEMPLATES.rglob("routes.py")):
            if "node_modules" in path.parts:
                continue
            text = path.read_text()
            if '@admin_router.post("/save")' not in text:
                continue
            rel = path.relative_to(_REPO_ROOT)
            if any(factory in text for factory in self._SHARED_FACTORIES):
                violations.append(f"{rel}: custom /save alongside shared route factory")
                continue
            if "require_addon_csrf" not in text and "_require_csrf" not in text:
                violations.append(f"{rel}: POST /save without CSRF validation")
        assert not violations, "\n".join(violations)


class TestAddonAdminConfigSave:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "save_url,redirect_url,form_data",
        [
            (
                "/admin/frontends/default/save",
                "/admin/frontends/default",
                {
                    "layout": "grid",
                    "products_per_page": "12",
                    "hero_products": "5",
                    "category_products": "8",
                    "show_category_nav": "on",
                },
            ),
            (
                "/admin/payments/stripe/save",
                "/admin/payments/stripe",
                {
                    "secret_key": "sk_test_csrf_fixture",
                    "publishable_key": "pk_test_csrf_fixture",
                    "webhook_secret": "whsec_csrf_fixture",
                    "success_url": "",
                    "cancel_url": "",
                },
            ),
            (
                "/admin/notifications/postmark/save",
                "/admin/notifications/postmark",
                {
                    "api_token": "postmark-csrf-fixture-token",
                    "from_address": "noreply@example.com",
                },
            ),
            (
                "/admin/suppliers/printful/save",
                "/admin/suppliers/printful",
                {
                    "api_key": "printful-csrf-fixture",
                    "is_active": "on",
                    "auto_confirm": "on",
                },
            ),
            (
                "/admin/suppliers/printify/save",
                "/admin/suppliers/printify",
                {
                    "api_key": "printify-csrf-fixture",
                    "shop_id": "12345",
                    "is_active": "on",
                    "auto_confirm": "on",
                },
            ),
        ],
    )
    async def test_save_config_with_valid_csrf_redirects(
        self, client, test_user, save_url, redirect_url, form_data
    ):
        from app.main import app

        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)

        save_patch = None
        if "/payments/" in save_url:
            save_patch = "app.addons.payments.shared_routes.save_addon_from_form"
        elif "/notifications/" in save_url:
            save_patch = "app.addons.notifications.shared_routes.save_addon_from_form"
        elif "/suppliers/" in save_url:
            save_patch = "app.addons.admin_helpers.save_addon_from_form"

        if save_patch:
            with patch(save_patch, new_callable=AsyncMock) as mock_save:
                mock_save.return_value = RedirectResponse(url=redirect_url, status_code=302)
                resp = await client.post(
                    save_url,
                    cookies=cookies,
                    data={"csrf_token": csrf, **form_data},
                    follow_redirects=False,
                )
        else:
            resp = await client.post(
                save_url,
                cookies=cookies,
                data={"csrf_token": csrf, **form_data},
                follow_redirects=False,
            )

        assert "Invalid CSRF token" not in resp.text
        assert resp.status_code == 302, resp.text[:500]
        assert resp.headers["location"] == redirect_url


class TestSupplierAdminConfigure:
    @pytest.mark.asyncio
    async def test_printful_configure_page_renders_with_admin_session(
        self, client, test_user
    ):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/suppliers/printful",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "Printful Supplier" in resp.text
        assert "API Key" in resp.text

    @pytest.mark.asyncio
    async def test_printify_configure_page_renders_with_admin_session(
        self, client, test_user
    ):
        from app.admin.session import SESSION_COOKIE_NAME, encode_session
        from app.main import app

        app.state.needs_setup = False
        token = encode_session(test_user.id)
        resp = await client.get(
            "/admin/suppliers/printify",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        assert "Printify" in resp.text

    def test_render_addon_admin_page_does_not_duplicate_flash(self):
        from types import SimpleNamespace

        from app.addons.admin_helpers import make_addon_jinja_env, render_addon_admin_page
        from pathlib import Path

        templates = Path(__file__).resolve().parents[1] / "app" / "admin" / "templates"
        env = make_addon_jinja_env(templates)
        request = SimpleNamespace(
            cookies={},
            state=SimpleNamespace(),
            url=SimpleNamespace(path="/admin/login"),
        )
        html = render_addon_admin_page(
            env,
            request,
            "login.html",
            "Test Title",
            redirect_to="/dashboard",
            error="",
        )
        assert isinstance(html, str)
        assert "Admin Login" in html


class TestAddonRegistry:
    """Test the addon registry."""

    def test_registry_discover_addons(self):
        """Registry should discover all installed addons."""
        from app.addons.registry import AddonRegistry
        registry = AddonRegistry()
        addons = registry.list_addons()
        addon_ids = [a["addon_id"] for a in addons]
        assert "printful" in addon_ids
        assert "printify" in addon_ids
        assert "manual" in addon_ids
        assert "stripe" in addon_ids
        assert "postmark" in addon_ids
        assert "sso" in addon_ids

    def test_registry_get_enabled_by_category(self):
        """get_enabled returns only enabled addons in a category."""
        from app.addons.registry import AddonRegistry
        from app.addons.payments.stripe.addon import StripeAddon

        registry = AddonRegistry()
        registry.register(StripeAddon)
        stripe = registry.get("stripe")
        assert stripe is not None
        stripe.is_enabled = True
        enabled = registry.get_enabled("payment")
        assert len(enabled) == 1
        assert enabled[0].addon_id == "stripe"
        stripe.is_enabled = False
