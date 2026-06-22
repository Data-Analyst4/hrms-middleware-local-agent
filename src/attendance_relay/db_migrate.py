from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def _table_columns(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(row[1]) for row in rows}


def ensure_sqlite_column(conn: Connection, table: str, column: str, definition: str) -> None:
    if column in _table_columns(conn, table):
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def migrate_local_schema(conn: Connection) -> None:
    """Apply additive SQLite migrations for existing attendance.db files."""
    ensure_sqlite_column(conn, "devices", "machine_number", "INTEGER NOT NULL DEFAULT 1")
    ensure_sqlite_column(conn, "devices", "middleware_public_url", "TEXT NULL")
