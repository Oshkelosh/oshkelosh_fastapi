"""D1 HTTP session correctness: JSON binding, insert-id pairing, rollback scope."""

from __future__ import annotations

import json

import pytest

from app.db.backends.d1_http_session import (
    D1HTTPAsyncSession,
    _bind_value,
    _parse_json_columns,
)
from models.order import Order
from models.user import User


class _FakeD1:
    """Records batch statements and returns canned per-statement results."""

    def __init__(self, batch_results: list) -> None:
        self.batch_results = batch_results
        self.batches: list[list[dict]] = []

    async def batch_query(self, statements: list[dict]) -> list:
        self.batches.append(statements)
        return self.batch_results


def test_bind_value_serializes_json_and_datetime():
    from datetime import datetime, timezone

    assert _bind_value({"a": 1}) == '{"a": 1}'
    assert _bind_value([1, 2]) == "[1, 2]"
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert _bind_value(dt) == dt.isoformat()
    assert _bind_value("plain") == "plain"
    assert _bind_value(7) == 7


def test_compile_insert_serializes_json_columns():
    session = D1HTTPAsyncSession(object())  # type: ignore[arg-type]
    order = Order(
        user_id=1,
        total_cents=100,
        shipping_address={"city": "Oslo"},
    )
    sql, values = session._compile_insert(order)
    assert "shipping_address" in sql
    bound = values[sql.split("(")[1].split(")")[0].split(", ").index("shipping_address")]
    assert bound == json.dumps({"city": "Oslo"})


def test_parse_json_columns_decodes_text():
    row = {
        "id": 1,
        "user_id": 1,
        "total_cents": 100,
        "shipping_address": '{"city": "Oslo"}',
    }
    parsed = _parse_json_columns(Order, row)
    assert parsed["shipping_address"] == {"city": "Oslo"}
    # Non-JSON columns untouched
    assert parsed["total_cents"] == 100


@pytest.mark.asyncio
async def test_flush_pairs_insert_ids_by_position():
    # One insert followed by one update; the update's batch returns a row
    # (e.g. meta echo). The insert must get id from batch[0], not batch[1].
    fake = _FakeD1(
        batch_results=[
            {"results": [{"id": 42}]},
            {"results": [{"id": 999}]},
        ]
    )
    session = D1HTTPAsyncSession(fake)  # type: ignore[arg-type]

    new_user = User(email="new@example.com", password_hash="x")
    session.add(new_user)
    existing = User(id=7, email="old@example.com", password_hash="y")
    session.mark_dirty(existing)

    await session.flush()

    assert new_user.id == 42
    assert existing.id == 7


@pytest.mark.asyncio
async def test_rollback_discards_pending_only():
    fake = _FakeD1(batch_results=[])
    session = D1HTTPAsyncSession(fake)  # type: ignore[arg-type]
    session.add(User(email="x@example.com", password_hash="h"))
    await session.rollback()
    await session.flush()
    assert fake.batches == []
