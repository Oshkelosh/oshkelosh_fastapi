"""Shared admin auth/template seams usable outside route packages."""

from app.admin.routes._deps import _common_ctx, _require_csrf, require_admin_session
from app.admin.session import set_flash_cookie

__all__ = [
    "_common_ctx",
    "_require_csrf",
    "require_admin_session",
    "set_flash_cookie",
]
