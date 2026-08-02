"""Command bus — internal action events → ESP32 JSON via Transport."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import OUTPUT_SAMPLE_RATE, log
from src.actions import action_key, build_robot_action
from src.audio import encode_audio_wav_b64
from src.events import EVT_ROBOT_ACTION, Event, EventBus
from src.state import SharedState
from src.transport import Transport


class CommandBus:
    """Converts ``robot.action`` events (and direct calls) into body JSON sends."""

    def __init__(
        self,
        bus: EventBus,
        shared: SharedState,
        transport: Transport,
    ) -> None:
        self._bus = bus
        self._shared = shared
        self._transport = transport
        bus.subscribe(EVT_ROBOT_ACTION, self._on_action_event)

    @property
    def transport(self) -> Transport:
        return self._transport

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
            ok = await self._transport.send(payload)

        if ok:
            shared.recent_actions.append(action_key(action))
            log.info(
                "Bridge send ok: %s source=%s audio=%s",
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
