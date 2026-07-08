from fastapi import APIRouter

from app.admin import limits as L
from app.config import settings
from app.admin.routes._deps import (
    Depends,
    Form,
    Optional,
    Query,
    RedirectResponse,
    Request,
    _common_ctx,
    _render_error,
    _require_csrf,
    _template,
    col,
    func,
    json,
    require_admin_session,
    select,
    set_flash_cookie,
    status,
)

router = APIRouter()

@router.get("/orders")
async def admin_orders_list(
    request: Request,
    page: int = Query(1, ge=1),
    status_filter: Optional[str] = Query(None),
    db=Depends(require_admin_session),
):
    """List orders with pagination and optional status filter."""
    from models.order import Order

    PAGE_SIZE = 20
    offset = (page - 1) * PAGE_SIZE

    stmt = select(Order).order_by(col(Order.created_at).desc()).offset(offset).limit(PAGE_SIZE)
    count_stmt = select(func.count(Order.id))

    if status_filter and status_filter != "all":
        stmt = stmt.where(col(Order.status) == status_filter)
        count_stmt = count_stmt.where(col(Order.status) == status_filter)

    total = 0
    items = []

    if db is not None:
        try:
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0

            result = await db.execute(stmt)
            items = result.scalars().all()
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    status_options = ["pending", "paid", "shipped", "delivered", "cancelled"]

    return _template(
        "orders.html",
        **_common_ctx(request, "Orders"),
        items=items,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        status_filter=status_filter,
        status_options=status_options,
    )


@router.get("/orders/{order_id}")
async def admin_order_detail(request: Request, order_id: int, db=Depends(require_admin_session)):
    """Show a single order with its line items."""
    from models.order import Order
    from models.order_item import OrderItem

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not order:
        return _render_error(request, "Order not found", status_code=404)

    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(col(OrderItem.id).asc())
    )
    items = items_result.scalars().all()

    fulfillment_notes = []
    if order.notes:
        for line in order.notes.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                fulfillment_notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    from app.services.commerce import allowed_next_statuses, apply_order_status_change

    return _template(
        "order_detail.html",
        **_common_ctx(request, f"Order #{order.id}"),
        order=order,
        order_items=items,
        fulfillment_notes=fulfillment_notes,
        allowed_statuses=sorted(allowed_next_statuses(order.status)),
    )


@router.post("/orders/{order_id}/status")
async def admin_order_update_status(
    request: Request,
    order_id: int,
    status: str = Form(...),
    tracking_number: str = Form(""),
    tracking_url: str = Form(""),
    carrier: str = Form(""),
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    """Update the status of an order."""
    from fastapi.responses import RedirectResponse
    from models.order import Order

    _require_csrf(request, csrf_token)

    from app.services.commerce import (
        VALID_TRANSITIONS,
        apply_order_status_change,
        apply_order_tracking,
        cancel_order_as_admin,
    )

    if status not in VALID_TRANSITIONS:
        all_statuses = sorted(VALID_TRANSITIONS.keys())
        return _render_error(
            request,
            f"Invalid status. Must be one of: {', '.join(all_statuses)}",
        )

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not order:
        return _render_error(request, "Order not found", status_code=404)

    allowed = VALID_TRANSITIONS.get(order.status, frozenset())
    if status not in allowed:
        return _render_error(
            request,
            f"Cannot transition from '{order.status}' to '{status}'",
        )

    old_status = order.status
    if status == "shipped" or tracking_number or tracking_url or carrier:
        apply_order_tracking(
            order,
            tracking_number=tracking_number or None,
            tracking_url=tracking_url or None,
            carrier=carrier or None,
        )
    if status == "cancelled":
        from app.core.exceptions import ValidationError

        try:
            await cancel_order_as_admin(db, order)
        except ValidationError as exc:
            return _render_error(request, exc.message)
    else:
        await apply_order_status_change(db, order, status)

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="order",
        resource_id=order.id,
        changes={"status": {"from": old_status, "to": status}},
        ip_address=ip_address,
        detail=f"Order #{order.id} status changed from '{old_status}' to '{status}'",
    )
    await db.commit()

    resp = RedirectResponse(url=f"{settings.admin_prefix}/orders/{order.id}", status_code=302)
    set_flash_cookie(
        resp,
        f"Order #{order.id} status changed from '{old_status}' to '{status}'",
    )
    return resp


