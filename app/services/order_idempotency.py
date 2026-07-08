"""Idempotency helpers for order creation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.config import settings
from models.order import Order
from models.order_idempotency_key import OrderIdempotencyKey


def hash_idempotency_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def find_idempotent_order(
    session: Any,
    *,
    user_id: int,
    raw_key: str,
) -> Order | None:
    """Return an existing order for this idempotency key within the TTL window."""
    key_hash = hash_idempotency_key(raw_key)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.order_idempotency_ttl_hours)
    result = await session.execute(
        select(OrderIdempotencyKey, Order)
        .join(Order, col(Order.id) == col(OrderIdempotencyKey.order_id))
        .where(col(OrderIdempotencyKey.user_id) == user_id)
        .where(col(OrderIdempotencyKey.key_hash) == key_hash)
        .where(col(OrderIdempotencyKey.created_at) >= cutoff)
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    return row[1]


async def record_idempotent_order(
    session: Any,
    *,
    user_id: int,
    raw_key: str,
    order_id: int,
) -> Order | None:
    """Record idempotency key. On duplicate, return the existing order if found."""
    record = OrderIdempotencyKey(
        user_id=user_id,
        key_hash=hash_idempotency_key(raw_key),
        order_id=order_id,
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:
        existing = await find_idempotent_order(session, user_id=user_id, raw_key=raw_key)
        if existing is not None:
            return existing
        raise
    return None
