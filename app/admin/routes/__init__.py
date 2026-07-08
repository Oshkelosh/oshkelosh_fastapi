"""Admin HTML route modules composed into a single router."""

from fastapi import APIRouter

from app.admin.routes._deps import _common_ctx, _require_csrf, require_admin_session
from app.admin.session import set_flash_cookie
from . import addons, audit, auth, categories, dashboard, misc, orders, products, settings, users

router = APIRouter()
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(products.router)
router.include_router(categories.router)
router.include_router(users.router)
router.include_router(orders.router)
router.include_router(settings.router)
router.include_router(addons.router)
router.include_router(audit.router)
router.include_router(misc.router)

__all__ = [
    "router",
    "_common_ctx",
    "_require_csrf",
    "require_admin_session",
    "set_flash_cookie",
]
