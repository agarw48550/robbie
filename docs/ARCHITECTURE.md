# Robbie Architecture

Pi Zero W (Python 3.11+, asyncio) is the AI brain. UNIHIKER K10 (ESP32-S3) is the body.

## Layers

1. **Gemini Live** (`src/live.py`, `src/live_tools.py`, `src/gemini/`) — conversation, speech I/O, tools.
2. **Event OS** (`src/events.py`, `src/robot_state.py`, `src/emotion_engine.py`, `src/scheduler.py`) — bus, state, emotion, jobs.
3. **Body egress** (`src/body_controller.py` → `src/command_bus.py` → `src/transport.py`) — sole hardware path.
4. **Memory** (`src/persistence.py` + `src/db/`) — SQLite + JSON write-through.
5. **Tools** (`src/tools/`) — registry for semantic utilities; Live tools stay in `live_tools.py`.

## Data flow (target)

```
User audio → Live → tool/intention → EventBus → BodyController → CommandBus → Transport → K10
```

Exact motion params (`direction`, `duration_seconds`, `speed`, `expression`) are preserved end-to-end.

## Entry points

- `main.py` → `src/app.py`
- CLI: `bin/robbie`
- Deprecated shim: `robbie_orchestrator.py`
