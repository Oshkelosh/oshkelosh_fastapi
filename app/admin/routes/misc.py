from fastapi import APIRouter

from app.admin.routes._deps import (
    Request,
    _render_error,
)

router = APIRouter()


@router.get("/error")
async def admin_error_page(request: Request, message: str = "An error occurred"):
    """Render the generic admin error page."""
    return _render_error(request, message)
