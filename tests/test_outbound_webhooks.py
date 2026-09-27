"""Outbound HMAC webhook signing, emit, and admin UI."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.main import app
from app.services.commerce import apply_order_status_change
from app.services.outbound_webhooks import (
    EVENT_ORDER_PAID,
    EVENT_WEBHOOK_TEST,
    HEADER_EVENT,
    HEADER_SIGNATURE,
    emit_outbound_webhook,
    get_outbound_webhook_endpoint,
    save_outbound_webhook_endpoint,
    send_outbound_webhook_test,
    sign_webhook_payload,
    verify_webhook_signature,
)
from app.services.site_settings import site_settings_to_public_dict
from models.order import Order
from models.site_settings import SiteSettings
from models.user import User


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


class _FakeResponse:
    status_code = 200


class _FakeClient:
    calls: ClassVar[list[tuple[str, bytes, dict[str, str]]]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, content=None, headers=None):
        type(self).calls.append((url, content, headers or {}))
        return _FakeResponse()


def test_sign_and_verify_roundtrip():
    secret = "test-secret"
    timestamp = "1700000000"
    body = b'{"ok":true}'
    header = sign_webhook_payload(secret, timestamp, body)
    assert header.startswith("t=1700000000,v1=")
    assert verify_webhook_signature(secret, timestamp, body, header) is True
    assert verify_webhook_signature(secret, timestamp, body, header + "x") is False
    assert verify_webhook_signature("other", timestamp, body, header) is False


@pytest.mark.asyncio
async def test_emit_skips_when_disabled(db_session):
    await save_outbound_webhook_endpoint(
        db_session,
        enabled=False,
        url="https://hooks.example.com/oshkelosh",
        events=[EVENT_ORDER_PAID],
    )
    await db_session.commit()
    _FakeClient.calls = []
    with patch("app.services.outbound_webhooks.httpx.AsyncClient", _FakeClient):
        sent = await emit_outbound_webhook(db_session, EVENT_ORDER_PAID, {"order_id": 1})
    assert sent is False
    assert _FakeClient.calls == []


@pytest.mark.asyncio
async def test_emit_posts_signed_headers_when_enabled(db_session):
    await save_outbound_webhook_endpoint(
        db_session,
        enabled=True,
        url="https://hooks.example.com/oshkelosh",
        events=[EVENT_ORDER_PAID],
    )
    await db_session.commit()
    _FakeClient.calls = []
    with patch("app.services.outbound_webhooks.httpx.AsyncClient", _FakeClient):
        sent = await emit_outbound_webhook(db_session, EVENT_ORDER_PAID, {"order_id": 9})
    assert sent is True
    assert len(_FakeClient.calls) == 1
    url, body, headers = _FakeClient.calls[0]
    assert url == "https://hooks.example.com/oshkelosh"
    assert headers[HEADER_EVENT] == EVENT_ORDER_PAID
    row = await get_outbound_webhook_endpoint(db_session)
    assert verify_webhook_signature(
        row.secret, headers["X-Webhook-Timestamp"], body, headers[HEADER_SIGNATURE]
    )


@pytest.mark.asyncio
async def test_order_paid_emits_once(db_session, test_user):
    await save_outbound_webhook_endpoint(
        db_session,
        enabled=True,
        url="https://hooks.example.com/oshkelosh",
        events=[EVENT_ORDER_PAID],
    )
    order = Order(
        user_id=test_user.id,
        status="pending",
        total_cents=1500,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
    )
    db_session.add(order)
    await db_session.flush()
    _FakeClient.calls = []
    with (
        patch("app.services.fulfillment.fulfill_order_with_suppliers", new_callable=AsyncMock),
        patch("app.services.notifications.notify_order_status_change", new_callable=AsyncMock),
        patch("app.services.outbound_webhooks.httpx.AsyncClient", _FakeClient),
    ):
        await apply_order_status_change(db_session, order, "paid")
    assert len(_FakeClient.calls) == 1
    assert _FakeClient.calls[0][2][HEADER_EVENT] == EVENT_ORDER_PAID


@pytest.mark.asyncio
async def test_webhook_test_ping_ignores_event_checkboxes(db_session):
    await save_outbound_webhook_endpoint(
        db_session,
        enabled=False,
        url="https://hooks.example.com/oshkelosh",
        events=[],
    )
    await db_session.commit()
    _FakeClient.calls = []
    with patch("app.services.outbound_webhooks.httpx.AsyncClient", _FakeClient):
        ok = await send_outbound_webhook_test(db_session)
    assert ok is True
    assert _FakeClient.calls[0][2][HEADER_EVENT] == EVENT_WEBHOOK_TEST


def test_public_site_settings_omit_webhook_secret():
    site = SiteSettings(store_name="Shop")
    with patch("app.services.site_settings.settings") as mock_settings:
        mock_settings.public_app_url = "https://shop.example.com"
        mock_settings.cors_origins = []
        data = site_settings_to_public_dict(site)
    assert "secret" not in data
    assert "webhook" not in str(data).lower()


@pytest.mark.asyncio
class TestAdminWebhooksPage:
    async def test_get_requires_csrf_on_post(self, client: AsyncClient, test_user: User):
        app.state.needs_setup = False
        cookies, _csrf = _admin_session(test_user.id)
        get = await client.get("/admin/webhooks", cookies=cookies)
        assert get.status_code == 200
        assert "Webhooks" in get.text
        assert "Signing secret" in get.text

        denied = await client.post(
            "/admin/webhooks",
            cookies=cookies,
            data={"url": "https://hooks.example.com/x", "csrf_token": "nope"},
        )
        assert denied.status_code == 403

    async def test_save_generates_secret_shown_once(self, client: AsyncClient, test_user: User, db_session):
        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            "/admin/webhooks",
            cookies=cookies,
            data={
                "enabled": "1",
                "url": "https://hooks.example.com/oshkelosh",
                "events": EVENT_ORDER_PAID,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        reveal = response.cookies.get("_oshkelosh_webhook_secret")
        assert reveal

        cookies_with_reveal = {**cookies, "_oshkelosh_webhook_secret": reveal}
        shown = await client.get("/admin/webhooks", cookies=cookies_with_reveal)
        assert shown.status_code == 200
        row = await get_outbound_webhook_endpoint(db_session)
        assert row.secret
        assert row.secret in shown.text

        hidden = await client.get("/admin/webhooks", cookies=cookies)
        assert hidden.status_code == 200
        assert row.secret not in hidden.text
        assert "••••" in hidden.text

    async def test_save_does_not_accept_posted_secret(self, client: AsyncClient, test_user: User, db_session):
        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)
        await client.post(
            "/admin/webhooks",
            cookies=cookies,
            data={
                "url": "https://hooks.example.com/oshkelosh",
                "csrf_token": csrf,
                "secret": "attacker-chosen-secret",
            },
            follow_redirects=False,
        )
        row = await get_outbound_webhook_endpoint(db_session)
        assert row.secret != "attacker-chosen-secret"
        assert row.secret
