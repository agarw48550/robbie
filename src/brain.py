"""Background brain (JSON motion planner) with model cascade."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional

from google.genai import types

from config.settings import (
    BRAIN_MODELS,
    BRAIN_RETRIES_PER_MODEL,
    REACTIVE_BRAIN_MIN_INTERVAL_S,
    VALID_ACTION_TYPES,
    log,
)
from src.bridge import (
    is_valid_serial_command,
    pick_fallback_serial,
    send_robot_action_from_serial,
)
from src.state import SharedState

PROTOCOL_BLOCK = """
=== STRICT 4-DIGIT SERIAL PROTOCOL ===
serial_command is exactly FOUR digits, or null.
Digit1 direction: 1 Forward, 2 Backward, 3 Spin Left, 4 Spin Right
Digit2 duration: 0-9 seconds
Digit3 speed: 1-9 (never 0)
Digit4 expression: 1 Happy,2 Sad,3 Curious,4 Angry,5 Calm,6 Surprised,7 Love,8 Silly,9 Worried
""".strip()

JSON_SCHEMA_BLOCK = """
Reply with ONLY this JSON object:
{
  "should_act": boolean,
  "action_type": "physical" | "social" | "both" | "none",
  "serial_command": "4-digit string or null",
  "social_note": "short string or null"
}
If should_act is false or action_type is none: serial_command and social_note must be null.
Prefer action_type="physical" with a valid serial_command for reactive turns.
Keep social_note null during active chat.
""".strip()


def merge_transcript(prev: str, chunk: str) -> str:
    chunk = (chunk or "").strip()
    if not chunk:
        return prev
    prev = (prev or "").strip()
    if not prev:
        return chunk
    if chunk.startswith(prev) or prev.startswith(chunk):
        return chunk if len(chunk) >= len(prev) else prev
    return f"{prev} {chunk}".strip()


def build_brain_prompt_reactive(user_text: str, model_text: str, recent: list[str]) -> str:
    return f"""Motor planner for Robbie. JSON only. Be fast.
User:{user_text[:120]!r} Robbie:{model_text[:120]!r}

If this turn is a joke, question, schedule, or normal chat with NO move request:
  should_act=false, action_type="none", serial_command=null, social_note=null.
Only move if the user asked for motion/expression or a tiny reaction truly fits.
Avoid recent commands: {recent}
{JSON_SCHEMA_BLOCK}
{PROTOCOL_BLOCK}"""


def build_brain_prompt_idle(idle_seconds: float, voice_on: bool, recent: list[str]) -> str:
    return f"""Robbie boredom planner. Idle {idle_seconds:.0f}s. Voice={'on' if voice_on else 'off'}.
Be CREATIVE — do NOT default to spin-left + curious.
Vary direction (1-4), duration (1-4), speed (2-8), expression (1-9).
Forbidden repeats of recent commands: {recent}
Ideas: tiny forward hop, silly sway, love glance, surprised jolt, calm pause-wiggle, angry stomp, backward peek.
If idle < 45s: usually none. Else prefer a playful unique physical move.
JSON only.
{JSON_SCHEMA_BLOCK}
{PROTOCOL_BLOCK}"""


def parse_brain_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw_text:
        return None
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    required = {"should_act", "action_type", "serial_command", "social_note"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data["should_act"], bool):
        return None
    if data["action_type"] not in VALID_ACTION_TYPES:
        return None
    serial_cmd = data["serial_command"]
    if serial_cmd is not None and not is_valid_serial_command(serial_cmd):
        data["serial_command"] = None
        serial_cmd = None
    if isinstance(data.get("social_note"), str) and not data["social_note"].strip():
        data["social_note"] = None
    if not data["should_act"] or data["action_type"] == "none":
        data["action_type"] = "none"
        data["serial_command"] = None
        data["social_note"] = None
        return data
    if data["action_type"] == "physical" and serial_cmd is None:
        return None
    return data


async def execute_brain_decision(
    shared: SharedState,
    decision: dict[str, Any],
    *,
    source: str = "brain_reactive",
) -> None:
    log.info(
        "Brain decision: should_act=%s action_type=%s serial=%r",
        decision["should_act"],
        decision["action_type"],
        decision["serial_command"],
    )
    if not decision["should_act"] or decision["action_type"] == "none":
        return
    if decision["serial_command"]:
        include_audio = source == "brain_reactive"
        await send_robot_action_from_serial(
            shared,
            decision["serial_command"],
            source=source,
            transcript=shared.last_model_transcript if include_audio else "",
            include_audio=include_audio,
        )
    social_note = decision.get("social_note")
    if social_note and shared.voice_enabled.is_set() and shared.live_session is not None:
        try:
            await shared.live_session.send_realtime_input(
                text=f"[ENVIRONMENTAL NOTE: {social_note}]"
            )
        except Exception as exc:
            log.error("Failed to inject social_note: %s", exc)


def _is_failover_error(exc: Exception) -> bool:
    msg = str(exc)
    return any(
        code in msg
        for code in (
            "429", "500", "503", "UNAVAILABLE", "INTERNAL",
            "RESOURCE_EXHAUSTED", "quota", "high demand",
        )
    )


async def call_brain(
    shared: SharedState,
    prompt: str,
    reason: str,
    *,
    source: str = "brain_reactive",
    fallback_serial: Optional[str] = None,
) -> None:
    client = shared.client
    if client is None:
        return

    async with shared.brain_lock:
        start_idx = shared.brain_model_index
        last_exc: Optional[Exception] = None

        for offset in range(len(BRAIN_MODELS)):
            idx = (start_idx + offset) % len(BRAIN_MODELS)
            model = BRAIN_MODELS[idx]
            for attempt in range(1, BRAIN_RETRIES_PER_MODEL + 2):
                log.info("Calling brain %s (%s) attempt %d…", model, reason, attempt)
                try:
                    response = await client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        ),
                    )
                    decision = parse_brain_response(getattr(response, "text", None))
                    if decision is None:
                        log.warning("Unusable JSON from %s", model)
                        break
                    shared.brain_model_index = idx  # stick to working model
                    await execute_brain_decision(shared, decision, source=source)
                    return
                except Exception as exc:
                    last_exc = exc
                    if _is_failover_error(exc) and attempt <= BRAIN_RETRIES_PER_MODEL:
                        await asyncio.sleep(0.4 * attempt)
                        continue
                    log.warning("Brain %s failed: %s — trying next model", model, exc)
                    break

        log.error("All brain models failed (%s): %s", reason, last_exc)
        # Advance sticky index so next call starts on a lighter model
        shared.brain_model_index = min(
            shared.brain_model_index + 1, len(BRAIN_MODELS) - 1
        )
        if fallback_serial and is_valid_serial_command(fallback_serial):
            log.info("Using fallback serial: %s", fallback_serial)
            include_audio = source == "brain_reactive"
            await send_robot_action_from_serial(
                shared,
                fallback_serial,
                source=source,
                transcript=shared.last_model_transcript if include_audio else "",
                include_audio=include_audio,
            )


def schedule_reactive_brain(shared: SharedState, user_t: str, model_t: str) -> None:
    if shared.tool_moved_this_turn:
        log.info("Skipping brain — Live already moved via tool this turn")
        return
    if shared.brain_scheduled_this_turn:
        return

    now = time.monotonic()
    if now - shared.last_reactive_brain_at < REACTIVE_BRAIN_MIN_INTERVAL_S:
        asyncio.create_task(
            send_robot_action_from_serial(
                shared,
                pick_fallback_serial(shared),
                source="brain_reactive",
                transcript=shared.last_model_transcript,
            )
        )
        shared.brain_scheduled_this_turn = True
        return

    shared.last_reactive_brain_at = now
    shared.brain_scheduled_this_turn = True
    prev = shared.reactive_brain_task
    if prev and not prev.done():
        prev.cancel()

    recent = list(shared.recent_actions)

    async def _run() -> None:
        try:
            await call_brain(
                shared,
                build_brain_prompt_reactive(user_t, model_t, recent),
                reason="per-response",
                source="brain_reactive",
                fallback_serial=pick_fallback_serial(shared),
            )
        except asyncio.CancelledError:
            pass

    shared.reactive_brain_task = asyncio.create_task(_run())
