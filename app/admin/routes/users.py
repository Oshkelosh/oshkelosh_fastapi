from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Any,
    Depends,
    Dict,
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
    mark_instance_dirty,
    require_admin_session,
    select,
    set_flash_cookie,
)

router = APIRouter()

def _address_from_form(
    line1: str = "",
    line2: str = "",
    city: str = "",
    state: str = "",
    postal_code: str = "",
    country: str = "",
) -> Optional[Dict[str, Any]]:
    """Build a shipping address dict from form fields."""
    raw = {
        "line1": line1.strip(),
        "line2": line2.strip(),
        "city": city.strip(),
        "state": state.strip(),
        "postal_code": postal_code.strip(),
        "country": country.strip(),
    }
    address = {k: v for k, v in raw.items() if v}
    return address or None


def _address_form_values(address: Optional[Dict[str, Any]]) -> Dict[str, str]:
    addr = address or {}
    return {
        "line1": addr.get("line1", "") or "",
        "line2": addr.get("line2", "") or "",
        "city": addr.get("city", "") or "",
        "state": addr.get("state", "") or "",
        "postal_code": addr.get("postal_code", "") or "",
        "country": addr.get("country", "") or "",
    }


async def _render_user_form(
    request: Request,
    *,
    title: str,
    user: Any = None,
    action_url: str,
    form_error: str | None = None,
    draft: Optional[Dict[str, Any]] = None,
):
    """Render the create/edit user form."""
    draft = draft or {}
    address = _address_form_values(
        draft.get("default_shipping_address")
        if draft.get("default_shipping_address") is not None
        else (user.default_shipping_address if user else None)
    )
    return _template(
        "user_form.html",
        **_common_ctx(request, title),
        user=user,
        action_url=action_url,
        form_error=form_error,
        draft=draft,
        address=address,
    )


@router.get("/users")
async def admin_users_list(
    request: Request,
    page: int = Query(1, ge=1),
    search: Optional[str] = Query(None),
    banned: Optional[str] = Query(None),
    verified: Optional[str] = Query(None),
    db=Depends(require_admin_session),
):
    """List users with pagination and optional filters."""
    from models.user import User

    PAGE_SIZE = 20
    offset = (page - 1) * PAGE_SIZE

    stmt = select(User).order_by(col(User.created_at).desc()).offset(offset).limit(PAGE_SIZE)
    count_stmt = select(func.count(User.id))

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            col(User.email).ilike(pattern) | col(User.full_name).ilike(pattern)
        )
        count_stmt = count_stmt.where(
            col(User.email).ilike(pattern) | col(User.full_name).ilike(pattern)
        )

    banned_filter: Optional[bool] = None
    if banned == "true":
        banned_filter = True
    elif banned == "false":
        banned_filter = False

    verified_filter: Optional[bool] = None
    if verified == "true":
        verified_filter = True
    elif verified == "false":
        verified_filter = False

    if banned_filter is not None:
        stmt = stmt.where(col(User.banned) == banned_filter)
        count_stmt = count_stmt.where(col(User.banned) == banned_filter)
    if verified_filter is not None:
        stmt = stmt.where(col(User.verified) == verified_filter)
        count_stmt = count_stmt.where(col(User.verified) == verified_filter)

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

    return _template(
        "users.html",
        **_common_ctx(request, "Users"),
        items=items,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        search=search or "",
        banned_filter=banned or "",
        verified_filter=verified or "",
    )


@router.get("/users/new")
async def admin_user_new(request: Request, db=Depends(require_admin_session)):
    """Show the create-user form."""
    return await _render_user_form(
        request,
        title="New User",
        action_url="/admin/users",
    )


@router.post("/users")
async def admin_user_create(
    request: Request,
    email: str = Form(..., max_length=255),
    password: str = Form(..., max_length=128),
    full_name: str = Form("", max_length=255),
    phone: str = Form("", max_length=32),
    line1: str = Form("", max_length=255),
    line2: str = Form("", max_length=255),
    city: str = Form("", max_length=128),
    state: str = Form("", max_length=128),
    postal_code: str = Form("", max_length=32),
    country: str = Form("", max_length=64),
    verified: Optional[str] = Form(None),
    banned: Optional[str] = Form(None),
    is_admin: Optional[str] = Form(None),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a new user."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.security import hash_password
    from app.services.user_accounts import mark_user_verified
    from models.user import User
    from schemas.user import UserCreate

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    default_shipping_address = _address_from_form(line1, line2, city, state, postal_code, country)
    draft = {
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "default_shipping_address": default_shipping_address,
        "verified": verified == "on",
        "banned": banned == "on",
        "is_admin": is_admin == "on",
    }

    try:
        data = UserCreate(
            email=email,
            password=password,
            full_name=full_name or None,
            phone=phone or None,
            default_shipping_address=default_shipping_address,
            verified=verified == "on",
            banned=banned == "on",
            is_admin=is_admin == "on",
        )
    except PydanticValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        return await _render_user_form(
            request,
            title="New User",
            action_url="/admin/users",
            form_error=errors,
            draft=draft,
        )

    existing = await db.execute(select(User).where(col(User.email) == data.email))
    if existing.first() is not None:
        return await _render_user_form(
            request,
            title="New User",
            action_url="/admin/users",
            form_error="A user with this email already exists",
            draft=draft,
        )

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        default_shipping_address=data.default_shipping_address,
        banned=data.banned,
        verified=data.verified,
        is_admin=data.is_admin,
    )
    if user.verified and user.verified_at is None:
        mark_user_verified(user)

    db.add(user)
    await db.commit()
    await db.refresh(user)

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="create",
        resource_type="user",
        resource_id=user.id,
        changes={
            "email": user.email,
            "is_admin": user.is_admin,
            "verified": user.verified,
            "banned": user.banned,
        },
        ip_address=ip_address,
        detail=f"Created user '{user.email}'",
    )
    await db.commit()

    resp = RedirectResponse(url=f"/admin/users/{user.id}", status_code=302)
    set_flash_cookie(resp, f"User '{user.email}' created")
    return resp


@router.get("/users/{user_id}")
async def admin_user_detail(
    request: Request,
    user_id: int,
    db=Depends(require_admin_session),
):
    """Show the edit-user form."""
    from models.user import User

    if not db:
        return _render_error(request, "Database unavailable")

    user = await db.get(User, user_id)
    if not user:
        return _render_error(request, "User not found", status_code=404)

    return await _render_user_form(
        request,
        title=f"User: {user.email}",
        user=user,
        action_url=f"/admin/users/{user_id}",
    )


@router.post("/users/{user_id}")
async def admin_user_update(
    request: Request,
    user_id: int,
    password: str = Form("", max_length=128),
    full_name: str = Form("", max_length=255),
    phone: str = Form("", max_length=32),
    line1: str = Form("", max_length=255),
    line2: str = Form("", max_length=255),
    city: str = Form("", max_length=128),
    state: str = Form("", max_length=128),
    postal_code: str = Form("", max_length=32),
    country: str = Form("", max_length=64),
    verified: Optional[str] = Form(None),
    banned: Optional[str] = Form(None),
    is_admin: Optional[str] = Form(None),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Update an existing user."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.security import hash_password
    from app.services.user_accounts import mark_user_verified
    from models.user import User
    from schemas.user import UserUpdate

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    user = await db.get(User, user_id)
    if not user:
        return _render_error(request, "User not found", status_code=404)

    from app.services.audit import admin_request_meta, diff_fields, log_change

    _USER_AUDIT_KEYS = {
        "full_name",
        "phone",
        "banned",
        "verified",
        "is_admin",
        "default_shipping_address",
    }
    user_before = {key: getattr(user, key) for key in _USER_AUDIT_KEYS}

    default_shipping_address = _address_from_form(line1, line2, city, state, postal_code, country)
    draft = {
        "full_name": full_name,
        "phone": phone,
        "default_shipping_address": default_shipping_address,
        "verified": verified == "on",
        "banned": banned == "on",
        "is_admin": is_admin == "on",
    }

    update_data: Dict[str, Any] = {
        "full_name": full_name or None,
        "phone": phone or None,
        "default_shipping_address": default_shipping_address,
        "banned": banned == "on",
        "verified": verified == "on",
        "is_admin": is_admin == "on",
    }

    if password.strip():
        update_data["password"] = password

    try:
        data = UserUpdate(**update_data)
    except PydanticValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        return await _render_user_form(
            request,
            title=f"User: {user.email}",
            user=user,
            action_url=f"/admin/users/{user_id}",
            form_error=errors,
            draft=draft,
        )

    updates = data.model_dump(exclude_unset=True)
    pwd = updates.pop("password", None)
    verified_set = updates.pop("verified", None)

    for key, value in updates.items():
        setattr(user, key, value)

    if pwd is not None:
        user.password_hash = hash_password(pwd)

    if verified_set is True:
        mark_user_verified(user)
    elif verified_set is False:
        user.verified = False
        user.verified_at = None

    mark_instance_dirty(db, user)
    await db.commit()
    await db.refresh(user)

    user_after = {key: getattr(user, key) for key in _USER_AUDIT_KEYS}
    changes = diff_fields(user_before, user_after, keys=_USER_AUDIT_KEYS)
    if pwd is not None:
        changes["password"] = {"from": "[redacted]", "to": "[changed]"}

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="user",
        resource_id=user.id,
        changes=changes or None,
        ip_address=ip_address,
        detail=f"Updated user '{user.email}'",
    )
    await db.commit()

    resp = RedirectResponse(url=f"/admin/users/{user.id}", status_code=302)
    set_flash_cookie(resp, f"User '{user.email}' updated")
    return resp


