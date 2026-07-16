from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Any,
    Depends,
    Dict,
    Form,
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
REVENUE_TREND_RANGE_OPTIONS = (30, 90, 180)


def _build_revenue_trend_chart(series: dict[str, Any]) -> dict[str, Any]:
    """Prepare a lightweight SVG chart model for the dashboard template."""
    points = list(series.get("days", []))
    width = 800
    height = 200
    left = 60
    right = 20
    top = 30
    bottom = 30
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_cents = max(series.get("max_cents", 0), 0)
    scale_max = max_cents if max_cents > 0 else 1

    chart_points: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        x = left if len(points) == 1 else left + (plot_width * index / (len(points) - 1))
        y = top + plot_height - ((point["revenue_cents"] / scale_max) * plot_height)
        chart_points.append(
            {
                **point,
                "x": round(x, 2),
                "y": round(y, 2),
                "amount": f"${point['revenue_cents'] / 100:,.2f}",
                "short_date": point["date"][5:],
            }
        )

    if chart_points:
        path_d = "M " + " L ".join(f"{point['x']} {point['y']}" for point in chart_points)
        area_d = (
            f"{path_d} L {chart_points[-1]['x']} {top + plot_height} "
            f"L {chart_points[0]['x']} {top + plot_height} Z"
        )
        start_label = chart_points[0]["date"]
        end_label = chart_points[-1]["date"]
    else:
        baseline_y = top + plot_height
        path_d = f"M {left} {baseline_y} L {left + plot_width} {baseline_y}"
        area_d = (
            f"M {left} {baseline_y} L {left + plot_width} {baseline_y} "
            f"L {left + plot_width} {baseline_y} L {left} {baseline_y} Z"
        )
        start_label = ""
        end_label = ""

    midpoint_cents = max_cents // 2 if max_cents > 0 else 0
    return {
        "points": chart_points,
        "path_d": path_d,
        "area_d": area_d,
        "has_revenue": series.get("total_cents", 0) > 0,
        "total_cents": series.get("total_cents", 0),
        "max_cents": max_cents,
        "top_label": f"${max_cents / 100:,.2f}",
        "mid_label": f"${midpoint_cents / 100:,.2f}",
        "baseline_y": top + plot_height,
        "start_label": start_label,
        "end_label": end_label,
        "days": len(points),
    }


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

    selected_range = 30
    requested_range = request.query_params.get("range_days")
    if requested_range is not None:
        try:
            parsed_range = int(requested_range)
        except ValueError:
            parsed_range = selected_range
        if parsed_range in REVENUE_TREND_RANGE_OPTIONS:
            selected_range = parsed_range

    stats: Dict[str, Any] = {
        "total_products": 0,
        "total_orders": 0,
        "total_revenue_cents": 0,
        "revenue_trend": _build_revenue_trend_chart({"days": [], "max_cents": 0, "total_cents": 0}),
        "revenue_trend_days": selected_range,
        "revenue_trend_options": REVENUE_TREND_RANGE_OPTIONS,
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
            from app.services.admin_dashboard import fetch_dashboard_stats, fetch_revenue_trend

            stats.update(await fetch_dashboard_stats(db))
            stats["revenue_trend"] = _build_revenue_trend_chart(
                await fetch_revenue_trend(db, days=selected_range)
            )

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
                        "created_at": str(order.created_at)[:10],
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
        host_self_update_enabled=settings.host_self_update_enabled,
        app_version=settings.app_version,
        **stats,
        **operational,
    )


@router.post("/system/update")
async def admin_host_update(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    confirm: str = Form("off", max_length=8),
    db=Depends(require_admin_session),
):
    """Fast-forward pull the host git repo and request a process restart."""
    from fastapi.responses import RedirectResponse

    from app.admin.routes._deps import _require_csrf, set_flash_cookie
    from app.core.exceptions import ValidationError
    from app.services.host_update import update_host_from_git

    _require_csrf(request, csrf_token)
    resp = RedirectResponse(url=f"{settings.admin_prefix}/dashboard", status_code=302)

    if confirm != "on":
        set_flash_cookie(resp, "Confirm the host update checkbox to continue.")
        return resp

    try:
        result = update_host_from_git()
    except ValidationError as e:
        set_flash_cookie(resp, e.message)
        return resp
    except Exception as e:
        set_flash_cookie(resp, f"Host update failed: {e}")
        return resp

    if db is not None:
        from app.services.audit import admin_request_meta, log_change

        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="update",
            resource_type="host",
            resource_id="oshkelosh",
            changes={
                "branch": result.branch,
                "previous_commit": result.previous_commit,
                "new_commit": result.new_commit,
            },
            ip_address=ip_address,
            detail=(
                f"Host updated on {result.branch}: "
                f"{result.previous_commit[:7]} → {result.new_commit[:7]}"
            ),
        )
        await db.commit()

    msg = (
        f"Oshkelosh updated on {result.branch} "
        f"({result.previous_commit[:7]} → {result.new_commit[:7]}). "
        "Restart the server to load the new code."
    )
    if result.restart_flag_written and result.restart_flag_path:
        msg += f" A restart flag was written to {result.restart_flag_path}."
    set_flash_cookie(resp, msg)
    return resp
