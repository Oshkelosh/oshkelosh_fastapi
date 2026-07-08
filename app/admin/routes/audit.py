from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    Query,
    Request,
    _common_ctx,
    _render_error,
    _template,
    col,
    datetime,
    func,
    json,
    require_admin_session,
    select,
    timedelta,
    timezone,
    urlencode,
)

router = APIRouter()

_AUDIT_ACTION_OPTIONS = (
    "create",
    "update",
    "delete",
    "install",
    "configure",
    "supplier_catalog_sync",
    "reset",
)

_AUDIT_RESOURCE_TYPE_OPTIONS = (
    "product",
    "user",
    "order",
    "site_settings",
    "category",
    "notification_template",
    "supplier",
    "addon",
)


def _audit_filter_params(
    *,
    action: str = "",
    resource_type: str = "",
    actor: str = "",
    resource_id: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, str]:
    params: dict[str, str] = {}
    if action:
        params["action"] = action
    if resource_type:
        params["resource_type"] = resource_type
    if actor:
        params["actor"] = actor
    if resource_id:
        params["resource_id"] = resource_id
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    return params


def _audit_list_query(page: int, filters: dict[str, str]) -> str:
    params = {"page": str(page), **filters}
    return urlencode(params)


def _parse_audit_date(value: str, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if end_of_day:
        return parsed + timedelta(days=1)
    return parsed


@router.get("/audit")
async def admin_audit_list(
    request: Request,
    page: int = Query(1, ge=1),
    action: str = Query("", max_length=50),
    resource_type: str = Query("", max_length=50),
    actor: str = Query("", max_length=255),
    resource_id: str = Query("", max_length=64),
    date_from: str = Query("", max_length=10),
    date_to: str = Query("", max_length=10),
    db=Depends(require_admin_session),
):
    """Read-only audit trail with filters."""
    from app.services.audit import resource_admin_url
    from models.audit_log import AuditLog
    from models.user import User

    PAGE_SIZE = 25
    offset = (page - 1) * PAGE_SIZE
    filters = _audit_filter_params(
        action=action,
        resource_type=resource_type,
        actor=actor,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
    )

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        stmt = select(AuditLog)
        count_stmt = select(func.count(AuditLog.id))

        if action:
            stmt = stmt.where(col(AuditLog.action) == action)
            count_stmt = count_stmt.where(col(AuditLog.action) == action)
        if resource_type:
            stmt = stmt.where(col(AuditLog.resource_type) == resource_type)
            count_stmt = count_stmt.where(col(AuditLog.resource_type) == resource_type)
        if resource_id:
            stmt = stmt.where(col(AuditLog.resource_id) == resource_id)
            count_stmt = count_stmt.where(col(AuditLog.resource_id) == resource_id)

        parsed_from = _parse_audit_date(date_from)
        if parsed_from is not None:
            stmt = stmt.where(col(AuditLog.created_at) >= parsed_from)
            count_stmt = count_stmt.where(col(AuditLog.created_at) >= parsed_from)

        parsed_to = _parse_audit_date(date_to, end_of_day=True)
        if parsed_to is not None:
            stmt = stmt.where(col(AuditLog.created_at) < parsed_to)
            count_stmt = count_stmt.where(col(AuditLog.created_at) < parsed_to)

        if actor:
            pattern = f"%{actor}%"
            actor_result = await db.execute(
                select(User.id).where(
                    col(User.email).ilike(pattern) | col(User.full_name).ilike(pattern)
                )
            )
            actor_ids = [row[0] for row in actor_result.all()]
            if not actor_ids:
                entries: list[AuditLog] = []
                total = 0
            else:
                stmt = stmt.where(col(AuditLog.actor_user_id).in_(actor_ids))
                count_stmt = count_stmt.where(col(AuditLog.actor_user_id).in_(actor_ids))
                count_result = await db.execute(count_stmt)
                total = count_result.scalar() or 0
                result = await db.execute(
                    stmt.order_by(col(AuditLog.created_at).desc())
                    .offset(offset)
                    .limit(PAGE_SIZE)
                )
                entries = list(result.scalars().all())
        else:
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0
            result = await db.execute(
                stmt.order_by(col(AuditLog.created_at).desc())
                .offset(offset)
                .limit(PAGE_SIZE)
            )
            entries = list(result.scalars().all())

        actor_ids = {entry.actor_user_id for entry in entries if entry.actor_user_id}
        actors: dict[int, User] = {}
        if actor_ids:
            actor_result = await db.execute(select(User).where(col(User.id).in_(actor_ids)))
            actors = {user.id: user for user in actor_result.scalars().all() if user.id is not None}

        resource_urls = {
            entry.id: resource_admin_url(entry.resource_type, entry.resource_id)
            for entry in entries
            if entry.id is not None
        }
    except Exception as exc:
        return _render_error(request, f"Failed to load audit log: {exc}")

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    range_start = offset + 1 if total > 0 else 0
    range_end = min(offset + len(entries), total)
    current_list_url = f"/admin/audit?{_audit_list_query(page, filters)}"
    prev_url = (
        f"/admin/audit?{_audit_list_query(page - 1, filters)}"
        if page > 1
        else None
    )
    next_url = (
        f"/admin/audit?{_audit_list_query(page + 1, filters)}"
        if page < total_pages
        else None
    )

    return _template(
        "audit.html",
        **_common_ctx(request, "Audit Log"),
        entries=entries,
        actors=actors,
        resource_urls=resource_urls,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        range_start=range_start,
        range_end=range_end,
        filter_action=action,
        filter_resource_type=resource_type,
        filter_actor=actor,
        filter_resource_id=resource_id,
        filter_date_from=date_from,
        filter_date_to=date_to,
        action_options=_AUDIT_ACTION_OPTIONS,
        resource_type_options=_AUDIT_RESOURCE_TYPE_OPTIONS,
        filter_query=urlencode(filters),
        current_list_url=current_list_url,
        prev_url=prev_url,
        next_url=next_url,
    )


@router.get("/audit/{entry_id}")
async def admin_audit_detail(
    request: Request,
    entry_id: int,
    db=Depends(require_admin_session),
):
    """Show a single audit log entry."""
    import json as json_module

    from app.services.audit import resource_admin_url
    from models.audit_log import AuditLog
    from models.user import User

    if not db:
        return _render_error(request, "Database unavailable")

    entry = await db.get(AuditLog, entry_id)
    if not entry:
        return _render_error(request, "Audit entry not found", status_code=404)

    actor = None
    if entry.actor_user_id:
        actor = await db.get(User, entry.actor_user_id)

    changes_json = (
        json_module.dumps(entry.changes, indent=2, sort_keys=True)
        if entry.changes
        else None
    )
    back_url = request.query_params.get("back") or "/admin/audit"

    return _template(
        "audit_detail.html",
        **_common_ctx(request, f"Audit #{entry_id}"),
        entry=entry,
        actor=actor,
        resource_url=resource_admin_url(entry.resource_type, entry.resource_id),
        changes_json=changes_json,
        back_url=back_url,
    )


