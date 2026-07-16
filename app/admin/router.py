"""
Admin router – root router for all /admin/* endpoints.

Mounts:
  - Jinja2-rendered routes from app.admin.routes
  - Static assets (CSS) from app.admin.static/
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles

from app.admin.routes import router as routes_router

router = APIRouter()

_static_dir = Path(__file__).resolve().parent / "static"
router.mount("/static", StaticFiles(directory=str(_static_dir)), name="admin_static")

router.include_router(routes_router)
