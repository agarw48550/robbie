# Database

SQLite file: `~/.config/robbie/robbie.db` (backup: `robbie.db.bak` on open).

## Tables

`users`, `conversation`, `facts`, `tasks`, `calendar`, `preferences`, `statistics`, `cache`, `schema_migrations`

Schema + migrations: `src/db/migrations.py`. Store: `src/db/store.py`.

## Facts / CLI parity

- On first open, facts are imported from `~/.config/robbie/memory.json`.
- `persistence.remember_fact` / `load_memory` / `save_memory` prefer SQLite when available and **write-through** to `memory.json` so `robbie memory show|clear` keeps working.

## Code

```python
from src.db import SQLiteStore, get_store
store = get_store()  # or SQLiteStore(path)
store.remember_fact("likes tea", source="test")
```
