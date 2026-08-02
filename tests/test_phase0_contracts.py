"""Phase 0 golden / parity tests — freeze current behaviour contracts."""

from __future__ import annotations

import importlib

from src.actions import (
    build_robot_action,
    build_serial_command,
    is_valid_serial_command,
    serial_command_to_action,
)
from src.command_bus import CommandBus
from src.events import EventBus
from src.live_tools import live_tool_declarations
from src.state import SharedState


REQUIRED_PAYLOAD_KEYS = {
    "direction",
    "duration_seconds",
    "speed",
    "expression",
    "audio",
    "audio_format",
    "sample_rate",
    "transcript",
    "source",
    "ts",
}

EXPECTED_LIVE_TOOLS = [
    "move_robot",
    "turn_voice_off",
    "remember",
    "save_reminder",
    "set_voice",
]


def test_build_serial_command_forward_curious() -> None:
    assert build_serial_command("forward", 2, 5, "curious") == "1253"


def test_serial_roundtrip() -> None:
    cmd = "4187"
    assert is_valid_serial_command(cmd)
    action = serial_command_to_action(cmd)
    assert action == {
        "direction": "spin_right",
        "duration_seconds": 1,
        "speed": 8,
        "expression": "love",
    }
    assert build_robot_action(**action) == action


def test_build_robot_action_rejects_bad_direction() -> None:
    assert build_robot_action("sideways", 2, 5, "curious") is None


def test_esp32_json_payload_shape() -> None:
    from src.transport import HttpTransport

    shared = SharedState()
    bus = EventBus()
    transport = HttpTransport(url="http://127.0.0.1/robot")
    cmd = CommandBus(bus, shared, transport)
    payload = cmd.to_esp32_json(
        direction="forward",
        duration_seconds=1,
        speed=5,
        expression="curious",
        source="bridge_test",
        transcript="Bridge test ping",
        audio_b64=None,
    )
    assert payload is not None
    assert REQUIRED_PAYLOAD_KEYS.issubset(payload.keys())
    assert payload["direction"] == "forward"
    assert payload["duration_seconds"] == 1
    assert payload["speed"] == 5
    assert payload["expression"] == "curious"
    assert payload["audio"] is None
    assert payload["audio_format"] == "wav"
    assert payload["sample_rate"] == 24000
    assert payload["source"] == "bridge_test"
    assert payload["transcript"] == "Bridge test ping"


def test_live_tool_names_and_move_robot_required_args() -> None:
    tools = live_tool_declarations()
    decls = tools[0].function_declarations
    names = [d.name for d in decls]
    assert names == EXPECTED_LIVE_TOOLS
    move = next(d for d in decls if d.name == "move_robot")
    assert set(move.parameters.required or []) == {"direction", "duration_seconds"}


def test_boot_imports() -> None:
    assert importlib.import_module("main") is not None
    app = importlib.import_module("src.app")
    assert callable(app.main)
    orch = importlib.import_module("robbie_orchestrator")
    assert hasattr(orch, "set_bridge_url")
    assert hasattr(orch, "VALID_VOICES")
    assert hasattr(orch, "get_voice_name")
