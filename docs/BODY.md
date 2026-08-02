# Body (K10)

Firmware: `robot/k10_body.py` — HTTP server for motion, expression text, optional WAV play.

## Capabilities today

- Directions: forward / backward / spin_left / spin_right
- Expressions: happy, sad, curious, angry, calm, surprised, love, silly, worried
- Audio: play base64 WAV from POST (24 kHz mono)
- No mic capture, wake word, or WebSocket client on body yet

## Pi façade

`BodyController` (`src/body_controller.py`) is the sole hardware egress: Face / Motor / LED / Audio / Sensor façades call into it; it uses `CommandBus` → `Transport`.

WS client sketch: `robot/k10_ws_client.py` (opt-in path).
