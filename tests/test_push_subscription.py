"""Tests for push discovery and storefront push config."""

from unittest.mock import patch

from app.services.addons import persist_addon_config


class TestPushDiscovery:
    async def test_storefront_config_includes_push_when_enabled(self, client, db_session):
        from app.addons.frontends.default.addon import DefaultFrontendAddon
        from app.addons.registry import addon_registry

        addon = addon_registry.get("default")
        if addon is None:
            addon_registry.register(DefaultFrontendAddon())
        await persist_addon_config(db_session, "default", {}, enabled=True)
        await db_session.commit()

        push_payload = {
            "provider": "onesignal",
            "config": {"appId": "abc-123"},
        }

        with patch(
            "app.api.v1.routers.storefront.get_public_push_config",
            return_value=push_payload,
        ):
            response = await client.get("/api/v1/storefront/config")

        assert response.status_code == 200
        data = response.json()
        assert data["notifications"]["push"]["provider"] == "onesignal"
        assert data["notifications"]["push"]["config"]["appId"] == "abc-123"

    async def test_fcm_service_worker_404_when_disabled(self, client):
        with patch(
            "app.services.push_discovery.get_notification_addon_for_channel",
            return_value=None,
        ):
            response = await client.get("/firebase-messaging-sw.js")
        assert response.status_code == 404

    async def test_fcm_service_worker_returns_js_when_enabled(self, client):
        from app.addons.notifications.fcm.addon import FcmAddon

        addon = FcmAddon()
        addon._config = {"web_api_key": "key", "project_id": "proj"}
        with patch(
            "app.services.push_discovery.get_notification_addon_for_channel",
            return_value=addon,
        ):
            response = await client.get("/firebase-messaging-sw.js")
        assert response.status_code == 200
        assert "firebase.initializeApp" in response.text
