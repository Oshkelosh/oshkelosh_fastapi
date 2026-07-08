"""JWT token helpers shared by auth and SSO flows."""

from models.user import User
from app.core.security import create_access_token, create_refresh_token


def build_token_response(user: User) -> dict:
    """Create a JWT token pair for the given user."""
    extra = {"email": user.email, "role": "admin" if user.is_admin else "user"}
    return {
        "access_token": create_access_token(user.id, extra_claims=extra),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
    }
