"""
SQLModel base classes and dev helpers.

Defines ``ModelBase`` which all domain models inherit from, and provides
an ``auto_create_tables`` convenience function for local development.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlmodel import Field, SQLModel

from app.config import settings
from app.db.backends.d1_binding import D1BindingNotConfiguredError

# ------------------------------------------------------------------
# Base model
# ------------------------------------------------------------------


class ModelBase(SQLModel):
    """Base class for all SQLModel tables (not a table itself)."""

    id: int | None = Field(default=None, primary_key=True)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ------------------------------------------------------------------
# Table creation helpers
# ------------------------------------------------------------------


def auto_create_tables() -> None:
    """Create all tables for the active database backend (sync — CLI only)."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(auto_create_tables_async())
        return
    raise RuntimeError(
        "auto_create_tables() cannot run inside an async context; use await auto_create_tables_async()"
    )


async def auto_create_tables_async() -> None:
    """Create all tables for the active database backend."""
    import models  # noqa: F401 — register SQLModel tables

    if settings.database_backend in ("d1_http", "d1_binding"):
        await _create_d1_tables_async()
    else:
        _create_sqlite_tables()


def _create_sqlite_tables() -> None:
    """Create tables in the local SQLite database."""
    from sqlalchemy import create_engine

    db_path = Path(settings.d1_local_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        SQLModel.metadata.create_all(engine)
        logger.info("SQLite tables created at {}", db_path)
    finally:
        engine.dispose()


async def _list_existing_tables_d1(d1: Any) -> set[str]:
    """Return table names already present in D1."""
    batches = await d1.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    names: set[str] = set()
    for batch in batches:
        for row in batch.get("results", []):
            if "name" in row:
                names.add(row["name"])
    return names


async def _create_d1_tables_async() -> None:
    """Create tables in D1 via HTTP API or Workers binding."""
    from app.config import settings as cfg

    if cfg.database_backend == "d1_binding":
        from app.db.d1_binding_connection import D1BindingConnection

        d1 = D1BindingConnection()
    else:
        from app.db.d1_client import D1Connection

        d1 = D1Connection()
    existing = await _list_existing_tables_d1(d1)

    for model in _all_table_models():
        table_name = model.__tablename__
        if table_name in existing:
            continue
        logger.info("Creating D1 table: {}", table_name)
        await _emit_ddl_async(d1, model)

    logger.info("D1 table sync complete")


def _all_table_models() -> list[type[ModelBase]]:
    models: list[type[ModelBase]] = []
    for mapper in SQLModel.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, "__tablename__") and issubclass(cls, ModelBase):
            models.append(cls)  # type: ignore[arg-type]
    return models


def _sql_type_for_column(col: Any) -> str:
    type_name = str(col.type).upper()
    if "INT" in type_name:
        return "INTEGER"
    if "BOOL" in type_name:
        return "INTEGER"
    if "DATE" in type_name or "TIME" in type_name:
        return "TEXT"
    return "TEXT"


async def _emit_ddl_async(d1: Any, model: type[ModelBase]) -> None:
    """Emit CREATE TABLE DDL to D1 for a SQLModel class."""
    table = model.__table__
    columns: list[str] = []
    for col in table.columns:
        sql_type = _sql_type_for_column(col)
        col_def = f"{col.name} {sql_type}"
        if col.primary_key:
            col_def += " PRIMARY KEY AUTOINCREMENT"
        elif not col.nullable:
            col_def += " NOT NULL"
        columns.append(col_def)

    create_sql = f"CREATE TABLE IF NOT EXISTS {table.name} (\n"
    create_sql += ",\n".join(columns)
    create_sql += "\n)"
    await d1.execute(create_sql)
