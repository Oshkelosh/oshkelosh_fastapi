"""Admin JSON API — scheduled maintenance job endpoints (cron entrypoints).

All interactive administration happens in the server-rendered admin panel
(``app/admin/``). These endpoints exist so production schedulers can trigger
maintenance jobs with an admin JWT (see README "Scheduled maintenance").
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.dependencies import CurrentUser, get_admin_user
from app.db.connection import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


class AbandonedCartJobResponse(BaseModel):
    scanned: int
    sent: int
    skipped: int
    message: str


@router.post("/jobs/abandoned-cart", response_model=AbandonedCartJobResponse)
async def admin_run_abandoned_cart_job(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> AbandonedCartJobResponse:
    """Process stale carts and send abandoned-cart reminders (cron entrypoint)."""
    from app.services.abandoned_cart import process_abandoned_carts

    result = await process_abandoned_carts(session)
    return AbandonedCartJobResponse(
        scanned=result.scanned,
        sent=result.sent,
        skipped=result.skipped,
        message=result.summary_message(),
    )


class PendingOrderCleanupResponse(BaseModel):
    scanned: int
    cancelled: int
    skipped: int
    message: str


@router.post("/jobs/pending-orders", response_model=PendingOrderCleanupResponse)
async def admin_run_pending_order_cleanup_job(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> PendingOrderCleanupResponse:
    """Cancel stale pending orders and restore reserved inventory."""
    from app.services.pending_order_cleanup import process_stale_pending_orders

    result = await process_stale_pending_orders(session)
    return PendingOrderCleanupResponse(
        scanned=result.scanned,
        cancelled=result.cancelled,
        skipped=result.skipped,
        message=result.summary_message(),
    )
