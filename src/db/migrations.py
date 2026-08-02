"""SQLite schema + lightweight migrations."""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    created_at TEXT NOT NULL,
    meta TEXT
);

CREATE TABLE IF NOT EXISTS conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL UNIQUE,
    source TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    due_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    when_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS statistics (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);
"""

# Named migrations applied in order after base schema
MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_base_tables",
        "-- base schema applied via SCHEMA_SQL",
    ),
]


def apply_schema(conn) -> None:
    """Create tables if missing and record base migration."""
    from datetime import datetime, timezone

    conn.executescript(SCHEMA_SQL)
    now = datetime.now(timezone.utc).isoformat()
    for name, _sql in MIGRATIONS:
        row = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (name, now),
            )
    conn.commit()
