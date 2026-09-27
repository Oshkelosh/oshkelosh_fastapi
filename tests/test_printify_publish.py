"""Host tests for Printify publish webhook + idempotency."""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.addons.suppliers.printify.publish import PUBLISH_STARTED_TOPIC
from app.addons.suppliers.printify.routes import printify_webhook
from app.services.webhook_idempotency import claim_webhook_event
from models.processed_webhook_event import ProcessedWebhookEvent
from models.product import Product


def _signed_request(payload: dict, secret: str) -> Request:
    body = json.dumps(payload).encode("utf-8")
    digest = hmac.new(secret.encode(), body, sha256).hexdigest()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/suppliers/printify/webhook",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-pfy-signature", f"sha256={digest}".encode()),
        ],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_claim_webhook_event_idempotent(db_session):
    first = await claim_webhook_event(
        db_session,
        event_id="pfy-1",
        provider="printify",
        event_type="product:publish:started",
    )
    await db_session.commit()
    second = await claim_webhook_event(
        db_session,
        event_id="pfy-1",
        provider="printify",
        event_type="product:publish:started",
    )
    assert first is True
    assert second is False
    rows = (
        await db_session.execute(
            select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == "pfy-1")
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_webhook_publish_started_succeeds(db_session):
    secret = "webhook-secret-value"
    product = Product(
        name="Cool Tee",
        slug="cool-tee",
        price_cents=1000,
        inventory_quantity=0,
        status="published",
        supplier_external_product_key="printify:prod1",
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)

    client = MagicMock()
    client.publishing_succeeded = AsyncMock(return_value={})
    client.publishing_failed = AsyncMock()
    client.unpublish = AsyncMock()

    addon = MagicMock()
    addon.is_enabled = True
    addon._config = {"webhook_secret": secret}
    addon._require_client = MagicMock(return_value=client)

    payload = {
        "id": "evt-ok",
        "type": PUBLISH_STARTED_TOPIC,
        "resource": {"id": "prod1", "type": "product", "data": {"action": "create"}},
    }
    request = _signed_request(payload, secret)

    with patch("app.addons.registry.addon_registry.get", return_value=addon):
        response = await printify_webhook(request, session=db_session)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["action"] == "publishing_succeeded"
    client.publishing_succeeded.assert_awaited_once()
    assert client.publishing_succeeded.await_args.kwargs["external_id"] == str(product.id)


@pytest.mark.asyncio
async def test_webhook_missing_product_fails(db_session):
    secret = "webhook-secret-value"
    client = MagicMock()
    client.publishing_failed = AsyncMock(return_value={})
    client.publishing_succeeded = AsyncMock()

    addon = MagicMock()
    addon.is_enabled = True
    addon._config = {"webhook_secret": secret}
    addon._require_client = MagicMock(return_value=client)

    payload = {
        "id": "evt-missing",
        "type": PUBLISH_STARTED_TOPIC,
        "resource": {"id": "missing", "type": "product", "data": {"action": "update"}},
    }
    request = _signed_request(payload, secret)

    with patch("app.addons.registry.addon_registry.get", return_value=addon):
        response = await printify_webhook(request, session=db_session)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["action"] == "publishing_failed"
    client.publishing_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_delete_unpublishes(db_session):
    secret = "webhook-secret-value"
    client = MagicMock()
    client.unpublish = AsyncMock(return_value={})

    addon = MagicMock()
    addon.is_enabled = True
    addon._config = {"webhook_secret": secret}
    addon._require_client = MagicMock(return_value=client)

    payload = {
        "id": "evt-del",
        "type": PUBLISH_STARTED_TOPIC,
        "resource": {"id": "prod1", "type": "product", "data": {"action": "delete"}},
    }
    request = _signed_request(payload, secret)

    with patch("app.addons.registry.addon_registry.get", return_value=addon):
        response = await printify_webhook(request, session=db_session)

    assert response.status_code == 200
    assert json.loads(response.body)["action"] == "unpublish"
    client.unpublish.assert_awaited_once_with("prod1")


@pytest.mark.asyncio
async def test_webhook_duplicate_event_skips_api(db_session):
    secret = "webhook-secret-value"
    client = MagicMock()
    client.publishing_succeeded = AsyncMock(return_value={})
    client.publishing_failed = AsyncMock()
    client.unpublish = AsyncMock()

    product = Product(
        name="Cool Tee",
        slug="cool-tee",
        price_cents=1000,
        inventory_quantity=0,
        status="published",
        supplier_external_product_key="printify:prod1",
    )
    db_session.add(product)
    await db_session.commit()

    addon = MagicMock()
    addon.is_enabled = True
    addon._config = {"webhook_secret": secret}
    addon._require_client = MagicMock(return_value=client)

    payload = {
        "id": "evt-dup",
        "type": PUBLISH_STARTED_TOPIC,
        "resource": {"id": "prod1", "type": "product", "data": {"action": "create"}},
    }

    with patch("app.addons.registry.addon_registry.get", return_value=addon):
        first = await printify_webhook(_signed_request(payload, secret), session=db_session)
        second = await printify_webhook(_signed_request(payload, secret), session=db_session)

    assert first.status_code == 200
    assert json.loads(second.body)["duplicate"] is True
    assert client.publishing_succeeded.await_count == 1
