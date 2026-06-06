"""Mount addon-contributed API and admin routers onto the FastAPI app."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from app.addons.registry import addon_registry

logger = logging.getLogger(__name__)

_ADDON_OPENAPI_TAGS = {
    "supplier": "addons-suppliers",
    "payment": "addons-payments",
    "notification": "addons-notifications",
    "frontend": "addons-frontends",
    "tool": "addons-tools",
}


def _tag_addon_routers(router: APIRouter, tag: str) -> None:
    """Apply OpenAPI tag to all routes on an addon router (for per-route metadata)."""
    for route in router.routes:
        existing = list(getattr(route, "tags", None) or [])
        if tag not in existing:
            route.tags = [*existing, tag]


def mount_addon_routers(
    app: FastAPI,
    api_prefix: str,
    admin_router: APIRouter,
) -> None:
    """Include every registered addon's public and admin routers."""
    addon_registry.register_all()

    for addon in addon_registry._registry.values():
        tag = _ADDON_OPENAPI_TAGS.get(addon.addon_category, f"addons-{addon.addon_category}")
        api_mount = addon.api_mount_prefix()

        for router in addon.get_routers():
            _tag_addon_routers(router, tag)
            full_prefix = f"{api_prefix}{api_mount}"
            app.include_router(router, prefix=full_prefix, tags=[tag])
            logger.info("Mounted addon API router at %s", full_prefix)

        admin_mount = addon.admin_mount_prefix()
        for router in addon.get_admin_routes():
            full_prefix = f"{admin_mount}"
            admin_router.include_router(router, prefix=full_prefix)
            logger.info("Mounted addon admin router at /admin%s", full_prefix)

        static_path = addon.get_admin_static()
        if static_path:
            static_dir = Path(static_path)
            if static_dir.is_dir():
                mount_name = f"addon_static_{addon.addon_id}"
                admin_router.mount(
                    f"{admin_mount}/static",
                    StaticFiles(directory=str(static_dir)),
                    name=mount_name,
                )
