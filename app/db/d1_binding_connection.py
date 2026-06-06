"""D1 database access via Cloudflare Workers binding (in-process)."""

from __future__ import annotations

import inspect
from typing import Any, Optional

from app.db.backends.d1_binding import get_d1_binding


class D1BindingConnection:
    """Async wrapper around ``env.DB`` with the same surface as ``D1Connection``."""

    def __init__(self, binding: object | None = None) -> None:
        self._binding = binding if binding is not None else get_d1_binding()

    async def query(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        return await self.execute(sql, params)

    async def execute(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        binding = self._binding

        if hasattr(binding, "prepare"):
            stmt = binding.prepare(sql)
            if params:
                bind_fn = getattr(stmt, "bind", None)
                if callable(bind_fn):
                    for idx, value in enumerate(params, start=1):
                        stmt = bind_fn(idx, value)
            run = getattr(stmt, "all", None) or getattr(stmt, "run", None)
            if callable(run):
                result = run()
                if inspect.isawaitable(result):
                    result = await result
                return _normalize_binding_result(result)

        exec_fn = getattr(binding, "exec", None) or getattr(binding, "execute", None)
        if callable(exec_fn):
            if params:
                result = exec_fn(sql, params)
            else:
                result = exec_fn(sql)
            if inspect.isawaitable(result):
                result = await result
            return _normalize_binding_result(result)

        raise NotImplementedError(
            "D1 binding does not expose prepare() or exec(); "
            "register a compatible Workers env.DB binding"
        )

    async def close(self) -> None:
        return None


def _normalize_binding_result(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        if result and isinstance(result[0], dict) and "results" in result[0]:
            return result
        return [{"results": result}]
    if isinstance(result, dict):
        if "results" in result:
            return [result]
        return [{"results": [result]}]
    return [{"results": []}]
