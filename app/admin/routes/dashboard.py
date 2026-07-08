from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Any,
    Depends,
    Dict,
    Request,
    _common_ctx,
    _template,
    col,
    datetime,
    func,
    require_admin_session,
    select,
    settings,
    status,
    timedelta,
)

router = APIRouter()


async def _load_dashboard_context(db) -> Dict[str, Any]:
    """Load health and supplier sync summary for the dashboard."""
    from app.services.background_jobs import get_active_supplier_sync_job, job_progress_percent
    from app.services.supplier_catalog_sync import get_last_sync_times, list_syncable_suppliers
    from app.services.system_health import build_health_summary

    health = await build_health_summary(db)
    last_sync: dict[str, Any] = {}
    syncable_suppliers: list[dict[str, Any]] = []
    active_job = None

    if db is not None:
        try:
            last_sync = await get_last_sync_times(db)
            active_job = await get_active_supplier_sync_job(db)
        except Exception:
            pass

    for addon in list_syncable_suppliers():
        syncable_suppliers.append(
            {
                "addon_id": addon.addon_id,
                "addon_name": addon.addon_name,
                "last_sync_at": last_sync.get(addon.addon_id),
            }
        )

    active_job_ctx = None
    if active_job is not None:
        active_job_ctx = {
            "id": active_job.id,
            "status": active_job.status,
            "percent": job_progress_percent(active_job),
            "progress": active_job.progress or {},
        }

    return {
        "health": health,
        "syncable_suppliers": syncable_suppliers,
        "active_sync_job": active_job_ctx,
    }


@router.get("/")
@router.get("/dashboard")
async def admin_dashboard(request: Request, db=Depends(require_admin_session)):
    """Admin dashboard with key metrics."""
    from models.order import Order
    from models.product import Product

    stats: Dict[str, Any] = {
        "total_products": 0,
        "total_orders": 0,
        "total_revenue_cents": 0,
        "recent_orders": [],
        "pending_orders": 0,
        "total_users": 0,
    }

    operational: Dict[str, Any] = {
        "health": None,
        "syncable_suppliers": [],
        "active_sync_job": None,
    }

    if db is not None:
        from models.user import User

        try:
            operational = await _load_dashboard_context(db)
            from app.services.admin_dashboard import fetch_dashboard_stats

            stats.update(await fetch_dashboard_stats(db))

            from models.order_item import OrderItem

            recent_order_ids = (
                select(Order.id)
                .order_by(col(Order.created_at).desc())
                .limit(5)
                .subquery()
            )
            stmt = (
                select(Order, OrderItem.product_name, OrderItem.quantity)
                .join(recent_order_ids, col(Order.id) == recent_order_ids.c.id)
                .join(OrderItem, Order.id == OrderItem.order_id, isouter=True)
                .order_by(col(Order.created_at).desc())
            )
            res = await db.execute(stmt)
            rows = res.all()
            for order, product_name, qty in rows:
                stats["recent_orders"].append(
                    {
                        "id": order.id,
                        "status": order.status,
                        "total_cents": order.total_cents,
                        "created_at": order.created_at,
                        "product_name": product_name or "—",
                        "quantity": qty or 0,
                    }
                )

        except Exception:
            pass

    return _template(
        "dashboard.html",
        **_common_ctx(request, "Dashboard"),
        restart_flag_enabled=settings.addon_install_restart_flag_path is not None,
        restart_flag_path=settings.addon_install_restart_flag_file or "",
        **stats,
        **operational,
    )
