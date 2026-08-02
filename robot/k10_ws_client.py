"""K10 WebSocket client sketch (MicroPython-oriented).

Connects to the Pi WebSocket server and applies the same v1 JSON action fields
as the HTTP path in ``k10_body.py`` (direction / duration / speed / expression /
audio). Dual-decode: accept bare v1 or protocol v2 envelopes.

This file is a firmware sketch — adapt imports for your MicroPython build
(e.g. ``websocket`` / ``uwebsockets``). CPython asyncio comments show intended
flow where native WS libs differ.

Configure:
  PI_WS_URL = "ws://192.168.x.x:8765"
"""

# --- MicroPython-friendly stubs (replace with real modules on device) ---
try:
    import ujson as json  # type: ignore
except ImportError:
    import json  # type: ignore

try:
    import utime as time  # type: ignore
except ImportError:
    import time  # type: ignore

# from machine import Pin, PWM
# from unihiker_k10 import screen, audio
# import network

PI_WS_URL = "ws://192.168.4.1:8765"
RECONNECT_DELAY_S = 2
MAX_RECONNECT_DELAY_S = 30


def unwrap_payload(data):
    """Dual-decode: bare v1 or v2 envelope → action dict."""
    if not isinstance(data, dict):
        return {}
    if "protocol_version" in data and isinstance(data.get("payload"), dict):
        return data["payload"]
    if "direction" in data or "expression" in data:
        return data
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else {}


def drive_motors(direction, speed_level, duration_sec):
    """Same semantics as k10_body.drive_motors — wire PWM on device."""
    if duration_sec <= 0 or speed_level <= 0:
        return
    # duty = int((speed_level / 9.0) * 1023)
    # ... set M1/M2 DIR+PWM from direction ...
    print("drive", direction, speed_level, duration_sec)
    time.sleep(duration_sec)
    # stop motors


def set_expression(expr_name):
    print("expression", expr_name)
    # screen.draw_text(... expr_name ...)


def play_base64_audio(b64_string):
    if not b64_string:
        return
    print("audio bytes", len(b64_string))
    # decode → /temp_speech.wav → audio.play_wav(...)


def handle_command(data):
    action = unwrap_payload(data)
    expression = action.get("expression", "calm")
    direction = action.get("direction", "")
    duration = int(action.get("duration_seconds", 0) or 0)
    speed = int(action.get("speed", 5) or 5)
    audio_b64 = action.get("audio", None)

    set_expression(expression)
    if audio_b64:
        play_base64_audio(audio_b64)
    if direction and duration > 0:
        drive_motors(direction, speed, duration)


# ---------------------------------------------------------------------------
# Asyncio-style reconnect loop (CPython reference / ports with asyncio)
# On MicroPython without asyncio, use a blocking websocket client + sleep.
# ---------------------------------------------------------------------------

def run_ws_client(url=PI_WS_URL):
    """Blocking reconnect loop sketch.

    Pseudocode for MicroPython ``websocket`` client::

        delay = RECONNECT_DELAY_S
        while True:
            try:
                ws = websocket.connect(url)
                delay = RECONNECT_DELAY_S
                while True:
                    raw = ws.recv()          # may include ping/pong from server
                    if not raw:
                        break
                    data = json.loads(raw)
                    handle_command(data)
                    # optional: ws.send(json.dumps({"ok": True, "type": "ack"}))
            except Exception as e:
                print("WS reconnect:", e)
                time.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY_S)
    """
    delay = RECONNECT_DELAY_S
    print("K10 WS client target", url)
    print("Install/adapt websocket module, then uncomment connect loop.")
    # Keep sketch import-safe on the Pi brain (no MicroPython sockets here).
    _ = delay
    return False


# asyncio port sketch (when available on the board):
#
# async def run_ws_client_async(url=PI_WS_URL):
#     import asyncio
#     delay = RECONNECT_DELAY_S
#     while True:
#         try:
#             # async with websockets.connect(url) as ws:
#             #     delay = RECONNECT_DELAY_S
#             #     async for raw in ws:
#             #         handle_command(json.loads(raw))
#             await asyncio.sleep(delay)
#         except Exception as e:
#             print("WS reconnect:", e)
#             await asyncio.sleep(delay)
#             delay = min(delay * 2, MAX_RECONNECT_DELAY_S)


if __name__ == "__main__":
    run_ws_client()
