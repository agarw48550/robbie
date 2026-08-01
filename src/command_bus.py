"""Command bus — internal action events → ESP32 JSON HTTP messages."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import OUTPUT_SAMPLE_RATE, log
from src.actions import action_key, build_robot_action
from src.audio import encode_audio_wav_b64
from src.events import EVT_ROBOT_ACTION, Event, EventBus
from src.persistence import load_bridge_config
from src.state import SharedState


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


class CommandBus:
    """Converts ``robot.action`` events (and direct calls) into ESP32 JSON POSTs."""

    def __init__(self, bus: EventBus, shared: SharedState) -> None:
        self._bus = bus
        self._shared = shared
        bus.subscribe(EVT_ROBOT_ACTION, self._on_action_event)

    async def _on_action_event(self, event: Event) -> None:
        payload = event.payload
        await self.send(
            direction=str(payload.get("direction", "")),
            duration_seconds=int(payload.get("duration_seconds", 0) or 0),
            speed=int(payload.get("speed", 5) or 5),
            expression=str(payload.get("expression", "curious")),
            source=str(payload.get("source", "event")),
            transcript=str(payload.get("transcript", "")),
            include_audio=bool(payload.get("include_audio", True)),
        )

    def to_esp32_json(
        self,
        *,
        direction: str,
        duration_seconds: int,
        speed: int,
        expression: str,
        source: str,
        transcript: str = "",
        audio_b64: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Build the exact bridge JSON payload (no network I/O)."""
        action = build_robot_action(direction, duration_seconds, speed, expression)
        if not action:
            return None
        return {
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

    async def send(
        self,
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
            log.warning(
                "Rejected invalid robot action: %r",
                (direction, duration_seconds, speed, expression),
            )
            return False

        bridge = load_bridge_config()
        if not bridge["bridge_url"]:
            log.warning("robot action skipped — no bridge_url configured")
            return False

        shared = self._shared
        async with shared.bridge_lock:
            audio_b64: Optional[str] = None
            if include_audio and shared.turn_audio_pcm:
                pcm = bytes(shared.turn_audio_pcm)
                shared.turn_audio_pcm.clear()
                audio_b64 = encode_audio_wav_b64(pcm)

            payload = self.to_esp32_json(
                direction=action["direction"],
                duration_seconds=action["duration_seconds"],
                speed=action["speed"],
                expression=action["expression"],
                source=source,
                transcript=transcript,
                audio_b64=audio_b64,
            )
            assert payload is not None
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

    async def publish_action(
        self,
        *,
        direction: str,
        duration_seconds: int,
        speed: int,
        expression: str,
        source: str,
        transcript: str = "",
        include_audio: bool = True,
    ) -> None:
        """Enqueue an action via the EventBus (handled by this CommandBus)."""
        await self._bus.publish(
            EVT_ROBOT_ACTION,
            {
                "direction": direction,
                "duration_seconds": duration_seconds,
                "speed": speed,
                "expression": expression,
                "source": source,
                "transcript": transcript,
                "include_audio": include_audio,
            },
        )
