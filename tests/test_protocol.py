"""Protocol v1/v2 envelope tests."""

from __future__ import annotations

from src.protocol import (
    PROTOCOL_VERSION,
    unwrap_to_v1,
    validate_envelope,
    wrap_v1_action,
)


def test_wrap_v1_action_envelope_shape() -> None:
    v1 = {
        "direction": "forward",
        "duration_seconds": 2,
        "speed": 5,
        "expression": "curious",
        "audio": None,
        "source": "test",
    }
    env = wrap_v1_action(v1, priority=3)
    assert env["protocol_version"] == PROTOCOL_VERSION
    assert env["priority"] == 3
    assert env["type"] == "robot.action"
    assert env["payload"]["direction"] == "forward"
    assert validate_envelope(env)


def test_unwrap_bare_v1() -> None:
    bare = {
        "direction": "spin_left",
        "duration_seconds": 1,
        "speed": 4,
        "expression": "happy",
    }
    out = unwrap_to_v1(bare)
    assert out["direction"] == "spin_left"
    assert out["expression"] == "happy"


def test_unwrap_v2_payload() -> None:
    env = wrap_v1_action(
        {"direction": "backward", "duration_seconds": 3, "speed": 6, "expression": "sad"}
    )
    out = unwrap_to_v1(env)
    assert out["direction"] == "backward"
    assert out["duration_seconds"] == 3


def test_validate_envelope_rejects_incomplete() -> None:
    assert validate_envelope({"protocol_version": 2}) is False
    assert validate_envelope("nope") is False
