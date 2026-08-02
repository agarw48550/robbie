"""Helpers to build robot intention dicts and publish ``EVT_INTENTION``."""

from __future__ import annotations

from typing import Any, Optional

from src.events import EVT_INTENTION, Event, EventBus


def build_intention(
    *,
    direction: str,
    duration_seconds: int,
    speed: int = 5,
    expression: str = "curious",
    source: str = "intention",
    transcript: str = "",
    include_audio: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured intention payload (exact motion params preserved)."""
    payload: dict[str, Any] = {
        "direction": direction,
        "duration_seconds": int(duration_seconds),
        "speed": int(speed),
        "expression": expression,
        "source": source,
        "transcript": transcript or "",
        "include_audio": bool(include_audio),
    }
    if extra:
        payload.update(extra)
    return payload


async def publish_intention(
    bus: EventBus,
    payload: dict[str, Any],
    *,
    priority: int = 0,
) -> Event:
    """Publish an intention event on the bus (BodyController consumes it)."""
    return await bus.publish(EVT_INTENTION, payload, priority=priority)


async def publish_move_intention(
    bus: EventBus,
    *,
    direction: str,
    duration_seconds: int,
    speed: int = 5,
    expression: str = "curious",
    source: str = "intention",
    transcript: str = "",
    include_audio: bool = True,
    priority: int = 0,
) -> Event:
    """Convenience: build + publish a move intention."""
    return await publish_intention(
        bus,
        build_intention(
            direction=direction,
            duration_seconds=duration_seconds,
            speed=speed,
            expression=expression,
            source=source,
            transcript=transcript,
            include_audio=include_audio,
        ),
        priority=priority,
    )
