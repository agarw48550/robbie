# Tools

## Live tools (Gemini function calling)

Declared in `src/live_tools.py`: `move_robot`, `turn_voice_off`, `remember`, `save_reminder`, `set_voice`.

`move_robot` prefers `BodyController.execute_action`, else publishes `EVT_INTENTION`, else `send_robot_action`.

## Tool framework (`src/tools/`)

- `Tool` — `name`, `description`, `async run(arguments) -> dict`
- `ToolRegistry` — `register`, `get`, `discover`, `list_docs`, `run`
- Builtins: `calculator`, `timer`, `calendar`, `memory_lookup`, `internet_search`, `weather`, `homework`
- Live names registered as documentation aliases

```python
from src.tools import default_registry
await default_registry.run("calculator", {"expression": "2+3*4"})
```

Stubs return structured `{ok, result}` without external APIs when keys are missing. `MemoryLookupTool` uses `persistence.load_memory`.
