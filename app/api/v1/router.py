"""
API v1 router – root router for all /api/v1/* endpoints.

Includes all feature sub-routers: auth, products, categories, cart,
orders, R2 media, and admin endpoints.
"""

from fastapi import APIRouter

from app.api.v1.routers import (
    admin,
    auth,
    cart,
    categories,
    orders,
    products,
    r2,
    storefront,
)

router = APIRouter()

# Public endpoints
router.include_router(auth.router, tags=["auth"])
router.include_router(products.router, tags=["products"])
router.include_router(categories.router, tags=["categories"])
router.include_router(cart.router, tags=["cart"])
router.include_router(orders.router, tags=["orders"])
router.include_router(r2.router, tags=["media"])
router.include_router(storefront.router, tags=["storefront"])

# Admin endpoints
router.include_router(admin.router, tags=["admin"])


@router.get("/health", tags=["status"])
async def api_health():
    """Confirm the API is responding."""
    from app.config import settings

    if settings.app_env == "production" and not settings.debug:
        return {"status": "ok"}
    return {"status": "running", "version": "v1"}
