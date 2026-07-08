"""Async session adapter that executes SQL via the Cloudflare D1 HTTP API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Sequence, Type, TypeVar

from sqlalchemy import Dialect, inspect as sa_inspect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ClauseElement
from sqlmodel import SQLModel

from app.db.d1_client import D1Connection

T = TypeVar("T", bound=SQLModel)
_DIALECT: Dialect = sqlite_dialect.dialect()


def _compile(statement: ClauseElement) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(
        dialect=_DIALECT,
        compile_kwargs={"render_postcompile": True},
    )
    params = dict(compiled.params)
    return str(compiled), params


def _ordered_params(params: dict[str, Any]) -> list[Any]:
    return list(params.values())


def _rows_from_d1_response(response: Any) -> list[dict[str, Any]]:
    """Normalize D1 HTTP API response into a list of row dicts."""
    if isinstance(response, list):
        rows: list[dict[str, Any]] = []
        for batch in response:
            if isinstance(batch, dict) and "results" in batch:
                rows.extend(batch["results"])
            elif isinstance(batch, dict):
                rows.append(batch)
        return rows
    if isinstance(response, dict):
        if "results" in response:
            return list(response["results"])
        if "result" in response:
            inner = response["result"]
            if isinstance(inner, list):
                return _rows_from_d1_response(inner)
    return []


class _D1ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise RuntimeError(f"Expected one row, got {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self) -> Any:
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise RuntimeError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0]


class D1HTTPResult:
    """Minimal SQLAlchemy Result stand-in for D1 HTTP queries."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        statement: ClauseElement,
        model: type[SQLModel] | None = None,
    ) -> None:
        self._rows = rows
        self._statement = statement
        self._model = model

    def _instantiate(self, row: dict[str, Any]) -> Any:
        if self._model is not None:
            return self._model.model_validate(row)
        return row

    def scalars(self) -> _D1ScalarResult:
        items: list[Any] = []
        for row in self._rows:
            if isinstance(row, dict):
                if len(row) == 1:
                    items.append(next(iter(row.values())))
                elif self._model is not None:
                    items.append(self._model.model_validate(row))
                else:
                    items.append(row)
            else:
                items.append(row)
        return _D1ScalarResult(items)

    def scalar_one(self) -> Any:
        return self.scalars().one()

    def scalar_one_or_none(self) -> Any:
        return self.scalars().one_or_none()

    def scalar(self) -> Any:
        return self.scalars().first()

    def all(self) -> list[Any]:
        return [self._instantiate(r) for r in self._rows]

    def first(self) -> Any:
        if not self._rows:
            return None
        return self._instantiate(self._rows[0])


class D1HTTPAsyncSession:
    """Async session that routes SQL to Cloudflare D1 via HTTP."""

    def __init__(self, d1: D1Connection) -> None:
        self._d1 = d1
        self._new: list[SQLModel] = []
        self._dirty: set[SQLModel] = set()
        self._deleted: list[SQLModel] = []

    def mark_dirty(self, instance: SQLModel) -> None:
        """Track an existing instance for UPDATE on flush."""
        if instance not in self._new:
            self._dirty.add(instance)

    async def execute_raw(self, sql: str, params: list[Any] | None = None) -> int:
        """Run parameterized SQL and return the number of rows changed."""
        response = await self._d1.execute(sql, params or [])
        rows = _rows_from_d1_response(response)
        for batch in response if isinstance(response, list) else [response]:
            if isinstance(batch, dict):
                meta = batch.get("meta") or {}
                if "changes" in meta:
                    return int(meta["changes"])
        if rows and isinstance(rows[0], dict) and "changes" in rows[0]:
            return int(rows[0]["changes"])
        return 0

    async def execute(
        self,
        statement: ClauseElement,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> D1HTTPResult:
        if params is not None or kwargs:
            from loguru import logger

            logger.warning(
                "D1HTTPAsyncSession.execute() ignores params/kwargs; use statement-bound parameters"
            )
        sql, bind = _compile(statement)
        response = await self._d1.query(sql, _ordered_params(bind))
        rows = _rows_from_d1_response(response)

        model: type[SQLModel] | None = None
        if isinstance(statement, Select):
            for col_desc in statement.column_descriptions:
                ent = col_desc.get("entity")
                if ent is not None and isinstance(ent, type) and issubclass(ent, SQLModel):
                    model = ent
                    break

        return D1HTTPResult(rows, statement, model)

    async def get(
        self,
        entity: Type[T],
        ident: Any,
    ) -> T | None:
        mapper = sa_inspect(entity)
        table = mapper.local_table
        pk_cols = list(table.primary_key.columns)
        if len(pk_cols) != 1:
            raise NotImplementedError("Composite primary keys not supported for D1 get()")
        pk_name = pk_cols[0].name
        sql = f"SELECT * FROM {table.name} WHERE {pk_name} = ?"
        response = await self._d1.query(sql, [ident])
        rows = _rows_from_d1_response(response)
        if not rows:
            return None
        return entity.model_validate(rows[0])

    def add(self, instance: SQLModel) -> None:
        self._new.append(instance)

    async def delete(self, instance: SQLModel) -> None:
        self._deleted.append(instance)

    def _compile_insert(self, obj: SQLModel) -> tuple[str, list[Any]]:
        mapper = sa_inspect(obj.__class__)
        table = mapper.local_table
        data = obj.model_dump()
        cols = [c.name for c in table.columns if c.name in data and data[c.name] is not None]
        if not cols:
            cols = [
                c.name
                for c in table.columns
                if c.name != "id" or data.get("id") is not None
            ]
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        values = [data[c] for c in cols]
        sql = f"INSERT INTO {table.name} ({col_names}) VALUES ({placeholders})"
        return sql, values

    def _compile_update(self, obj: SQLModel) -> tuple[str, list[Any]]:
        mapper = sa_inspect(obj.__class__)
        table = mapper.local_table
        pk_cols = list(table.primary_key.columns)
        if len(pk_cols) != 1:
            raise NotImplementedError("Composite PK update not supported")
        pk_name = pk_cols[0].name
        data = obj.model_dump()
        pk_val = data[pk_name]
        sets = [f"{k} = ?" for k in data if k != pk_name and data[k] is not None]
        values = [data[k] for k in data if k != pk_name and data[k] is not None]
        values.append(pk_val)
        sql = f"UPDATE {table.name} SET {', '.join(sets)} WHERE {pk_name} = ?"
        return sql, values

    def _compile_delete(self, obj: SQLModel) -> tuple[str, list[Any]]:
        mapper = sa_inspect(obj.__class__)
        table = mapper.local_table
        pk_cols = list(table.primary_key.columns)
        pk_name = pk_cols[0].name
        pk_val = getattr(obj, pk_name)
        sql = f"DELETE FROM {table.name} WHERE {pk_name} = ?"
        return sql, [pk_val]

    async def flush(self) -> None:
        new_objs = list(self._new)
        dirty_objs = list(self._dirty)
        deleted_objs = list(self._deleted)
        if not new_objs and not dirty_objs and not deleted_objs:
            return

        statements: list[dict[str, Any]] = []
        insert_objs: list[SQLModel] = []

        for obj in new_objs:
            sql, values = self._compile_insert(obj)
            statements.append({"sql": f"{sql} RETURNING id", "params": values})
            insert_objs.append(obj)
        for obj in dirty_objs:
            sql, values = self._compile_update(obj)
            statements.append({"sql": sql, "params": values})
        for obj in deleted_objs:
            sql, values = self._compile_delete(obj)
            statements.append({"sql": sql, "params": values})

        results = await self._d1.batch_query(statements)
        insert_idx = 0
        for batch in results:
            rows = _rows_from_d1_response(
                batch if isinstance(batch, dict) else [batch]
            )
            if insert_idx < len(insert_objs) and rows:
                obj = insert_objs[insert_idx]
                if getattr(obj, "id", None) is None and "id" in rows[0]:
                    obj.id = rows[0]["id"]
                insert_idx += 1

        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()

    async def _insert(self, obj: SQLModel) -> None:
        sql, values = self._compile_insert(obj)
        response = await self._d1.query(f"{sql} RETURNING id", values)
        rows = _rows_from_d1_response(response)
        if rows and getattr(obj, "id", None) is None:
            obj.id = rows[0].get("id")

    async def _update(self, obj: SQLModel) -> None:
        sql, values = self._compile_update(obj)
        await self._d1.execute(sql, values)

    async def _delete_row(self, obj: SQLModel) -> None:
        sql, values = self._compile_delete(obj)
        await self._d1.execute(sql, values)

    async def commit(self) -> None:
        await self.flush()

    async def rollback(self) -> None:
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()

    async def refresh(
        self,
        instance: SQLModel,
        attribute_names: Sequence[str] | None = None,
    ) -> None:
        del attribute_names
        mapper = sa_inspect(instance.__class__)
        table = mapper.local_table
        pk_cols = list(table.primary_key.columns)
        pk_name = pk_cols[0].name
        pk_val = getattr(instance, pk_name)
        sql = f"SELECT * FROM {table.name} WHERE {pk_name} = ?"
        response = await self._d1.query(sql, [pk_val])
        rows = _rows_from_d1_response(response)
        if rows:
            for key, value in rows[0].items():
                setattr(instance, key, value)

    async def close(self) -> None:
        pass


@asynccontextmanager
async def d1_http_session(d1: D1Connection) -> AsyncIterator[D1HTTPAsyncSession]:
    """Context manager yielding a D1 HTTP-backed session."""
    session = D1HTTPAsyncSession(d1)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
