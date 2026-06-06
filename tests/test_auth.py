"""Tests for authentication endpoints."""

from httpx import AsyncClient


class TestAuthRegistration:
    """Test user registration endpoints."""

    async def test_register_user(self, client: AsyncClient):
        """Test that a user can register."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "full_name": "New User",
        })
        assert response.status_code == 200 or response.status_code == 201

    async def test_register_duplicate_email(self, client: AsyncClient):
        """Test that registering with a duplicate email fails."""
        await client.post("/api/v1/auth/register", json={
            "email": "dup@example.com",
            "password": "SecurePass123!",
            "full_name": "Dup User",
        })
        response = await client.post("/api/v1/auth/register", json={
            "email": "dup@example.com",
            "password": "SecurePass123!",
            "full_name": "Dup User Again",
        })
        assert response.status_code in (400, 409, 422)

    async def test_register_invalid_email(self, client: AsyncClient):
        """Test that registering with an invalid email fails."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "SecurePass123!",
            "full_name": "Bad Email User",
        })
        assert response.status_code == 422

    async def test_register_weak_password(self, client: AsyncClient):
        """Test that registering with a weak password fails."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "weak@example.com",
            "password": "123",
            "full_name": "Weak Password",
        })
        assert response.status_code == 422

    async def test_register_cannot_set_admin(self, client: AsyncClient):
        """Extra fields like is_admin are rejected or ignored."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "noradmin@example.com",
            "password": "SecurePass123!",
            "full_name": "Normal User",
            "is_admin": True,
        })
        assert response.status_code in (200, 201)
        assert response.json()["is_admin"] is False


class TestAuthLogin:
    """Test login endpoints."""

    async def test_login_success(self, client: AsyncClient):
        """Test that a user can log in."""
        # Register first
        await client.post("/api/v1/auth/register", json={
            "email": "loginuser@example.com",
            "password": "SecurePass123!",
            "full_name": "Login User",
        })
        response = await client.post("/api/v1/auth/login", json={
            "email": "loginuser@example.com",
            "password": "SecurePass123!",
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient):
        """Test that login fails with wrong password."""
        await client.post("/api/v1/auth/register", json={
            "email": "wrongpass@example.com",
            "password": "SecurePass123!",
            "full_name": "Wrong Pass",
        })
        response = await client.post("/api/v1/auth/login", json={
            "email": "wrongpass@example.com",
            "password": "WrongPassword",
        })
        assert response.status_code == 401


class TestAuthMe:
    """Test get current user endpoint."""

    async def test_get_current_user(self, client: AsyncClient):
        """Test getting current user profile."""
        # Register and login
        await client.post("/api/v1/auth/register", json={
            "email": "meuser@example.com",
            "password": "SecurePass123!",
            "full_name": "Me User",
        })
        login = await client.post("/api/v1/auth/login", json={
            "email": "meuser@example.com",
            "password": "SecurePass123!",
        })
        token = login.json()["access_token"]
        response = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "meuser@example.com"

    async def test_get_current_user_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated request fails."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
