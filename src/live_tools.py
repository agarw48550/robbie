"""Gemini Live tool declarations and handlers."""

from __future__ import annotations

from typing import Any

from google.genai import types

from config.settings import VALID_VOICES, log
from src.actions import build_robot_action
from src.bridge import send_robot_action
from src.gemini.intentions import build_intention, publish_intention
from src.persistence import remember_fact, set_voice_name, write_voice_mode_file
from src.state import SharedState


def live_tool_declarations() -> list[types.Tool]:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="move_robot",
                    description=(
                        "Move the physical robot ONLY when the user explicitly asks "
                        "for motion or a facial expression (e.g. 'move forward 2 seconds'). "
                        "Do NOT call this for jokes, questions, schedules, or normal chat."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "direction": types.Schema(
                                type=types.Type.STRING,
                                description="forward | backward | spin_left | spin_right",
                            ),
                            "duration_seconds": types.Schema(
                                type=types.Type.INTEGER,
                                description="0-9 seconds of motion",
                            ),
                            "speed": types.Schema(
                                type=types.Type.INTEGER,
                                description="1-9 (10%-90%). Default 5.",
                            ),
                            "expression": types.Schema(
                                type=types.Type.STRING,
                                description=(
                                    "happy|sad|curious|angry|calm|surprised|love|silly|worried"
                                ),
                            ),
                        },
                        required=["direction", "duration_seconds"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="turn_voice_off",
                    description=(
                        "Turn off voice/listening mode. Proactive idle motions continue. "
                        "Use when the user asks for quiet, stop listening, or voice off."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "reason": types.Schema(
                                type=types.Type.STRING,
                                description="Optional short reason",
                            ),
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="remember",
                    description="Store a lasting personal fact or preference about the user.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "fact": types.Schema(
                                type=types.Type.STRING,
                                description="One concise fact to remember",
                            ),
                        },
                        required=["fact"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="save_reminder",
                    description=(
                        "Save a schedule item, reminder, or to-do "
                        "(e.g. 'dentist Thursday 3pm', 'call mom tonight')."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "item": types.Schema(
                                type=types.Type.STRING,
                                description="The reminder or schedule item",
                            ),
                            "when": types.Schema(
                                type=types.Type.STRING,
                                description="Optional time/date phrasing",
                            ),
                        },
                        required=["item"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="set_voice",
                    description="Change Robbie's speaking voice. Session will reconnect.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "voice_name": types.Schema(
                                type=types.Type.STRING,
                                description=f"One of: {', '.join(VALID_VOICES[:10])}, …",
                            ),
                        },
                        required=["voice_name"],
                    ),
                ),
            ]
        )
    ]


async def handle_live_tool(
    shared: SharedState,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    args = dict(args or {})
    if name == "move_robot":
        action = build_robot_action(
            direction=args.get("direction", ""),
            duration_seconds=args.get("duration_seconds", 2),
            speed=args.get("speed", 5),
            expression=args.get("expression", "curious"),
        )
        if not action:
            return {"ok": False, "error": "invalid movement args"}

        # Prefer BodyController → intention bus → legacy bridge send
        body = getattr(shared, "body_controller", None)
        if body is not None:
            ok = await body.execute_action(
                direction=action["direction"],
                duration_seconds=action["duration_seconds"],
                speed=action["speed"],
                expression=action["expression"],
                source="live_tool",
                transcript=shared.last_model_transcript,
            )
        elif shared.event_bus is not None:
            await publish_intention(
                shared.event_bus,
                build_intention(
                    direction=action["direction"],
                    duration_seconds=action["duration_seconds"],
                    speed=action["speed"],
                    expression=action["expression"],
                    source="live_tool",
                    transcript=shared.last_model_transcript,
                ),
            )
            ok = True
        else:
            ok = await send_robot_action(
                shared,
                direction=action["direction"],
                duration_seconds=action["duration_seconds"],
                speed=action["speed"],
                expression=action["expression"],
                source="live_tool",
                transcript=shared.last_model_transcript,
            )
        shared.tool_moved_this_turn = True
        return {"ok": ok, "action": action}

    if name == "turn_voice_off":
        write_voice_mode_file(False)
        shared.voice_enabled.clear()
        log.info("Live tool turned voice OFF (%s)", args.get("reason", ""))
        return {"ok": True, "voice": "off"}

    if name == "remember":
        status = remember_fact(str(args.get("fact", "")), source="live_tool")
        return {"ok": True, "status": status}

    if name == "save_reminder":
        item = str(args.get("item", "")).strip()
        when = str(args.get("when", "")).strip()
        text = f"Reminder: {item}" + (f" ({when})" if when else "")
        status = remember_fact(text, source="reminder")
        return {"ok": True, "status": status, "saved": text}

    if name == "set_voice":
        try:
            voice = set_voice_name(str(args.get("voice_name", "")))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        shared.voice_name = voice
        shared.force_live_reconnect = True
        log.info("Voice set to %s — reconnecting Live", voice)
        return {"ok": True, "voice_name": voice, "reconnecting": True}

    return {"ok": False, "error": f"unknown tool {name}"}
