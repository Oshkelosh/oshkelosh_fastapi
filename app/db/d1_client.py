"""Cloudflare D1 HTTP API client."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.config import settings


class D1Connection:
    """Thin async wrapper for the Cloudflare D1 HTTP API."""

    API_BASE = "https://api.cloudflare.com/client/v4"

    def __init__(
        self,
        account_id: Optional[str] = None,
        database_id: Optional[str] = None,
        api_token: Optional[str] = None,
    ) -> None:
        self.account_id = account_id or settings.d1_account_id
        self.database_id = database_id or settings.d1_database_id
        self.api_token = api_token or settings.d1_api_token
        self._http: Optional[httpx.AsyncClient] = None

    def _check_configured(self) -> bool:
        return bool(self.account_id and self.database_id and self.api_token)

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.API_BASE,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._http

    async def query(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        """Execute SQL via the D1 HTTP API and return batch result objects."""
        if not self._check_configured():
            raise RuntimeError("D1 HTTP client is not configured")

        payload: dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = params

        client = self.http_client
        url = (
            f"/accounts/{self.account_id}"
            f"/d1/database/{self.database_id}"
            "/query"
        )
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise RuntimeError(f"D1 query failed: {data.get('errors')}")

        result = data.get("result")
        if isinstance(result, list):
            return result
        return []

    async def execute(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        """Execute a statement (INSERT / UPDATE / DELETE / DDL)."""
        return await self.query(sql, params)

    async def batch_query(
        self,
        statements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute multiple SQL statements in one D1 transaction."""
        if not statements:
            return []
        if not self._check_configured():
            raise RuntimeError("D1 HTTP client is not configured")

        client = self.http_client
        url = (
            f"/accounts/{self.account_id}"
            f"/d1/database/{self.database_id}"
            "/query"
        )
        resp = await client.post(url, json=statements)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise RuntimeError(f"D1 batch query failed: {data.get('errors')}")

        result = data.get("result")
        if isinstance(result, list):
            return result
        return []

    def execute_sync(self, sql: str, params: Optional[list[Any]] = None) -> list[dict[str, Any]]:
        """Execute synchronously — CLI/scripts only (no running event loop).

        From async code use ``await execute()`` instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(sql, params))
        raise RuntimeError(
            "D1Connection.execute_sync() cannot run inside an async context; "
            "use await d1.execute() or auto_create_tables_async() / apply_migrations_async()"
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
