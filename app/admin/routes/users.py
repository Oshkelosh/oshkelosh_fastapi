import json
import logging

from fastapi import APIRouter
from sqlalchemy.exc import IntegrityError

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
    settings,
)
from app.core.exceptions import ValidationError as AppValidationError

router = APIRouter()
logger = logging.getLogger(__name__)

_RECENT_ORDERS_LIMIT = 10


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


def _address_form_values(address: Any) -> Dict[str, str]:
    """Flatten an address column value into form field strings.

    Accepts dicts, JSON strings, or other legacy shapes without raising.
    """
    empty = {
        "line1": "",
        "line2": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": "",
    }
    if address is None:
        return empty
    if isinstance(address, str):
        try:
            address = json.loads(address)
        except (json.JSONDecodeError, TypeError):
            return empty
    if not isinstance(address, dict):
        return empty
    return {
        "line1": address.get("line1", "") or "",
        "line2": address.get("line2", "") or "",
        "city": address.get("city", "") or "",
        "state": address.get("state", "") or "",
        "postal_code": address.get("postal_code", "") or "",
        "country": address.get("country", "") or "",
    }


def _address_storage(value: Any) -> Optional[Dict[str, Any]]:
    """Convert a validated Address (or None) to a DB storage dict."""
    if value is None:
        return None
    if hasattr(value, "to_storage_dict"):
        return value.to_storage_dict()
    if isinstance(value, dict):
        return value
    return None


def _format_dt(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16]


async def _render_user_form(
    request: Request,
    *,
    title: str,
    edit_user: Any = None,
    action_url: str,
    form_error: str | None = None,
    draft: Optional[Dict[str, Any]] = None,
    recent_orders: list | None = None,
):
    """Render the create/edit user maintenance form."""
    draft = draft or {}
    shipping = _address_form_values(
        draft.get("default_shipping_address")
        if draft.get("default_shipping_address") is not None
        else (edit_user.default_shipping_address if edit_user else None)
    )
    billing = _address_form_values(
        draft.get("default_billing_address")
        if draft.get("default_billing_address") is not None
        else (edit_user.default_billing_address if edit_user else None)
    )
    return _template(
        "user_form.html",
        **_common_ctx(request, title),
        edit_user=edit_user,
        action_url=action_url,
        form_error=form_error,
        draft=draft,
        address=shipping,
        billing_address=billing,
        recent_orders=recent_orders or [],
        format_dt=_format_dt,
    )


async def _load_recent_orders(db, user_id: int) -> list:
    from models.order import Order

    try:
        result = await db.execute(
            select(Order)
            .where(col(Order.user_id) == user_id)
            .order_by(col(Order.created_at).desc())
            .limit(_RECENT_ORDERS_LIMIT)
        )
        return list(result.scalars().all())
    except Exception:
        logger.exception("Failed to load recent orders for user %s", user_id)
        return []


def _self_lockout_error(
    request: Request,
    *,
    target_user_id: int,
    is_admin: bool,
    banned: bool,
) -> str | None:
    """Reject demoting or banning the currently signed-in admin."""
    admin = getattr(request.state, "admin_user", None)
    if admin is None or admin.id != target_user_id:
        return None
    if not is_admin:
        return "You cannot remove your own admin privileges"
    if banned:
        return "You cannot ban your own account"
    return None


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
        action_url=f"{settings.admin_prefix}/users",
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
    billing_line1: str = Form("", max_length=255),
    billing_line2: str = Form("", max_length=255),
    billing_city: str = Form("", max_length=128),
    billing_state: str = Form("", max_length=128),
    billing_postal_code: str = Form("", max_length=32),
    billing_country: str = Form("", max_length=64),
    verified: Optional[str] = Form(None),
    banned: Optional[str] = Form(None),
    is_admin: Optional[str] = Form(None),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a new user."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.security import hash_password
    from app.services.user_accounts import ensure_admin_slot_available, mark_user_verified
    from models.user import User
    from schemas.user import UserCreate

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    default_shipping_address = _address_from_form(line1, line2, city, state, postal_code, country)
    default_billing_address = _address_from_form(
        billing_line1,
        billing_line2,
        billing_city,
        billing_state,
        billing_postal_code,
        billing_country,
    )
    draft = {
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "default_shipping_address": default_shipping_address,
        "default_billing_address": default_billing_address,
        "verified": verified == "on",
        "banned": banned == "on",
        "is_admin": is_admin == "on",
    }

    async def _form_error(message: str):
        return await _render_user_form(
            request,
            title="New User",
            action_url=f"{settings.admin_prefix}/users",
            form_error=message,
            draft=draft,
        )

    try:
        data = UserCreate(
            email=email,
            password=password,
            full_name=full_name or None,
            phone=phone or None,
            default_shipping_address=default_shipping_address,
            default_billing_address=default_billing_address,
            verified=verified == "on",
            banned=banned == "on",
            is_admin=is_admin == "on",
        )
    except PydanticValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        return await _form_error(errors)

    existing = await db.execute(select(User).where(col(User.email) == data.email))
    if existing.first() is not None:
        return await _form_error("A user with this email already exists")

    try:
        await ensure_admin_slot_available(db, make_admin=data.is_admin)
    except AppValidationError as exc:
        return await _form_error(exc.message)

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        default_shipping_address=_address_storage(data.default_shipping_address),
        default_billing_address=_address_storage(data.default_billing_address),
        banned=data.banned,
        verified=data.verified,
        is_admin=data.is_admin,
    )
    if user.verified and user.verified_at is None:
        mark_user_verified(user)

    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        return await _form_error("Could not create user (database constraint)")

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

    resp = RedirectResponse(url=f"{settings.admin_prefix}/users/{user.id}", status_code=302)
    set_flash_cookie(resp, f"User '{user.email}' created")
    return resp


@router.get("/users/{user_id}")
async def admin_user_detail(
    request: Request,
    user_id: int,
    db=Depends(require_admin_session),
):
    """Show the edit-user maintenance page."""
    from models.user import User

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        user = await db.get(User, user_id)
        if not user:
            return _render_error(request, "User not found", status_code=404)

        recent_orders = await _load_recent_orders(db, user_id)
        return await _render_user_form(
            request,
            title=f"User: {user.email}",
            edit_user=user,
            action_url=f"{settings.admin_prefix}/users/{user_id}",
            recent_orders=recent_orders,
        )
    except Exception:
        logger.exception("Failed to render user maintenance page for user %s", user_id)
        return _render_error(request, "Could not load user", status_code=500)


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
    billing_line1: str = Form("", max_length=255),
    billing_line2: str = Form("", max_length=255),
    billing_city: str = Form("", max_length=128),
    billing_state: str = Form("", max_length=128),
    billing_postal_code: str = Form("", max_length=32),
    billing_country: str = Form("", max_length=64),
    verified: Optional[str] = Form(None),
    banned: Optional[str] = Form(None),
    is_admin: Optional[str] = Form(None),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Update an existing user."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.security import hash_password
    from app.services.user_accounts import ensure_admin_slot_available, mark_user_verified
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
        "default_billing_address",
    }
    user_before = {key: getattr(user, key) for key in _USER_AUDIT_KEYS}

    default_shipping_address = _address_from_form(line1, line2, city, state, postal_code, country)
    default_billing_address = _address_from_form(
        billing_line1,
        billing_line2,
        billing_city,
        billing_state,
        billing_postal_code,
        billing_country,
    )
    want_verified = verified == "on"
    want_banned = banned == "on"
    want_admin = is_admin == "on"
    draft = {
        "full_name": full_name,
        "phone": phone,
        "default_shipping_address": default_shipping_address,
        "default_billing_address": default_billing_address,
        "verified": want_verified,
        "banned": want_banned,
        "is_admin": want_admin,
    }

    async def _form_error(message: str):
        recent_orders = await _load_recent_orders(db, user_id)
        return await _render_user_form(
            request,
            title=f"User: {user.email}",
            edit_user=user,
            action_url=f"{settings.admin_prefix}/users/{user_id}",
            form_error=message,
            draft=draft,
            recent_orders=recent_orders,
        )

    lockout = _self_lockout_error(
        request,
        target_user_id=user.id,
        is_admin=want_admin,
        banned=want_banned,
    )
    if lockout:
        return await _form_error(lockout)

    update_data: Dict[str, Any] = {
        "full_name": full_name or None,
        "phone": phone or None,
        "default_shipping_address": default_shipping_address,
        "default_billing_address": default_billing_address,
        "banned": want_banned,
        "verified": want_verified,
        "is_admin": want_admin,
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
        return await _form_error(errors)

    updates = data.model_dump(exclude_unset=True)
    pwd = updates.pop("password", None)
    verified_set = updates.pop("verified", None)

    if updates.get("is_admin") is True and not user.is_admin:
        try:
            await ensure_admin_slot_available(
                db,
                make_admin=True,
                exclude_user_id=user.id,
            )
        except AppValidationError as exc:
            return await _form_error(exc.message)

    for key, value in updates.items():
        if key in ("default_shipping_address", "default_billing_address"):
            setattr(user, key, _address_storage(getattr(data, key)))
        else:
            setattr(user, key, value)

    if pwd is not None:
        user.password_hash = hash_password(pwd)

    if verified_set is True:
        mark_user_verified(user)
    elif verified_set is False:
        user.verified = False
        user.verified_at = None

    mark_instance_dirty(db, user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        return await _form_error("Could not update user (database constraint)")

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

    resp = RedirectResponse(url=f"{settings.admin_prefix}/users/{user.id}", status_code=302)
    set_flash_cookie(resp, f"User '{user.email}' updated")
    return resp
