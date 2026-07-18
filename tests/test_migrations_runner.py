"""Tests for the migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_apply_migrations_async_tracks_files_and_tolerates_duplicate_columns(
    tmp_path, monkeypatch
):
    from app import config as config_module
    from app.db import migrations as migrations_module

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_create_widgets.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY, name TEXT);",
        encoding="utf-8",
    )
    (migrations_dir / "002_add_code.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN code TEXT;",
        encoding="utf-8",
    )
    (migrations_dir / "003_add_code_again.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN code TEXT;",
        encoding="utf-8",
    )

    db_path = tmp_path / "migrations.sqlite"
    monkeypatch.setattr(migrations_module, "_MIGRATIONS_DIR", migrations_dir)
    monkeypatch.setattr(config_module, "SQLITE_DB_PATH", db_path)
    monkeypatch.setattr("app.db.migrations.settings.database_backend", "sqlite")

    await migrations_module.apply_migrations_async()
    await migrations_module.apply_migrations_async()

    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(widgets)").fetchall()]
        applied = [
            row[0]
            for row in conn.execute(
                "SELECT filename FROM schema_migrations ORDER BY filename"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert columns == ["id", "name", "code"]
    assert applied == [
        "001_create_widgets.sql",
        "002_add_code.sql",
        "003_add_code_again.sql",
    ]


_REAL_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "migrations" / "d1"
)


def test_split_statements_preserves_ddl_after_comment_headers():
    """Real migration files begin with comment headers; the DDL must survive."""
    from app.db.migrations import _split_statements

    for name in (
        "001_user_default_billing_address.sql",
        "002_order_shipping_selections.sql",
        "003_site_shop_currency.sql",
    ):
        sql = (_REAL_MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        statements = _split_statements(sql)
        assert statements, f"{name} produced no statements"
        assert any(s.upper().startswith("ALTER TABLE") for s in statements), name
        assert not any(s.lstrip().startswith("--") for s in statements)


def test_split_statements_keeps_cart_unique_index_from_initial():
    from app.db.migrations import _split_statements

    sql = (_REAL_MIGRATIONS_DIR / "000_initial.sql").read_text(encoding="utf-8")
    statements = _split_statements(sql)
    assert any("idx_cart_items_cart_variant" in s for s in statements)


def test_split_statements_ignores_double_dash_inside_string_literal():
    from app.db.migrations import _split_statements

    sql = "UPDATE t SET note = 'a--b' WHERE id = 1; -- trailing comment\n"
    statements = _split_statements(sql)
    assert statements == ["UPDATE t SET note = 'a--b' WHERE id = 1"]
