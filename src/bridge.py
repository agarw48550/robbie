"""HTTP bridge helpers — delegates action building to ``actions`` and posting to ``CommandBus``."""

from __future__ import annotations

import random
from typing import Optional

from config.settings import FALLBACK_SERIAL_POOL, log
from src.actions import (  # noqa: F401 — re-export for existing imports
    action_key,
    build_robot_action,
    build_serial_command,
    is_valid_serial_command,
    serial_command_to_action,
)
from src.state import SharedState


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
    """Send a body command. Prefers BodyController, else CommandBus."""
    body = getattr(shared, "body_controller", None)
    if body is not None:
        return await body.execute_action(
            direction=direction,
            duration_seconds=duration_seconds,
            speed=speed,
            expression=expression,
            source=source,
            transcript=transcript,
            include_audio=include_audio,
        )

    if shared.command_bus is not None:
        return await shared.command_bus.send(
            direction=direction,
            duration_seconds=duration_seconds,
            speed=speed,
            expression=expression,
            source=source,
            transcript=transcript,
            include_audio=include_audio,
        )

    # Fallback only if OS layer not yet attached (should not happen in normal app.py)
    log.warning("CommandBus missing — robot action dropped")
    return False


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
