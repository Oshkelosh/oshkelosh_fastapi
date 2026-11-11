"""Host bot-challenge seam. Uses a fake tool so the installable addon is optional."""

import re

from httpx import AsyncClient

from app.addons.base import AddonConfig
from app.addons.tools.base import ToolAddon
from app.core.exceptions import ValidationError

SAMPLE_ADDRESS = {
    "line1": "123 Main St",
    "city": "Portland",
    "state": "OR",
    "postal_code": "97201",
    "country": "US",
}


class _ChallengeConfig(AddonConfig):
    pass


class _ChallengeTool(ToolAddon):
    addon_id = "test_bot_challenge"
    addon_name = "Test challenge"
    addon_category = "tool"

    @classmethod
    def config_schema(cls):
        return _ChallengeConfig

    async def initialize(self, config: dict) -> None:
        self.is_enabled = True

    async def shutdown(self) -> None:
        self.is_enabled = False

    def protects_challenge(self, action: str) -> bool:
        return action in {"register", "login", "forgot_password", "admin_login"}

    def challenge_public_config(self) -> dict:
        return {
            "site_key": "site-key",
            "script_url": "https://example.test/challenge.js",
            "actions": ["register", "login", "forgot_password"],
        }

    def admin_challenge_widget_html(self) -> str:
        return '<div id="bot-challenge-widget"></div>'

    async def verify_bot_challenge(self, token, remote_ip, action) -> None:
        if token != "ok":
            raise ValidationError(message="Bot challenge failed")


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": "SecurePass123!",
        "full_name": "Challenge User",
        "default_shipping_address": SAMPLE_ADDRESS,
        "billing_same_as_shipping": True,
    }


class TestBotChallengeSeam:
    def setup_method(self):
        from app.addons.registry import addon_registry

        self._registry = addon_registry
        addon = _ChallengeTool()
        addon.is_enabled = True
        addon_registry._registry[addon.addon_id] = addon

    def teardown_method(self):
        self._registry._registry.pop("test_bot_challenge", None)

    async def test_login_requires_header_and_accepts_passing_token(self, client: AsyncClient):
        headers = {"X-Bot-Challenge": "ok"}
        registered = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("challenge@example.com"),
            headers=headers,
        )
        assert registered.status_code == 201

        denied = await client.post(
            "/api/v1/auth/login",
            json={"email": "challenge@example.com", "password": "SecurePass123!"},
        )
        assert denied.status_code == 422
        assert denied.json()["message"] == "Bot challenge failed"

        allowed = await client.post(
            "/api/v1/auth/login",
            json={"email": "challenge@example.com", "password": "SecurePass123!"},
            headers=headers,
        )
        assert allowed.status_code == 200
        assert "access_token" in allowed.json()

    async def test_forgot_password_requires_header(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "missing@example.com"},
        )
        assert response.status_code == 422

    async def test_storefront_config_includes_challenge(self, client: AsyncClient):
        response = await client.get("/api/v1/storefront/config")
        assert response.status_code == 200
        challenge = response.json()["auth"]["challenge"]
        assert challenge["site_key"] == "site-key"
        assert challenge["actions"] == ["register", "login", "forgot_password"]

    async def test_admin_login_renders_widget_and_rejects_missing_token(
        self, client: AsyncClient, test_user
    ):
        page = await client.get("/admin/login")
        assert page.status_code == 200
        assert 'id="bot-challenge-widget"' in page.text
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match is not None

        rejected = await client.post(
            "/admin/login",
            data={
                "email": test_user.email,
                "password": "SecurePass123!",
                "csrf_token": match.group(1),
                "bot_challenge": "",
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 200
        assert "Bot challenge failed" in rejected.text

        allowed = await client.post(
            "/admin/login",
            data={
                "email": test_user.email,
                "password": "SecurePass123!",
                "csrf_token": match.group(1),
                "bot_challenge": "ok",
            },
            follow_redirects=False,
        )
        assert allowed.status_code == 302
