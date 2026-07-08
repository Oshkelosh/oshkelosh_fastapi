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
