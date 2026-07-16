"""Tests for authentication endpoints."""

from httpx import AsyncClient

SAMPLE_ADDRESS = {
    "line1": "123 Main St",
    "city": "Portland",
    "state": "OR",
    "postal_code": "97201",
    "country": "US",
}


def _register_payload(email: str, **extra):
    return {
        "email": email,
        "password": "SecurePass123!",
        "full_name": extra.pop("full_name", "Test User"),
        "default_shipping_address": SAMPLE_ADDRESS,
        "billing_same_as_shipping": True,
        **extra,
    }


class TestAuthRegistration:
    """Test user registration endpoints."""

    async def test_register_user(self, client: AsyncClient):
        """Test that a user can register and receives a session."""
        response = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("newuser@example.com", full_name="New User"),
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["default_shipping_address"]["line1"] == "123 Main St"
        assert data["user"]["default_billing_address"]["line1"] == "123 Main St"

    async def test_register_duplicate_email(self, client: AsyncClient):
        """Test that registering with a duplicate email fails."""
        await client.post(
            "/api/v1/auth/register",
            json=_register_payload("dup@example.com", full_name="Dup User"),
        )
        response = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("dup@example.com", full_name="Dup User Again"),
        )
        assert response.status_code in (400, 409, 422)

    async def test_register_invalid_email(self, client: AsyncClient):
        """Test that registering with an invalid email fails."""
        response = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("not-an-email", full_name="Bad Email User"),
        )
        assert response.status_code == 422

    async def test_register_weak_password(self, client: AsyncClient):
        """Test that registering with a weak password fails."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "weak@example.com",
                "password": "123",
                "full_name": "Weak Password",
                "default_shipping_address": SAMPLE_ADDRESS,
                "billing_same_as_shipping": True,
            },
        )
        assert response.status_code == 422

    async def test_register_requires_address(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "noaddr@example.com",
                "password": "SecurePass123!",
                "full_name": "No Address",
            },
        )
        assert response.status_code == 422

    async def test_register_cannot_set_admin(self, client: AsyncClient):
        """Extra fields like is_admin are rejected or ignored."""
        response = await client.post(
            "/api/v1/auth/register",
            json=_register_payload(
                "noradmin@example.com",
                full_name="Normal User",
                is_admin=True,
            ),
        )
        assert response.status_code == 201
        assert response.json()["user"]["is_admin"] is False

    async def test_register_normalizes_email(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("  MixedCase@Example.COM  ", full_name="Norm"),
        )
        assert response.status_code == 201
        assert response.json()["user"]["email"] == "mixedcase@example.com"


class TestAuthLogin:
    """Test login endpoints."""

    async def test_login_success(self, client: AsyncClient):
        """Test that a user can log in."""
        await client.post(
            "/api/v1/auth/register",
            json=_register_payload("loginuser@example.com", full_name="Login User"),
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "loginuser@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code in (200, 201)
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient):
        """Test that login fails with wrong password."""
        await client.post(
            "/api/v1/auth/register",
            json=_register_payload("wrongpass@example.com", full_name="Wrong Pass"),
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpass@example.com", "password": "WrongPassword"},
        )
        assert response.status_code == 401


class TestAuthMe:
    """Test get current user endpoint."""

    async def test_get_current_user(self, client: AsyncClient):
        """Test getting current user profile."""
        register = await client.post(
            "/api/v1/auth/register",
            json=_register_payload("meuser@example.com", full_name="Me User"),
        )
        token = register.json()["access_token"]
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "meuser@example.com"

    async def test_get_current_user_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated request fails."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
