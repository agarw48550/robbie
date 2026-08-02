# Roadmap

Incremental upgrade (preserve behaviour each phase):

| Phase | Focus | Status intent |
|-------|--------|---------------|
| 0–4 | Contracts, EventBus, Transport wrap | Foundation |
| 5–10 | Priority events, protocol v2, BodyController, WS opt-in | In progress / landed |
| 11 | Gemini cleanup — intentions, sectioned Live | Landed |
| 12 | Tool registry + builtins | Landed |
| 13 | SQLite memory + JSON parity | Landed |
| 14 | Scheduler cron / reminders / priority | Landed |
| 15 | `ROBBIE_BODY_AUDIO` gated K10 cutover | Flag only; Pi audio stays |
| 16 | Docs suite | Landed |
| 17 | Pi Zero performance | Pending |
| 18 | Final review / EventBus-primary | Pending |

Audio cutover stays **off** until WS + K10 firmware + parity tests (wake, Live turn, motion+speech sync).
