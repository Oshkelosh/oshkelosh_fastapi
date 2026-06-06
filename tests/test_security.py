"""Security regression tests."""

import pytest
from httpx import AsyncClient
from sqlmodel import select

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
