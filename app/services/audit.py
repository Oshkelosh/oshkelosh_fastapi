"""Audit logging helpers."""

from __future__ import annotations

import re
from typing import Any

from models.audit_log import AuditLog

_SECRET_KEY_PATTERN = re.compile(
    r"password|secret|token|api_key|private_key",
    re.IGNORECASE,
)

__all__ = [
    "admin_request_meta",
    "diff_fields",
    "log_change",
    "redact_changes",
    "resource_admin_url",
]


def diff_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    keys: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return changed fields as {field: {from, to}}."""
    field_names = keys if keys is not None else set(before) | set(after)
    changes: dict[str, dict[str, Any]] = {}
    for key in field_names:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes[key] = {"from": old, "to": new}
    return changes


def redact_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secret-like keys in audit change payloads."""
    redacted: dict[str, Any] = {}
    for key, value in changes.items():
        if _SECRET_KEY_PATTERN.search(key):
            if isinstance(value, dict) and "from" in value and "to" in value:
                redacted[key] = {"from": "[redacted]", "to": "[changed]"}
            else:
                redacted[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            redacted[key] = redact_changes(value)
        else:
            redacted[key] = value
    return redacted


def admin_request_meta(request: Any) -> tuple[int | None, str | None]:
    """Extract actor user id and client IP from an admin request."""
    actor = getattr(request.state, "admin_user", None)
    actor_user_id = actor.id if actor is not None else None
    ip_address = request.client.host if request.client else None
    return actor_user_id, ip_address


def resource_admin_url(resource_type: str, resource_id: str | None) -> str | None:
    """Map audit resource to an admin panel URL, if one exists."""
    if not resource_id:
        if resource_type == "site_settings":
            return "/admin/settings"
        return None

    if resource_type == "product":
        return f"/admin/products/{resource_id}"
    if resource_type == "order":
        return f"/admin/orders/{resource_id}"
    if resource_type == "user":
        return f"/admin/users/{resource_id}"
    if resource_type in ("supplier", "addon"):
        return f"/admin/addons/{resource_id}/configure"
    if resource_type == "site_settings":
        return "/admin/settings"
    if resource_type == "notification_template" and "/" in resource_id:
        event_key, channel = resource_id.split("/", 1)
        return f"/admin/notifications/messages/{event_key}/{channel}"
    return None


async def log_change(
    session: Any,
    *,
    actor_user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None,
    changes: dict[str, Any] | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """Persist an audit log entry."""
    safe_changes = redact_changes(changes) if changes else None
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        changes=safe_changes,
        ip_address=ip_address,
        detail=detail,
    )
    session.add(entry)
    await session.flush()
    return entry
