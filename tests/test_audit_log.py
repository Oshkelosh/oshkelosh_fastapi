"""Tests for audit logging helpers and admin audit UI."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlmodel import col

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.main import app
from app.services.audit import (
    diff_fields,
    log_change,
    redact_changes,
    resource_admin_url,
)
from models.audit_log import AuditLog
from models.order import Order
from models.user import User


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


class TestAuditHelpers:
    def test_diff_fields_returns_only_changes(self):
        before = {"name": "Old", "status": "draft", "price_cents": 100}
        after = {"name": "New", "status": "draft", "price_cents": 200}
        assert diff_fields(before, after) == {
            "name": {"from": "Old", "to": "New"},
            "price_cents": {"from": 100, "to": 200},
        }

    def test_redact_changes_masks_secrets(self):
        changes = {
            "api_key": {"from": "old-key", "to": "new-key"},
            "name": {"from": "a", "to": "b"},
            "config": {"client_secret": "hidden"},
        }
        redacted = redact_changes(changes)
        assert redacted["api_key"] == {"from": "[redacted]", "to": "[changed]"}
        assert redacted["name"] == {"from": "a", "to": "b"}
        assert redacted["config"]["client_secret"] == "[redacted]"

    def test_resource_admin_url_maps_known_types(self):
        assert resource_admin_url("product", "5") == "/admin/products/5"
        assert resource_admin_url("order", "12") == "/admin/orders/12"
        assert resource_admin_url("user", "3") == "/admin/users/3"
        assert resource_admin_url("addon", "mangopay") == "/admin/addons/mangopay/configure"
        assert (
            resource_admin_url("notification_template", "order_paid/email")
            == "/admin/notifications/messages/order_paid/email"
        )
        assert resource_admin_url("site_settings", "1") == "/admin/settings"


@pytest.mark.asyncio
async def test_log_change_redacts_secrets(db_session):
    await log_change(
        db_session,
        actor_user_id=1,
        action="configure",
        resource_type="addon",
        resource_id="test",
        changes={"api_key": {"from": "a", "to": "b"}},
    )
    await db_session.commit()

    result = await db_session.execute(select(AuditLog))
    entry = result.scalars().first()
    assert entry is not None
    assert entry.changes["api_key"] == {"from": "[redacted]", "to": "[changed]"}


class TestAdminAuditInstrumentation:
    async def test_product_update_writes_audit_entry(
        self, client: AsyncClient, test_user: User, test_product, db_session
    ):
        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)

        response = await client.post(
            f"/admin/products/{test_product.id}",
            cookies=cookies,
            data={
                "name": "Updated Product Name",
                "description": test_product.description or "",
                "slug": test_product.slug or "",
                "meta_title": "",
                "meta_description": "",
                "price_cents": test_product.price_cents,
                "compare_at_price_cents": "",
                "sku": test_product.sku or "",
                "inventory_quantity": test_product.inventory_quantity,
                "status": "published",
                "category_id": test_product.category_id or "",
                "supplier_value": "",
                "supplier_product_id": "",
                "supplier_variant_id": "",
                "tags": "[]",
                "product_options": "{}",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 302

        result = await db_session.execute(
            select(AuditLog).where(
                col(AuditLog.resource_type) == "product",
                col(AuditLog.resource_id) == str(test_product.id),
                col(AuditLog.action) == "update",
            )
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.changes is not None
        assert entry.changes["name"] == {"from": "Test Product", "to": "Updated Product Name"}

    async def test_order_status_change_writes_audit_entry(
        self, client: AsyncClient, test_user: User, test_product, db_session
    ):
        app.state.needs_setup = False
        order = Order(
            user_id=test_user.id,
            status="pending",
            total_cents=test_product.price_cents,
            tax_cents=0,
            shipping_cents=0,
            currency="usd",
        )
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            f"/admin/orders/{order.id}/status",
            cookies=cookies,
            data={"status": "paid", "csrf_token": csrf},
        )
        assert response.status_code == 302

        result = await db_session.execute(
            select(AuditLog).where(
                col(AuditLog.resource_type) == "order",
                col(AuditLog.resource_id) == str(order.id),
            )
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.changes["status"] == {"from": "pending", "to": "paid"}

    async def test_user_update_password_not_stored_in_audit(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        cookies, csrf = _admin_session(test_user.id)

        response = await client.post(
            f"/admin/users/{test_user.id}",
            cookies=cookies,
            data={
                "password": "NewSecurePass123!",
                "full_name": test_user.full_name or "",
                "phone": "",
                "line1": "",
                "line2": "",
                "city": "",
                "state": "",
                "postal_code": "",
                "country": "",
                "verified": "on",
                "is_admin": "on",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 302

        result = await db_session.execute(
            select(AuditLog).where(
                col(AuditLog.resource_type) == "user",
                col(AuditLog.resource_id) == str(test_user.id),
                col(AuditLog.action) == "update",
            )
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.changes is not None
        assert entry.changes["password"] == {"from": "[redacted]", "to": "[changed]"}
        assert "NewSecurePass123!" not in str(entry.changes)


class TestAdminAuditPages:
    async def test_audit_list_renders_entries(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        await log_change(
            db_session,
            actor_user_id=test_user.id,
            action="create",
            resource_type="product",
            resource_id="1",
            detail="Created product 'Demo'",
        )
        await db_session.commit()

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get("/admin/audit", cookies=cookies)
        assert response.status_code == 200
        assert "Audit Log" in response.text
        assert "Created product" in response.text
        assert "Test User" in response.text

    async def test_audit_list_filters_by_resource_type(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        await log_change(
            db_session,
            actor_user_id=test_user.id,
            action="create",
            resource_type="product",
            resource_id="1",
            detail="Product entry",
        )
        await log_change(
            db_session,
            actor_user_id=test_user.id,
            action="update",
            resource_type="order",
            resource_id="2",
            detail="Order entry",
        )
        await db_session.commit()

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get(
            "/admin/audit?resource_type=product",
            cookies=cookies,
        )
        assert response.status_code == 200
        assert "Product entry" in response.text
        assert "Order entry" not in response.text

    async def test_audit_detail_shows_changes(
        self, client: AsyncClient, test_user: User, db_session
    ):
        app.state.needs_setup = False
        entry = await log_change(
            db_session,
            actor_user_id=test_user.id,
            action="update",
            resource_type="product",
            resource_id="9",
            changes={"status": {"from": "draft", "to": "published"}},
            detail="Updated product",
        )
        await db_session.commit()
        assert entry.id is not None

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get(f"/admin/audit/{entry.id}", cookies=cookies)
        assert response.status_code == 200
        assert "Updated product" in response.text
        assert "status" in response.text
        assert "draft" in response.text
        assert "published" in response.text


class TestAdminCategoryAudit:
    async def test_create_category_writes_audit_entry(
        self, client: AsyncClient, test_user: User, db_session
    ):
        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            "/admin/categories",
            cookies=cookies,
            data={"name": "Gadgets", "slug": "gadgets", "sort_order": "1", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 302

        result = await db_session.execute(
            select(AuditLog).where(
                col(AuditLog.resource_type) == "category",
                col(AuditLog.action) == "create",
            )
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.actor_user_id == test_user.id
