"""SQLite memory store + persistence write-through tests."""

from __future__ import annotations

import json
from pathlib import Path

import src.db.store as store_mod
import src.persistence as persistence
from src.db.store import SQLiteStore


def _reset_store_singleton() -> None:
    store_mod._store = None


def test_sqlite_store_migrate_and_remember(tmp_path: Path, monkeypatch) -> None:
    mem_json = tmp_path / "memory.json"
    mem_json.write_text(
        json.dumps(
            {
                "facts": [
                    {"text": "likes mangoes", "source": "seed", "ts": "2026-01-01T00:00:00+00:00"}
                ]
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "robbie.db"
    monkeypatch.setattr(store_mod, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(store_mod, "MEMORY_PATH", mem_json)
    monkeypatch.setattr(persistence, "MEMORY_PATH", mem_json)
    monkeypatch.setattr(persistence, "CONFIG_DIR", tmp_path)
    _reset_store_singleton()

    store = SQLiteStore(db_path)
    facts = store.list_facts()
    assert any(f["text"] == "likes mangoes" for f in facts)
    assert store.remember_fact("likes mangoes", source="dup") == "already_known"
    assert store.remember_fact("has a desk pet", source="test") == "saved"
    assert (tmp_path / "robbie.db.bak").exists() or db_path.exists()
    store.close()
    _reset_store_singleton()


def test_persistence_write_through(tmp_path: Path, monkeypatch) -> None:
    mem_json = tmp_path / "memory.json"
    db_path = tmp_path / "robbie.db"
    monkeypatch.setattr(store_mod, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(store_mod, "MEMORY_PATH", mem_json)
    monkeypatch.setattr(persistence, "MEMORY_PATH", mem_json)
    monkeypatch.setattr(persistence, "CONFIG_DIR", tmp_path)
    _reset_store_singleton()

    status = persistence.remember_fact("favorite color is blue", source="unit")
    assert status == "saved"
    data = json.loads(mem_json.read_text(encoding="utf-8"))
    assert any(f.get("text") == "favorite color is blue" for f in data["facts"])

    loaded = persistence.load_memory()
    assert any(f.get("text") == "favorite color is blue" for f in loaded["facts"])

    persistence.save_memory({"facts": []})
    assert persistence.load_memory()["facts"] == []
    _reset_store_singleton()
