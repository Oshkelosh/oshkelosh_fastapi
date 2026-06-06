"""Audit logging helpers."""

from __future__ import annotations

from typing import Any

from models.audit_log import AuditLog


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
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        changes=changes,
        ip_address=ip_address,
        detail=detail,
    )
    session.add(entry)
    await session.flush()
    return entry
