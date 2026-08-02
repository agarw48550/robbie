# Robbie Protocol

Wire formats between the Pi brain and the K10 body.

## Versioning

| Version | Status | Notes |
|---------|--------|-------|
| **v1** | **Current default** | Bare JSON object POSTed to `http://…/robot` (HTTP). |
| **v2** | Envelope | Adds routing metadata; v1 fields live inside `payload`. |

HTTP remains the default transport. WebSocket is opt-in via
`bridge_transport=websocket` and carries the same JSON (v1 bare or v2 envelope).

## v1 body action (ESP32 contract — unchanged)

```json
{
  "direction": "forward",
  "duration_seconds": 1,
  "speed": 5,
  "expression": "curious",
  "audio": null,
  "audio_format": "wav",
  "sample_rate": 24000,
  "transcript": "",
  "source": "bridge_test",
  "ts": "2026-08-01T12:00:00+00:00"
}
```

### Field rules

| Field | Values / range |
|-------|----------------|
| `direction` | `forward` \| `backward` \| `spin_left` \| `spin_right` |
| `duration_seconds` | 0–9 |
| `speed` | 1–9 |
| `expression` | `happy` \| `sad` \| `curious` \| `angry` \| `calm` \| `surprised` \| `love` \| `silly` \| `worried` |
| `audio` | base64 WAV (24 kHz mono) or `null` |

Exact motion parameters from Gemini / tools are allowed and must not be rewritten.

## v2 envelope

```json
{
  "protocol_version": 2,
  "message_id": "uuid",
  "timestamp": "ISO-8601",
  "type": "robot.action",
  "priority": 0,
  "payload": { "...v1 fields..." }
}
```

| Field | Meaning |
|-------|---------|
| `protocol_version` | Always `2` for this envelope |
| `message_id` | Unique id (UUID string) |
| `timestamp` | UTC ISO-8601 |
| `type` | Logical message kind (e.g. `robot.action`) |
| `priority` | Integer; higher = more urgent |
| `payload` | v1 action object (or other typed body) |

Helpers on the Pi: `src/protocol.py` — `wrap_v1_action`, `unwrap_to_v1`, `validate_envelope`.

## Dual-decode

Receivers MUST accept both:

1. **Bare v1** — top-level `direction` / `expression` (today’s K10 HTTP path).
2. **v2 envelope** — extract `payload` after validating the envelope.

`unwrap_to_v1()` implements this: if `direction` or `expression` is present at the
top level and `protocol_version` is absent, the message is treated as v1.

## Transport notes

- **HTTP (default):** one POST per message; body may be v1 or v2.
- **WebSocket (opt-in):** Pi hosts a WS server; K10 connects as client. Same JSON
  frames; outbound queue on the Pi avoids losing commands while disconnected.
