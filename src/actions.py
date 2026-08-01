"""Reusable robot body actions.

All motion parameters (direction / duration / speed / expression) live here.
No motor angles or PWM values outside this module on the Pi brain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from config.settings import (
    DIGIT_TO_DIR,
    DIGIT_TO_EXPR,
    DIR_NAME_TO_DIGIT,
    EXPR_NAME_TO_DIGIT,
    SERIAL_COMMAND_RE,
)


@dataclass(frozen=True)
class MotorMotion:
    """Discrete drive command (no raw angles)."""

    direction: str
    duration_seconds: int
    speed: int


@dataclass(frozen=True)
class RobotAction:
    """Full body action sent to the ESP32 bridge."""

    direction: str
    duration_seconds: int
    speed: int
    expression: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def make_robot_action(
    direction: str,
    duration_seconds: int | float | str,
    speed: int | float | str = 5,
    expression: str | int = "curious",
) -> Optional[RobotAction]:
    data = build_robot_action(direction, duration_seconds, speed, expression)
    if not data:
        return None
    return RobotAction(
        direction=data["direction"],
        duration_seconds=data["duration_seconds"],
        speed=data["speed"],
        expression=data["expression"],
    )


def action_key(action: dict[str, Any]) -> str:
    d = {"forward": "1", "backward": "2", "spin_left": "3", "spin_right": "4"}[
        action["direction"]
    ]
    e = EXPR_NAME_TO_DIGIT[action["expression"]]
    return f"{d}{action['duration_seconds']}{action['speed']}{e}"


# --- Named reusable primitives (same validation path as build_robot_action) ---

def move_forward(
    duration_seconds: int = 2,
    speed: int = 5,
    expression: str = "curious",
) -> Optional[RobotAction]:
    return make_robot_action("forward", duration_seconds, speed, expression)


def move_backward(
    duration_seconds: int = 2,
    speed: int = 5,
    expression: str = "curious",
) -> Optional[RobotAction]:
    return make_robot_action("backward", duration_seconds, speed, expression)


def spin_left(
    duration_seconds: int = 2,
    speed: int = 5,
    expression: str = "curious",
) -> Optional[RobotAction]:
    return make_robot_action("spin_left", duration_seconds, speed, expression)


def spin_right(
    duration_seconds: int = 2,
    speed: int = 5,
    expression: str = "curious",
) -> Optional[RobotAction]:
    return make_robot_action("spin_right", duration_seconds, speed, expression)


def express(expression: str, *, duration_seconds: int = 0, speed: int = 5) -> Optional[RobotAction]:
    """Expression-only action (duration 0 → no drive on ESP32)."""
    return make_robot_action("forward", duration_seconds, speed, expression)
