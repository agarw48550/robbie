"""HTTP bridge helpers and serial command conversion."""

from __future__ import annotations

import asyncio
import json
import random
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import (
    DIR_NAME_TO_DIGIT,
    DIGIT_TO_DIR,
    DIGIT_TO_EXPR,
    EXPR_NAME_TO_DIGIT,
    FALLBACK_SERIAL_POOL,
    OUTPUT_SAMPLE_RATE,
    SERIAL_COMMAND_RE,
    log,
)
from src.audio import encode_audio_wav_b64
from src.persistence import load_bridge_config
from src.state import SharedState


def is_valid_serial_command(cmd: Optional[str]) -> bool:
    return isinstance(cmd, str) and bool(SERIAL_COMMAND_RE.fullmatch(cmd))


def build_serial_command(
    direction: str,
    duration_seconds: int | float | str,
    speed: int | float | str = 5,
    expression: str | int = "curious",
) -> Optional[str]:
    d = DIR_NAME_TO_DIGIT.get(str(direction).strip().lower())
    if not d:
        return None
    try:
        dur = int(round(float(duration_seconds)))
    except (TypeError, ValueError):
        return None
    dur = max(0, min(9, dur))
    try:
        spd = int(round(float(speed)))
    except (TypeError, ValueError):
        spd = 5
    spd = max(1, min(9, spd))
    expr = EXPR_NAME_TO_DIGIT.get(str(expression).strip().lower(), "3")
    return f"{d}{dur}{spd}{expr}"


def serial_command_to_action(cmd: str) -> Optional[dict[str, Any]]:
    if not is_valid_serial_command(cmd):
        return None
    return {
        "direction": DIGIT_TO_DIR[cmd[0]],
        "duration_seconds": int(cmd[1]),
        "speed": int(cmd[2]),
        "expression": DIGIT_TO_EXPR[cmd[3]],
    }


def build_robot_action(
    direction: str,
    duration_seconds: int | float | str,
    speed: int | float | str = 5,
    expression: str | int = "curious",
) -> Optional[dict[str, Any]]:
    cmd = build_serial_command(direction, duration_seconds, speed, expression)
    if not cmd:
        return None
    return serial_command_to_action(cmd)


def action_key(action: dict[str, Any]) -> str:
    d = {"forward": "1", "backward": "2", "spin_left": "3", "spin_right": "4"}[
        action["direction"]
    ]
    e = EXPR_NAME_TO_DIGIT[action["expression"]]
    return f"{d}{action['duration_seconds']}{action['speed']}{e}"


def _post_json_sync(url: str, body: bytes, timeout_s: float, token: str) -> bool:
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        log.error("Bridge POST HTTP %s: %s", exc.code, exc.reason)
        return False
    except urllib.error.URLError as exc:
        log.error("Bridge POST failed: %s", exc.reason)
        return False
    except Exception as exc:
        log.error("Bridge POST failed: %s", exc)
        return False


async def send_robot_action(
    shared: SharedState,
    *,
    direction: str,
    duration_seconds: int,
    speed: int,
    expression: str,
    source: str,
    transcript: str = "",
    include_audio: bool = True,
) -> bool:
    action = build_robot_action(direction, duration_seconds, speed, expression)
    if not action:
        log.warning("Rejected invalid robot action: %r", (direction, duration_seconds, speed, expression))
        return False

    bridge = load_bridge_config()
    if not bridge["bridge_url"]:
        log.warning("robot action skipped — no bridge_url configured")
        return False

    async with shared.bridge_lock:
        audio_b64: Optional[str] = None
        if include_audio and shared.turn_audio_pcm:
            pcm = bytes(shared.turn_audio_pcm)
            shared.turn_audio_pcm.clear()
            audio_b64 = encode_audio_wav_b64(pcm)

        payload = {
            "direction": action["direction"],
            "duration_seconds": action["duration_seconds"],
            "speed": action["speed"],
            "expression": action["expression"],
            "audio": audio_b64,
            "audio_format": "wav",
            "sample_rate": OUTPUT_SAMPLE_RATE,
            "transcript": (transcript or "")[:500],
            "source": source,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(payload).encode("utf-8")
        ok = await asyncio.to_thread(
            _post_json_sync,
            bridge["bridge_url"],
            body,
            bridge["bridge_timeout_s"],
            bridge["bridge_token"],
        )

    if ok:
        shared.recent_actions.append(action_key(action))
        log.info(
            "Bridge POST ok: %s source=%s audio=%s",
            action_key(action),
            source,
            "yes" if audio_b64 else "no",
        )
    return ok


async def send_robot_action_from_serial(
    shared: SharedState,
    cmd: str,
    *,
    source: str,
    transcript: str = "",
    include_audio: bool = True,
) -> bool:
    action = serial_command_to_action(cmd)
    if not action:
        log.warning("Rejected invalid serial_command: %r", cmd)
        return False
    return await send_robot_action(
        shared,
        direction=action["direction"],
        duration_seconds=action["duration_seconds"],
        speed=action["speed"],
        expression=action["expression"],
        source=source,
        transcript=transcript,
        include_audio=include_audio,
    )


def pick_fallback_serial(shared: SharedState) -> str:
    recent = set(shared.recent_actions)
    choices = [c for c in FALLBACK_SERIAL_POOL if c not in recent] or list(FALLBACK_SERIAL_POOL)
    return random.choice(choices)
