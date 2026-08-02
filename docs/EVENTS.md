# Events

Canonical types (see `src/events.py`):

| Constant | String | Purpose |
|----------|--------|---------|
| `EVT_STATE_CHANGED` | `robot.state_changed` | RobotStateMachine transitions |
| `EVT_EMOTION_CHANGED` | `robot.emotion_changed` | EmotionEngine output |
| `EVT_ROBOT_ACTION` | `robot.action` | Concrete body action |
| `EVT_INTENTION` | `robot.intention` | Gemini / planner intent (exact params OK) |
| `EVT_SHUTDOWN` | `system.shutdown` | Process teardown |
| `EVT_REMINDER` | `scheduler.reminder` | Scheduler reminder fire |

## EventBus features

- `publish` / `publish_nowait` with `priority` (higher first) and `sticky`
- `get_sticky(type)`, `get_trace()` (last 100)
- Handlers may be sync or async

Intentions are built via `src/gemini/intentions.py` and consumed by `BodyController`.
