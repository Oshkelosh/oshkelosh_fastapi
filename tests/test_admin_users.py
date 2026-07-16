"""HTML admin user maintenance page tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.core.security import hash_password
from app.main import app
from models.order import Order
from models.user import User


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


@pytest.mark.asyncio
class TestAdminUserMaintenancePage:
    async def test_edit_page_renders_html(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=2500,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get(
            f"/admin/users/{test_user.id}",
            cookies=cookies,
        )
        assert response.status_code == 200
        assert "application/json" not in response.headers.get("content-type", "")
        body = response.text
        assert test_user.email in body
        assert "Account details" in body
        assert "Recent orders" in body
        assert f"#{order.id}" in body
        assert "Save changes" in body
        # Admin session user must remain in header (edit_user must not override it)
        assert "Logout" in body

    async def test_edit_page_survives_malformed_address_json(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        customer = User(
            email="broken-address@example.com",
            password_hash=hash_password("SecurePass123!"),
            full_name="Broken Address",
            verified=True,
            banned=False,
            is_admin=False,
            default_shipping_address='{"line1": "not a real dict storage"}',  # type: ignore[arg-type]
            default_billing_address=["legacy", "list"],  # type: ignore[arg-type]
        )
        db_session.add(customer)
        await db_session.flush()
        await db_session.refresh(customer)

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get(
            f"/admin/users/{customer.id}",
            cookies=cookies,
        )
        assert response.status_code == 200
        assert "broken-address@example.com" in response.text
        assert "internal_error" not in response.text

    async def test_html_promote_second_admin_shows_form_error(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        customer = User(
            email="customer@example.com",
            password_hash=hash_password("SecurePass123!"),
            full_name="Customer",
            verified=True,
            banned=False,
            is_admin=False,
        )
        db_session.add(customer)
        await db_session.flush()
        await db_session.refresh(customer)

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/users/{customer.id}",
            cookies=cookies,
            data={
                "full_name": "Customer",
                "phone": "",
                "line1": "",
                "line2": "",
                "city": "",
                "state": "",
                "postal_code": "",
                "country": "",
                "billing_line1": "",
                "billing_line2": "",
                "billing_city": "",
                "billing_state": "",
                "billing_postal_code": "",
                "billing_country": "",
                "verified": "on",
                "is_admin": "on",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200
        assert "Only one admin user is allowed" in response.text
        await db_session.refresh(customer)
        assert customer.is_admin is False

    async def test_html_self_demote_blocked(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/users/{test_user.id}",
            cookies=cookies,
            data={
                "full_name": test_user.full_name or "",
                "phone": "",
                "line1": "",
                "line2": "",
                "city": "",
                "state": "",
                "postal_code": "",
                "country": "",
                "billing_line1": "",
                "billing_line2": "",
                "billing_city": "",
                "billing_state": "",
                "billing_postal_code": "",
                "billing_country": "",
                "verified": "on",
                # is_admin intentionally omitted → unchecked
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200
        assert "You cannot remove your own admin privileges" in response.text
        await db_session.refresh(test_user)
        assert test_user.is_admin is True

    async def test_new_user_page_keeps_admin_header(
        self, client: AsyncClient, test_user: User
    ):
        app.state.needs_setup = False
        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get("/admin/users/new", cookies=cookies)
        assert response.status_code == 200
        assert "New User" in response.text
        assert "Logout" in response.text
        assert "Create user" in response.text
