# API surface (internal)

## CLI (`bin/robbie`)

| Command | Effect |
|---------|--------|
| `start` / `stop` / `status` | Orchestrator process |
| `set-key` / `set-bridge` | Persist API key / body URL |
| `voice on\|off` | Voice mode file |
| `memory show\|clear` | Facts via `memory.json` (SQLite write-through) |

## Live tools

See [TOOLS.md](TOOLS.md).

## Python modules of note

| Module | Role |
|--------|------|
| `src.app` | Assembly / asyncio main |
| `src.bridge.send_robot_action` | Body send helper (delegates to BodyController) |
| `src.protocol` | v1/v2 wrap/unwrap |
| `src.db.store.SQLiteStore` | Memory DB |
| `src.scheduler.Scheduler` | `call_later`, `call_periodic`, `schedule_cron`, `schedule_reminder` |
| `src.audio_routing` | `ROBBIE_BODY_AUDIO` path logging |

## Env flags

| Flag | Default | Meaning |
|------|---------|---------|
| `ROBBIE_PI` | unset | Force Pi slim brain cascade |
| `ROBBIE_BODY_AUDIO` | `0` | Log K10 audio path; Pi sounddevice still used |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | — | Gemini auth |
