"""Integration tests for addon wiring, persistence, and commerce hooks."""

from unittest.mock import AsyncMock, patch

from app.addons.base import AddonConfig, BaseAddon
from app.addons.registry import AddonRegistry
from app.services.addons import persist_addon_config
from app.services.commerce import apply_order_status_change
from models.order import Order


class _MockConfig(AddonConfig):
    api_key: str = "test-key"


class _MockAddon(BaseAddon):
    addon_id = "mock_addon"
    addon_name = "Mock Addon"
    addon_description = "For tests"
    addon_category = "notification"
    version = "0.0.1"

    def __init__(self) -> None:
        super().__init__()
        self.initialized = False
        self.shut_down = False

    @classmethod
    def config_schema(cls):
        return _MockConfig

    async def initialize(self, config: dict) -> None:
        self.initialized = True
        self._config = config

    async def shutdown(self) -> None:
        self.shut_down = True
        self.is_enabled = False


class TestAddonRegistryLifecycle:
    async def test_enable_and_disable_call_lifecycle(self):
        registry = AddonRegistry()
        registry.register(_MockAddon)

        await registry.enable_async("mock_addon", {"api_key": "secret"})
        addon = registry.get("mock_addon")
        assert addon is not None
        assert addon.is_enabled is True
        assert addon.initialized is True

        await registry.disable_async("mock_addon")
        assert addon.is_enabled is False
        assert addon.shut_down is True


class TestPersistAddonConfig:
    async def test_persist_writes_db_and_registry(self, db_session):
        from app.addons.registry import addon_registry

        addon_registry.register(_MockAddon)

        row = await persist_addon_config(
            db_session,
            "mock_addon",
            {"api_key": "persisted"},
            enabled=True,
        )
        await db_session.commit()

        assert row.addon_id == "mock_addon"
        assert row.is_enabled is True
        assert addon_registry.get("mock_addon").is_enabled is True
        assert addon_registry.get_config("mock_addon")["api_key"] == "persisted"


class TestMountAddonRouters:
    def test_openapi_includes_printful_products_route(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/api/v1/suppliers/printful/products" in paths


class TestCheckoutRequiresPaymentAddon:
    async def test_checkout_without_payment_addon_fails(
        self, client, test_user, test_product, db_session
    ):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": test_product.id, "quantity": 1},
        )
        order_resp = await client.post("/api/v1/orders", headers=headers)
        order_id = order_resp.json()["id"]

        checkout = await client.post(
            f"/api/v1/orders/{order_id}/checkout",
            headers=headers,
        )
        assert checkout.status_code in (400, 422)


class TestOrderPaidNotification:
    async def test_paid_transition_triggers_notification(self, db_session, test_user):
        from app.addons.notifications.base import NotificationAddon
        from app.addons.registry import addon_registry

        class _NotifyAddon(NotificationAddon):
            addon_id = "notify_test"
            addon_name = "Notify Test"
            addon_description = "Test"
            version = "0.0.1"
            send_email = AsyncMock(return_value={"success": True})

            @classmethod
            def config_schema(cls):
                return _MockConfig

            async def initialize(self, config: dict) -> None:
                self.is_enabled = True

            async def shutdown(self) -> None:
                pass

            async def send_sms(self, to: str, body: str) -> dict:
                return {"success": False}

            async def send_webhook(self, url: str, payload: dict) -> dict:
                return {"success": False}

        notify = _NotifyAddon()
        notify.is_enabled = True
        addon_registry._registry["notify_test"] = notify

        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        with patch(
            "app.services.notifications.get_notification_addon",
            return_value=notify,
        ):
            await apply_order_status_change(db_session, order, "paid")

        notify.send_email.assert_awaited_once()
        addon_registry._registry.pop("notify_test", None)
