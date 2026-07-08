"""Security regression tests."""

import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.db.connection import get_session
from models.user import User


class TestRegistrationSecurity:
    async def test_register_rejects_is_admin_in_body(self, client: AsyncClient, db_session):
        """Clients cannot self-assign admin via registration."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "hacker@example.com",
                "password": "SecurePass123!",
                "full_name": "Hacker",
                "is_admin": True,
            },
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["is_admin"] is False

        result = await db_session.execute(
            select(User).where(User.email == "hacker@example.com")
        )
        user = result.scalar_one()
        assert user.is_admin is False

    async def test_demoted_admin_token_rejected(
        self, client: AsyncClient, db_session, test_user: User
    ):
        """Admin API rejects users demoted after token issuance."""
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        token = login.json()["access_token"]

        test_user.is_admin = False
        db_session.add(test_user)
        await db_session.commit()

        response = await client.get(
            "/api/v1/products",
            headers={"Authorization": f"Bearer {token}"},
            params={"status": "draft"},
        )
        assert response.status_code == 422
        response_admin = await client.post(
            "/api/v1/products",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Blocked",
                "price_cents": 100,
                "status": "draft",
            },
        )
        assert response_admin.status_code == 403


class TestAdminLoginSecurity:
    async def test_admin_login_requires_valid_csrf(self, client: AsyncClient, test_user):
        page = await client.get("/admin/login")
        assert page.status_code == 200

        response = await client.post(
            "/admin/login",
            data={
                "email": test_user.email,
                "password": "SecurePass123!",
                "csrf_token": "wrong-token",
            },
            follow_redirects=False,
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid CSRF token"

    async def test_admin_prefix_login_and_product_create_flow(
        self, db_session, test_user, test_category, monkeypatch
    ):
        from app.config import settings
        from app.main import create_app

        original_prefix = settings.admin_prefix
        monkeypatch.setattr(settings, "admin_prefix", "/control")
        custom_app = create_app()
        custom_app.state.needs_setup = False

        async def override_session():
            try:
                yield db_session
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                raise

        custom_app.dependency_overrides[get_session] = override_session
        transport = ASGITransport(app=custom_app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                page = await client.get("/control/login")
                assert page.status_code == 200
                assert 'action="/control/login"' in page.text
                match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
                assert match is not None

                login = await client.post(
                    "/control/login",
                    data={
                        "email": test_user.email,
                        "password": "SecurePass123!",
                        "csrf_token": match.group(1),
                    },
                    follow_redirects=False,
                )
                assert login.status_code == 302
                assert login.headers["location"] == "/control/dashboard"

                new_page = await client.get("/control/products/new")
                assert new_page.status_code == 200
                assert 'action="/control/products"' in new_page.text
                match = re.search(r'name="csrf_token" value="([^"]+)"', new_page.text)
                assert match is not None

                create = await client.post(
                    "/control/products",
                    data={
                        "name": "Prefixed Product",
                        "description": "",
                        "slug": "",
                        "meta_title": "",
                        "meta_description": "",
                        "price_cents": "1299",
                        "compare_at_price_cents": "",
                        "sku": "PREFIX-001",
                        "inventory_quantity": "5",
                        "status": "draft",
                        "category_id": str(test_category.id),
                        "supplier_value": "",
                        "supplier_product_id": "",
                        "supplier_variant_id": "",
                        "tags": "[]",
                        "product_options": "{}",
                        "csrf_token": match.group(1),
                    },
                    follow_redirects=False,
                )
                assert create.status_code == 302
                assert create.headers["location"].startswith("/control/products/")

                detail = await client.get(create.headers["location"])
                assert detail.status_code == 200
                assert 'href="/control/products"' in detail.text
        finally:
            custom_app.dependency_overrides.clear()
            monkeypatch.setattr(settings, "admin_prefix", original_prefix)

    async def test_stale_needs_setup_state_rechecks_database_truth(
        self, db_session, test_user
    ):
        from app.main import create_app

        custom_app = create_app()
        custom_app.state.needs_setup = True

        async def override_session():
            try:
                yield db_session
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                raise

        custom_app.dependency_overrides[get_session] = override_session
        transport = ASGITransport(app=custom_app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                login_page = await client.get("/admin/login")
                assert login_page.status_code == 200
                assert custom_app.state.needs_setup is False
        finally:
            custom_app.dependency_overrides.clear()


class TestSingleAdminConstraint:
    async def test_admin_create_user_rejects_second_admin(self, client: AsyncClient, test_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "SecurePass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = await client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "second-admin@example.com",
                "password": "SecurePass123!",
                "full_name": "Second Admin",
                "is_admin": True,
                "verified": True,
                "banned": False,
            },
        )
        assert response.status_code == 422
        assert response.json()["message"] == "Only one admin user is allowed"
