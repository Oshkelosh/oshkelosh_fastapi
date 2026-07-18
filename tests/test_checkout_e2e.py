"""End-to-end money-path checks: shop currency reaches the PSP charge, and
customer shipping selections survive order create → checkout → read."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.site_settings import update_site_settings


@contextmanager
def _mock_payment_addon():
    mock_addon = AsyncMock()
    mock_addon.addon_id = "mock_payment"
    mock_addon.create_payment = AsyncMock(
        return_value={
            "success": True,
            "checkout_url": "https://pay.test",
            "session_id": "sess_mock",
            "payment_id": "pi_mock",
        }
    )
    with patch(
        "app.services.addons.require_payment_addon",
        return_value=mock_addon,
    ):
        yield mock_addon


async def _login_and_fill_cart(client: AsyncClient, test_user, test_product, test_variant):
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "SecurePass123!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post(
        "/api/v1/cart/items",
        headers=headers,
        json={"product_id": test_product.id, "variant_id": test_variant.id, "quantity": 1},
    )
    return headers


@pytest.mark.asyncio
async def test_shop_currency_flows_to_order_and_charge(
    client: AsyncClient, db_session, test_user, test_product, test_variant
):
    """Site Settings currency ends up on the order AND in the PSP charge call."""
    await update_site_settings(db_session, {"shop_currency": "EUR"})

    headers = await _login_and_fill_cart(client, test_user, test_product, test_variant)
    order_resp = await client.post("/api/v1/orders", headers=headers)
    assert order_resp.status_code == 201, order_resp.text
    order = order_resp.json()
    assert order["currency"].upper() == "EUR"
    assert order["total_cents"] > 0

    with _mock_payment_addon() as addon:
        checkout = await client.post(
            f"/api/v1/orders/{order['id']}/checkout",
            headers=headers,
            json={"shipping_address": {"line1": "1 Main St", "country": "DE"}},
        )
    assert checkout.status_code == 200, checkout.text

    charge_kwargs = addon.create_payment.await_args.kwargs
    assert charge_kwargs["currency"].upper() == "EUR"
    assert charge_kwargs["amount"] > 0
    assert charge_kwargs["order_id"] == str(order["id"])


@pytest.mark.asyncio
async def test_shipping_selections_persist_through_checkout(
    client: AsyncClient, test_user, test_product, test_variant
):
    """Selections set at create are readable; checkout can overwrite them."""
    headers = await _login_and_fill_cart(client, test_user, test_product, test_variant)

    selections = {"printful": "STANDARD"}
    order_resp = await client.post(
        "/api/v1/orders",
        headers=headers,
        json={"shipping_selections": selections},
    )
    assert order_resp.status_code == 201, order_resp.text
    order_id = order_resp.json()["id"]
    assert order_resp.json()["shipping_selections"] == selections

    detail = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert detail.json()["shipping_selections"] == selections

    updated = {"printful": "EXPRESS"}
    with _mock_payment_addon():
        checkout = await client.post(
            f"/api/v1/orders/{order_id}/checkout",
            headers=headers,
            json={"shipping_selections": updated},
        )
    assert checkout.status_code == 200, checkout.text

    detail = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert detail.json()["shipping_selections"] == updated
