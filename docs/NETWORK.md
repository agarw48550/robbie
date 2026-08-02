# Network

## HTTP (default)

- URL: `http://192.168.4.1/robot` (override with `robbie set-bridge`)
- Config: `~/.config/robbie/config.json` → `bridge_url`, `bridge_timeout_s`, `bridge_token`
- Transport: `src/transport.py` → `HttpTransport`
- Smoke test: `tools/bridge_test.py`

## WebSocket (opt-in)

- Set `bridge_transport=websocket` and `bridge_ws_url` (e.g. `ws://0.0.0.0:8765`)
- Pi hosts the server; K10 connects as client
- Implementation: `src/ws_transport.py`
- Outbound queue retains commands while disconnected

Switching transports is configuration-only behind the `Transport` interface (`connect` / `disconnect` / `send`).
