## Learned User Preferences

- Use the official `google-genai` SDK only; do not use the legacy `google-generativeai` package.
- Robbie should behave as a helpful agent (jokes, world knowledge, schedules), not only as a movement/expression controller.
- Multilingual speech (e.g. Hindi, Chinese) is welcome, but do not switch languages randomly—only when the user asks or the context clearly calls for it.
- Support distinct voice vs proactive-only modes; wake word `robbie` should turn voice mode on from proactive-only mode.
- Every conversational turn should drive robot directives (tool/Gemma path) so speech and motion feel synchronized and fast.
- Prefer global start/stop commands and persistent API-key storage so the orchestrator can run from anywhere on the machine.
- Avoid mic-muting approaches that break live audio I/O; keep listening reliable and reduce cutoffs / out-of-turn speech.
- Persist something memorable from each conversation; allow the user to change voices.
- Gemini Live should be able to turn voice mode off via tool and issue exact motion commands (e.g. forward for N seconds).
- In proactive mode, vary motions and expressions creatively rather than repeating the same pattern (e.g. spin left + curious).

## Learned Workspace Facts

- Robbie is a desk-pet robot: Mac (Python 3.12+, asyncio) is the brain; a micro:bit USB relay executes motion/expression commands.
- Configured relay serial port is `/dev/cu.usbmodem102` at 115200 baud; commands are a strict 4-digit newline-terminated string (e.g. `1491\n`).
- 4-digit protocol: digit1 direction (1 F / 2 B / 3 spin L / 4 spin R), digit2 duration seconds 0–9, digit3 speed 1–9 (10%–90%), digit4 expression 1–9 (happy/sad/curious/angry/calm/surprised/love/silly/worried).
- Main orchestrator is `robbie_orchestrator.py`; `Serial_test.py` is the serial smoke test; use the project `.venv` (system Python blocks pip).
- Architecture: Gemini Live for conversation plus a fast text model for motion JSON (prefer Gemma 4 26B, fall back to Gemini 3.1 Flash Lite on failure/rate limits).
- Dependencies center on `google-genai`, `pyserial`, and `asyncio` (see `requirements.txt`).
