"""SQLite store — ~/.config/robbie/robbie.db with JSON memory migration."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.settings import CONFIG_DIR, MAX_MEMORY_FACTS, MEMORY_PATH, log
from src.db.migrations import apply_schema

DEFAULT_DB_PATH = CONFIG_DIR / "robbie.db"

_store: Optional["SQLiteStore"] = None


class SQLiteStore:
    """Thin SQLite wrapper for Robbie memory and structured tables."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backup()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        apply_schema(self._conn)
        self._migrate_memory_json_once()

    def _backup(self) -> None:
        """Automatic backup to robbie.db.bak when the db already exists."""
        if self.path.exists() and self.path.stat().st_size > 0:
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                shutil.copy2(self.path, bak)
            except OSError as exc:
                log.warning("SQLite backup failed: %s", exc)

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def _migrate_memory_json_once(self) -> None:
        """Import facts from memory.json on first open (idempotent via UNIQUE text)."""
        if not MEMORY_PATH.exists():
            return
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        facts = data.get("facts") or []
        if not isinstance(facts, list) or not facts:
            return
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            text = str(fact.get("text") or "").strip()
            if not text:
                continue
            source = str(fact.get("source") or "migration")
            ts = str(fact.get("ts") or now)
            try:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO facts (text, source, ts) VALUES (?, ?, ?)",
                    (text[:300], source, ts),
                )
                inserted += cur.rowcount
            except sqlite3.Error as exc:
                log.warning("Fact migrate skip: %s", exc)
        self._conn.commit()
        if inserted:
            log.info("Migrated %d facts from %s → SQLite", inserted, MEMORY_PATH)

    def list_facts(self, limit: int = MAX_MEMORY_FACTS) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT text, source, ts FROM facts ORDER BY id ASC"
        ).fetchall()
        facts = [
            {"text": r["text"], "source": r["source"], "ts": r["ts"]} for r in rows
        ]
        return facts[-limit:] if limit else facts

    def remember_fact(self, text: str, source: str = "conversation") -> str:
        text = (text or "").strip()
        if not text:
            return "empty"
        text = text[:300]
        existing = self._conn.execute(
            "SELECT 1 FROM facts WHERE text = ?", (text,)
        ).fetchone()
        if existing:
            return "already_known"
        ts = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO facts (text, source, ts) VALUES (?, ?, ?)",
            (text, source, ts),
        )
        # Trim oldest beyond MAX_MEMORY_FACTS
        count = self._conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()["c"]
        if count > MAX_MEMORY_FACTS:
            overflow = count - MAX_MEMORY_FACTS
            self._conn.execute(
                "DELETE FROM facts WHERE id IN (SELECT id FROM facts ORDER BY id ASC LIMIT ?)",
                (overflow,),
            )
        self._conn.commit()
        return "saved"

    def clear_facts(self) -> None:
        self._conn.execute("DELETE FROM facts")
        self._conn.commit()

    def facts_as_memory_dict(self) -> dict[str, Any]:
        return {"facts": self.list_facts()}


def get_store(path: Optional[Path] = None) -> SQLiteStore:
    """Return process-wide store (or a fresh one when ``path`` is overridden)."""
    global _store
    if path is not None:
        return SQLiteStore(path)
    if _store is None:
        try:
            _store = SQLiteStore()
        except Exception as exc:
            log.warning("SQLiteStore unavailable: %s", exc)
            raise
    return _store


def try_get_store(path: Optional[Path] = None) -> Optional[SQLiteStore]:
    try:
        return get_store(path)
    except Exception:
        return None
