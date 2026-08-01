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

- Robbie is a desk-pet robot: Raspberry Pi Zero W (Python 3.11+, asyncio) is the AI brain; an ESP32-S3 over WiFi executes motion, expression, and plays speech audio.
- HTTP bridge default: `http://192.168.4.1/robot` (configure with `robbie set-bridge <URL>` in `~/.config/robbie/config.json`).
- POST JSON payload fields: `direction`, `duration_seconds` (0–9), `speed` (1–9), `expression`, `audio` (base64 WAV from Gemini Live at 24 kHz mono, or null), `transcript`, `source`, `ts`.
- Direction values: `forward | backward | spin_left | spin_right`. Expression values: `happy | sad | curious | angry | calm | surprised | love | silly | worried`.
- Internal brain still uses 4-digit serial codes for planning; orchestrator converts to structured JSON before POST.
- Main entry point is `main.py` (modules under `src/`); `robbie_orchestrator.py` is a deprecated re-export shim. HTTP smoke test: `tools/bridge_test.py`. ESP32/K10 body firmware: `robot/k10_body.py`. Use the project `.venv`.
- Layout: `config/` (constants), `src/` (brain/Live/bridge), `robot/` (ESP32), `tools/`, `tests/`, `assets/`, `docs/`.
- Architecture: Gemini Live for conversation plus a fast text model for motion JSON (full cascade on dev; Pi Zero uses `gemini-3.1-flash-lite` only via `ROBBIE_PI=1` or armv6l/armv7l detection).
- Dependencies: `google-genai`, `sounddevice` (see `requirements.txt`). Pi Zero: recommend 512MB swap/zram; audio buffer capped at ~8s.
