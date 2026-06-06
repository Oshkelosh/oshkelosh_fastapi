"""D1 startup must not nest asyncio.run inside a running loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

@pytest.mark.asyncio
async def test_execute_sync_raises_inside_running_loop():
    from app.db.d1_client import D1Connection

    d1 = D1Connection()
    with pytest.raises(RuntimeError, match="cannot run inside an async context"):
        d1.execute_sync("SELECT 1")


@pytest.mark.asyncio
async def test_auto_create_tables_async_uses_await_not_execute_sync(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "database_backend", "d1_http")
    monkeypatch.setattr(settings, "deployment_profile", None)

    mock_d1 = MagicMock()
    mock_d1.execute = AsyncMock(return_value=[{"results": []}])

    with patch("app.db.d1_client.D1Connection", return_value=mock_d1):
        with patch("app.db.base._all_table_models", return_value=[]):
            from app.db.base import auto_create_tables_async

            await auto_create_tables_async()

    assert mock_d1.execute.await_count >= 1
    mock_d1.execute_sync = MagicMock(side_effect=AssertionError("execute_sync must not be called"))
