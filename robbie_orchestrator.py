#!/usr/bin/env python3
"""Robbie — proactive desk-pet AI orchestrator.

Concurrent work:
  1. Gemini Live voice (tools: move, voice-off, remember, set voice)
  2. Background brain with model cascade for motion when Live does not tool-call
  3. HTTP POST bridge to ESP32-S3 (motion + base64 WAV audio)

Pi Zero W (512MB RAM): set ROBBIE_PI=1 or run on armv6l/armv7l for slim mode.
Recommend 512MB swap or zram — Live + sounddevice peaks ~350–450MB RSS.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import platform
import queue as std_queue
import random
import re
import struct
import time
import urllib.error
import urllib.request
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import sounddevice as sd
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "robbie"
CONFIG_PATH = CONFIG_DIR / "config.json"
VOICE_MODE_PATH = CONFIG_DIR / "voice_mode"  # "on" | "off"
MEMORY_PATH = CONFIG_DIR / "memory.json"

DEFAULT_BRIDGE_URL = "http://192.168.4.1/robot"
DEFAULT_BRIDGE_TIMEOUT_S = 5.0

LIVE_MODEL = "gemini-3.1-flash-live-preview"
BRAIN_MODELS_FULL = [
    "gemini-3.1-flash-lite",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
]
BRAIN_MODELS_PI = ["gemini-3.1-flash-lite"]


def is_pi_zero() -> bool:
    if os.environ.get("ROBBIE_PI") == "1":
        return True
    return platform.machine() in ("armv6l", "armv7l")


IS_PI = is_pi_zero()
BRAIN_MODELS = BRAIN_MODELS_PI if IS_PI else BRAIN_MODELS_FULL
TURN_AUDIO_MAX_BYTES = 384_000  # ~8s @ 24 kHz mono 16-bit
MIC_QUEUE_SIZE = 16 if IS_PI else 32
PLAY_QUEUE_SIZE = 64 if IS_PI else 256
PROACTIVITY_INTERVAL_S = 60.0

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
CHANNELS = 1
CHUNK_FRAMES = 512  # ~32 ms @ 16 kHz — Live prefers ~20–40 ms chunks

VOICE_POLL_S = 0.35
BRAIN_RETRIES_PER_MODEL = 0  # fail over immediately for speed
# Only used as a soft floor while listening; do NOT zero out speech
AMBIENT_RMS_THRESHOLD = 120.0
WAKE_RMS_THRESHOLD = 900.0
REACTIVE_BRAIN_MIN_INTERVAL_S = 1.2
FALLBACK_SERIAL_POOL = (
    "1251", "2148", "4187", "1326", "2412",
    "3158", "4231", "1529", "2345", "1457",
)
FALLBACK_SERIAL_COMMAND = "1251"
MAX_MEMORY_FACTS = 40
WAKE_COOLDOWN_S = 4.0
WAKE_CLIP_S = 1.6

SERIAL_COMMAND_RE = re.compile(r"^[1-4][0-9][1-9][1-9]$")
VALID_ACTION_TYPES = frozenset({"physical", "social", "both", "none"})

VALID_VOICES = (
    "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
    "Autonoe", "Umbriel", "Erinome", "Laomedeia", "Schedar", "Achird",
    "Sadachbia", "Enceladus", "Algieba", "Algenib", "Achernar", "Gacrux",
    "Zubenelgenubi", "Sadaltager", "Callirrhoe", "Iapetus", "Despina",
    "Rasalgethi", "Alnilam", "Pulcherrima", "Vindemiatrix", "Sulafat",
)

DIR_NAME_TO_DIGIT = {
    "forward": "1",
    "fwd": "1",
    "1": "1",
    "backward": "2",
    "back": "2",
    "2": "2",
    "spin_left": "3",
    "left": "3",
    "3": "3",
    "spin_right": "4",
    "right": "4",
    "4": "4",
}

EXPR_NAME_TO_DIGIT = {
    "happy": "1", "sad": "2", "curious": "3", "angry": "4", "calm": "5",
    "surprised": "6", "love": "7", "silly": "8", "worried": "9",
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9",
}

DIGIT_TO_DIR = {
    "1": "forward",
    "2": "backward",
    "3": "spin_left",
    "4": "spin_right",
}

DIGIT_TO_EXPR = {
    "1": "happy",
    "2": "sad",
    "3": "curious",
    "4": "angry",
    "5": "calm",
    "6": "surprised",
    "7": "love",
    "8": "silly",
    "9": "worried",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("robbie")


# ---------------------------------------------------------------------------
# Config / memory / voice persistence
# ---------------------------------------------------------------------------

def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read config %s: %s", CONFIG_PATH, exc)
        return {}


def save_config(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def resolve_api_key() -> Optional[str]:
    env_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key.strip()
    cfg = load_config()
    key = cfg.get("google_api_key") or cfg.get("api_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def get_voice_name() -> str:
    cfg = load_config()
    name = cfg.get("voice_name", "Puck")
    if isinstance(name, str) and name in VALID_VOICES:
        return name
    return "Puck"


def set_bridge_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("bridge URL cannot be empty")
    cfg = load_config()
    cfg["bridge_url"] = cleaned
    if "bridge_timeout_s" not in cfg:
        cfg["bridge_timeout_s"] = DEFAULT_BRIDGE_TIMEOUT_S
    save_config(cfg)
    return cleaned


def load_bridge_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        "bridge_url": cfg.get("bridge_url", DEFAULT_BRIDGE_URL),
        "bridge_timeout_s": float(cfg.get("bridge_timeout_s", DEFAULT_BRIDGE_TIMEOUT_S)),
        "bridge_token": (cfg.get("bridge_token") or "").strip(),
    }


def set_voice_name(name: str) -> str:
    cleaned = name.strip()
    # Case-insensitive match to canonical voice
    for v in VALID_VOICES:
        if v.lower() == cleaned.lower():
            cfg = load_config()
            cfg["voice_name"] = v
            save_config(cfg)
            return v
    raise ValueError(f"Unknown voice {name!r}. Try: {', '.join(VALID_VOICES[:8])}…")


def read_voice_mode_file() -> bool:
    try:
        if not VOICE_MODE_PATH.exists():
            return False
        return VOICE_MODE_PATH.read_text(encoding="utf-8").strip().lower() in {
            "on", "1", "true", "yes",
        }
    except OSError:
        return False


def write_voice_mode_file(enabled: bool) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_MODE_PATH.write_text("on\n" if enabled else "off\n", encoding="utf-8")


def load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {"facts": []}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"facts": []}
        data.setdefault("facts", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"facts": []}


def save_memory(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remember_fact(text: str, source: str = "conversation") -> str:
    text = (text or "").strip()
    if not text:
        return "empty"
    mem = load_memory()
    facts: list[dict[str, Any]] = list(mem.get("facts") or [])
    # Dedup exact matches
    if any(isinstance(f, dict) and f.get("text") == text for f in facts):
        return "already_known"
    facts.append({
        "text": text[:300],
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    mem["facts"] = facts[-MAX_MEMORY_FACTS:]
    save_memory(mem)
    log.info("Remembered (%s): %s", source, text[:120])
    return "saved"


def memory_summary_for_prompt(limit: int = 12) -> str:
    facts = load_memory().get("facts") or []
    if not facts:
        return "(no memories yet)"
    lines = []
    for f in facts[-limit:]:
        if isinstance(f, dict) and f.get("text"):
            lines.append(f"- {f['text']}")
    return "\n".join(lines) if lines else "(no memories yet)"


def build_live_system_instruction() -> str:
    memories = memory_summary_for_prompt()
    return f"""You are Robbie — a helpful desk companion that also happens to be a cute robot.

PRIMARY JOB (most important):
- Be a useful assistant: answer questions, tell jokes, explain things, brainstorm,
  help with schedules/reminders/to-dos, remember preferences, and chat naturally.
- Lead with a clear helpful answer. Do NOT steer every reply toward movement,
  faces, or robot abilities.
- Only mention motion/expression when the user asks you to move OR a tiny gesture
  genuinely fits after you've already helped (optional, rare).

MOVEMENT TOOLS (secondary):
- Call move_robot ONLY when the user explicitly asks to move/spin/express, or
  clearly wants a physical reaction. Never ask "what motion should I show?"
- turn_voice_off when they want quiet / stop listening.
- remember / save_reminder for facts and schedule items.
- set_voice when they ask to change your speaking voice.

LANGUAGE (critical):
- Default to English.
- Mirror the user's language ONLY when they are clearly speaking that language
  for the whole turn (e.g. full Hindi or Chinese sentences).
- Do NOT randomly switch languages mid-conversation.
- Do NOT reply in Hindi/Chinese just because a word sounded similar.
- If unsure, stay in English.
- You CAN speak Hindi and Chinese when the user does — never claim you cannot.

STYLE:
- Warm, clear, concise. One focused reply per turn.
- Ignore background noise / TV. If you only catch a fragment, ask a short
  clarifying question in English instead of guessing a motion.

Memories (use naturally; do not dump the list):
{memories}
"""


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

@dataclass
class SharedState:
    last_interaction_time: float = field(default_factory=time.monotonic)
    last_user_transcript: str = ""
    last_model_transcript: str = ""
    live_session: Any = None
    bridge_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    brain_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    voice_enabled: asyncio.Event = field(default_factory=asyncio.Event)
    is_playing: bool = False
    last_reactive_brain_at: float = 0.0
    tool_moved_this_turn: bool = False
    brain_scheduled_this_turn: bool = False
    brain_model_index: int = 0
    voice_name: str = "Puck"
    force_live_reconnect: bool = False
    recent_actions: deque[str] = field(default_factory=lambda: deque(maxlen=8))
    turn_audio_pcm: bytearray = field(default_factory=bytearray)
    client: Any = None
    reactive_brain_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# WAV / audio helpers
# ---------------------------------------------------------------------------

def pcm16_to_wav_bytes(pcm: bytes, rate: int = OUTPUT_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def encode_audio_wav_b64(pcm: bytes, rate: int = OUTPUT_SAMPLE_RATE) -> Optional[str]:
    if not pcm:
        return None
    wav = pcm16_to_wav_bytes(pcm, rate=rate)
    return base64.b64encode(wav).decode("ascii")


def append_turn_audio(shared: SharedState, pcm: bytes) -> None:
    if not pcm:
        return
    shared.turn_audio_pcm.extend(pcm)
    if len(shared.turn_audio_pcm) > TURN_AUDIO_MAX_BYTES:
        del shared.turn_audio_pcm[: len(shared.turn_audio_pcm) - TURN_AUDIO_MAX_BYTES]


# ---------------------------------------------------------------------------
# HTTP bridge helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Live tools
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Background brain (JSON motion planner) with model cascade
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Control-file watchers
# ---------------------------------------------------------------------------

async def control_watcher(shared: SharedState) -> None:
    if read_voice_mode_file():
        shared.voice_enabled.set()
        log.info("Voice mode: ON")
    else:
        shared.voice_enabled.clear()
        log.info("Voice mode: OFF (proactive-only)")
    shared.voice_name = get_voice_name()
    log.info("Speaking voice: %s", shared.voice_name)

    while not shared.shutdown.is_set():
        enabled = read_voice_mode_file()
        if enabled and not shared.voice_enabled.is_set():
            shared.voice_enabled.set()
            log.info("Voice mode enabled")
        elif not enabled and shared.voice_enabled.is_set():
            shared.voice_enabled.clear()
            log.info("Voice mode disabled — closing Live")

        voice = get_voice_name()
        if voice != shared.voice_name:
            shared.voice_name = voice
            shared.force_live_reconnect = True
            log.info("Voice changed to %s — will reconnect Live", voice)

        try:
            await asyncio.wait_for(shared.shutdown.wait(), timeout=VOICE_POLL_S)
            break
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Live audio I/O
# ---------------------------------------------------------------------------

def _chunk_rms(pcm: bytes) -> float:
    if not pcm or len(pcm) < 2:
        return 0.0
    try:
        import audioop

        return float(audioop.rms(pcm, 2))
    except ImportError:
        count = len(pcm) // 2
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        if not samples:
            return 0.0
        ss = sum(s * s for s in samples)
        return (ss / len(samples)) ** 0.5


async def _mic_send_loop(session: Any, shared: SharedState) -> None:
    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MIC_QUEUE_SIZE)

    def _callback(indata: Any, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        if status:
            log.debug("Mic status: %s", status)
        pcm = bytes(indata)
        try:
            loop.call_soon_threadsafe(audio_queue.put_nowait, pcm)
        except asyncio.QueueFull:
            pass

    stream = sd.RawInputStream(
        samplerate=INPUT_SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_FRAMES,
        callback=_callback,
    )
    stream.start()
    log.info("Microphone streaming started (%d Hz)", INPUT_SAMPLE_RATE)
    try:
        while (
            not shared.shutdown.is_set()
            and shared.voice_enabled.is_set()
            and not shared.force_live_reconnect
        ):
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            # Half-duplex: silence only while Robbie is speaking (prevents echo barge-in).
            # Do NOT zero quiet listening audio — that made soft speech get ignored.
            if shared.is_playing:
                chunk = b"\x00" * len(chunk)

            try:
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                )
            except Exception as exc:
                if shared.shutdown.is_set() or not shared.voice_enabled.is_set():
                    break
                log.error("Mic send failed: %s", exc)
                raise
    finally:
        stream.stop()
        stream.close()
        log.info("Microphone streaming stopped")


async def _receive_loop(session: Any, shared: SharedState) -> None:
    play_q: std_queue.Queue[Optional[bytes]] = std_queue.Queue(maxsize=PLAY_QUEUE_SIZE)

    def _play_worker() -> None:
        with sd.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_FRAMES,
        ) as out:
            while True:
                item = play_q.get()
                if item is None:
                    break
                try:
                    out.write(item)
                except Exception as exc:
                    log.debug("Playback write error: %s", exc)

    player_task = asyncio.create_task(asyncio.to_thread(_play_worker))

    try:
        while (
            not shared.shutdown.is_set()
            and shared.voice_enabled.is_set()
            and not shared.force_live_reconnect
        ):
            turn_model_audio_seen = False
            turn_had_user = False
            shared.tool_moved_this_turn = False
            shared.brain_scheduled_this_turn = False
            shared.turn_audio_pcm.clear()

            async for response in session.receive():
                if (
                    shared.shutdown.is_set()
                    or not shared.voice_enabled.is_set()
                    or shared.force_live_reconnect
                ):
                    return

                # --- Live tool calls (move / voice-off / remember / set_voice) ---
                tool_call = getattr(response, "tool_call", None)
                if tool_call and getattr(tool_call, "function_calls", None):
                    function_responses = []
                    for fc in tool_call.function_calls:
                        args = dict(fc.args or {})
                        log.info("Live tool: %s(%s)", fc.name, args)
                        result = await handle_live_tool(shared, fc.name, args)
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response=result,
                            )
                        )
                    await session.send_tool_response(function_responses=function_responses)
                    continue

                content = getattr(response, "server_content", None)
                if content is None:
                    continue

                if getattr(content, "input_transcription", None):
                    transcript = content.input_transcription.text or ""
                    if transcript.strip():
                        if shared.is_playing:
                            log.debug("Ignoring echo transcript: %r", transcript[:60])
                        else:
                            shared.last_interaction_time = time.monotonic()
                            shared.last_user_transcript = merge_transcript(
                                shared.last_user_transcript, transcript
                            )
                            turn_had_user = True
                            log.info("User speech: %r", transcript.strip()[:120])

                if getattr(content, "output_transcription", None):
                    out_t = content.output_transcription.text or ""
                    if out_t.strip():
                        shared.last_model_transcript = merge_transcript(
                            shared.last_model_transcript, out_t
                        )
                        log.info("Robbie said: %r", out_t.strip()[:120])

                model_turn = getattr(content, "model_turn", None)
                if model_turn and getattr(model_turn, "parts", None):
                    for part in model_turn.parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            if not shared.is_playing:
                                shared.is_playing = True
                                log.info("Robbie speaking — half-duplex silence")
                                # Fire motion ASAP so the body moves with the voice
                                schedule_reactive_brain(
                                    shared,
                                    shared.last_user_transcript,
                                    shared.last_model_transcript,
                                )
                            turn_model_audio_seen = True
                            audio_bytes = inline.data
                            if isinstance(audio_bytes, str):
                                audio_bytes = base64.b64decode(audio_bytes)
                            append_turn_audio(shared, audio_bytes)
                            try:
                                play_q.put_nowait(audio_bytes)
                            except std_queue.Full:
                                pass

                if getattr(content, "interrupted", False):
                    log.info("Model interrupted — clearing playback")
                    shared.is_playing = False
                    shared.turn_audio_pcm.clear()
                    while not play_q.empty():
                        try:
                            play_q.get_nowait()
                        except std_queue.Empty:
                            break

                if getattr(content, "turn_complete", False):
                    log.info("Live turn complete")
                    shared.is_playing = False
                    user_t = shared.last_user_transcript
                    model_t = shared.last_model_transcript
                    shared.last_user_transcript = ""
                    shared.last_model_transcript = ""

                    if user_t or model_t:
                        snippet = f"User said {user_t[:80]!r}; Robbie replied {model_t[:80]!r}."
                        remember_fact(snippet, source="turn")

                    # Only schedule here if we somehow never started speaking audio
                    if not shared.brain_scheduled_this_turn and (
                        turn_model_audio_seen or (turn_had_user and model_t)
                    ):
                        schedule_reactive_brain(shared, user_t, model_t)

                    shared.tool_moved_this_turn = False
                    shared.brain_scheduled_this_turn = False
                    shared.turn_audio_pcm.clear()
    finally:
        shared.is_playing = False
        play_q.put(None)
        await player_task
        log.info("Live receive loop ended")


async def live_conversation_task(shared: SharedState) -> None:
    client = shared.client
    backoff = 1.0

    while not shared.shutdown.is_set():
        if not shared.voice_enabled.is_set():
            shared.live_session = None
            shared.is_playing = False
            log.info("Voice off — Live idle (proactivity still running)")
            await shared.voice_enabled.wait()
            if shared.shutdown.is_set():
                break
            backoff = 1.0

        try:
            voice = shared.voice_name or get_voice_name()
            log.info("Connecting Live %s voice=%s …", LIVE_MODEL, voice)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=build_live_system_instruction(),
                tools=live_tool_declarations(),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
                realtime_input_config=types.RealtimeInputConfig(
                    # Allow natural barge-in after Robbie finishes; hear soft speech better
                    activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                        prefix_padding_ms=40,
                        silence_duration_ms=800,
                    ),
                ),
            )
            shared.force_live_reconnect = False
            async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                shared.live_session = session
                shared.is_playing = False
                backoff = 1.0
                log.info("Live session connected")

                mic_task = asyncio.create_task(_mic_send_loop(session, shared))
                recv_task = asyncio.create_task(_receive_loop(session, shared))

                async def _wait_stop() -> None:
                    while (
                        shared.voice_enabled.is_set()
                        and not shared.shutdown.is_set()
                        and not shared.force_live_reconnect
                    ):
                        await asyncio.sleep(VOICE_POLL_S)

                stop_task = asyncio.create_task(_wait_stop())
                shutdown_waiter = asyncio.create_task(shared.shutdown.wait())

                done, pending = await asyncio.wait(
                    {mic_task, recv_task, stop_task, shutdown_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                if shared.shutdown.is_set():
                    break
                if shared.force_live_reconnect:
                    log.info("Reconnecting Live (voice/config change)")
                    continue
                if not shared.voice_enabled.is_set():
                    log.info("Voice turned off — disconnecting Live")
                    continue

                for task in done:
                    if task in (stop_task, shutdown_waiter):
                        continue
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    if exc:
                        raise exc

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            shared.live_session = None
            if shared.shutdown.is_set():
                break
            if not shared.voice_enabled.is_set():
                continue
            log.error("Live session error: %s — reconnecting in %.1fs", exc, backoff)
            try:
                await asyncio.wait_for(shared.shutdown.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)
        finally:
            shared.live_session = None
            shared.is_playing = False

    log.info("Live conversation task stopped")


# ---------------------------------------------------------------------------
# Wake word ("robbie") while proactive-only
# ---------------------------------------------------------------------------

WAKE_PATTERNS = re.compile(
    r"\b(hey\s+)?robbie\b|\bरॉबी\b|\bरोबी\b|罗比|羅比",
    re.IGNORECASE,
)


async def _clip_contains_wake_word(client: genai.Client, wav_bytes: bytes) -> bool:
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                        types.Part(
                            text=(
                                "Transcribe briefly. Then answer YES or NO on its own line: "
                                "did the speaker clearly say the wake word Robbie "
                                "(or Hey Robbie / रॉबी / 罗比)?"
                            )
                        ),
                    ],
                )
            ],
        )
        text = (getattr(response, "text", None) or "").strip()
        log.info("Wake check: %r", text[:120])
        if WAKE_PATTERNS.search(text):
            return True
        last = text.splitlines()[-1].strip().upper() if text else ""
        return last.startswith("YES")
    except Exception as exc:
        log.warning("Wake-word check failed: %s", exc)
        return False


async def wake_word_task(shared: SharedState) -> None:
    """When voice is OFF, listen for 'Robbie' and flip voice mode on."""
    log.info("Wake-word listener ready (say 'Robbie' in proactive mode)")
    loop = asyncio.get_running_loop()
    audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
    last_wake = 0.0

    def _callback(indata: Any, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        if status:
            log.debug("Wake mic status: %s", status)
        pcm = bytes(indata)
        try:
            loop.call_soon_threadsafe(audio_q.put_nowait, pcm)
        except asyncio.QueueFull:
            pass

    stream: Optional[sd.RawInputStream] = None

    try:
        while not shared.shutdown.is_set():
            # Only listen while proactive-only
            if shared.voice_enabled.is_set():
                if stream is not None:
                    stream.stop()
                    stream.close()
                    stream = None
                    log.info("Wake mic paused (voice ON)")
                await asyncio.sleep(0.4)
                continue

            if stream is None:
                stream = sd.RawInputStream(
                    samplerate=INPUT_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_FRAMES,
                    callback=_callback,
                )
                stream.start()
                log.info("Wake mic listening for 'Robbie'…")

            # Collect an energy-gated clip
            clip = bytearray()
            speech_started = False
            silence_chunks = 0
            need_chunks = int(WAKE_CLIP_S * INPUT_SAMPLE_RATE / CHUNK_FRAMES)
            max_chunks = need_chunks + 8
            chunks = 0

            while chunks < max_chunks and not shared.shutdown.is_set() and not shared.voice_enabled.is_set():
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if speech_started:
                        break
                    continue
                rms = _chunk_rms(chunk)
                if rms >= WAKE_RMS_THRESHOLD:
                    speech_started = True
                    silence_chunks = 0
                    clip.extend(chunk)
                elif speech_started:
                    silence_chunks += 1
                    clip.extend(chunk)
                    if silence_chunks >= 6:  # ~0.4s quiet after speech
                        break
                chunks += 1

            if shared.voice_enabled.is_set() or shared.shutdown.is_set():
                continue
            if len(clip) < INPUT_SAMPLE_RATE:  # < ~0.5s of audio
                continue
            if time.monotonic() - last_wake < WAKE_COOLDOWN_S:
                continue

            wav = pcm16_to_wav_bytes(bytes(clip), rate=INPUT_SAMPLE_RATE)
            hit = await _clip_contains_wake_word(shared.client, wav)
            if hit:
                last_wake = time.monotonic()
                log.info("Wake word detected — enabling voice mode")
                write_voice_mode_file(True)
                shared.voice_enabled.set()
                # Tiny acknowledgment motion
                fallback = serial_command_to_action(pick_fallback_serial(shared))
                if fallback:
                    await send_robot_action(
                        shared,
                        direction=fallback["direction"],
                        duration_seconds=fallback["duration_seconds"],
                        speed=fallback["speed"],
                        expression=fallback["expression"],
                        source="wake",
                        include_audio=False,
                    )

    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        log.info("Wake-word listener stopped")


# ---------------------------------------------------------------------------
# Idle proactivity
# ---------------------------------------------------------------------------

async def proactivity_task(shared: SharedState) -> None:
    log.info(
        "Proactivity brain started (interval=%.0fs, cascade=%s)",
        PROACTIVITY_INTERVAL_S,
        " → ".join(BRAIN_MODELS),
    )
    while not shared.shutdown.is_set():
        try:
            await asyncio.wait_for(shared.shutdown.wait(), timeout=PROACTIVITY_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

        idle_seconds = time.monotonic() - shared.last_interaction_time
        recent = list(shared.recent_actions)
        log.info(
            "Proactivity tick — idle=%.1fs voice=%s brain=%s",
            idle_seconds,
            "on" if shared.voice_enabled.is_set() else "off",
            BRAIN_MODELS[shared.brain_model_index],
        )
        await call_brain(
            shared,
            build_brain_prompt_idle(
                idle_seconds, shared.voice_enabled.is_set(), recent
            ),
            reason="idle",
            source="brain_idle",
            fallback_serial=pick_fallback_serial(shared) if idle_seconds >= 45 else None,
        )

    log.info("Proactivity brain stopped")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    api_key = resolve_api_key()
    if not api_key:
        raise SystemExit(
            "No API key found. Run: robbie set-key YOUR_KEY\n"
            f"Or set GOOGLE_API_KEY / write google_api_key into {CONFIG_PATH}"
        )

    cfg = load_config()
    if cfg.get("google_api_key") != api_key:
        cfg["google_api_key"] = api_key
        save_config(cfg)
        log.info("Saved API key to %s", CONFIG_PATH)
    if "voice_name" not in cfg:
        cfg["voice_name"] = "Puck"
        save_config(cfg)
    if "bridge_url" not in cfg:
        cfg["bridge_url"] = DEFAULT_BRIDGE_URL
        cfg["bridge_timeout_s"] = DEFAULT_BRIDGE_TIMEOUT_S
        save_config(cfg)
    if not VOICE_MODE_PATH.exists():
        write_voice_mode_file(False)
    if not MEMORY_PATH.exists():
        save_memory({"facts": []})

    shared = SharedState()
    shared.client = genai.Client(api_key=api_key)
    shared.voice_name = get_voice_name()

    bridge = load_bridge_config()
    log.info("HTTP bridge target: %s", bridge["bridge_url"])
    if IS_PI:
        log.info("Pi Zero slim mode: brain=%s mic_q=%d play_q=%d", BRAIN_MODELS, MIC_QUEUE_SIZE, PLAY_QUEUE_SIZE)

    watcher = asyncio.create_task(control_watcher(shared), name="control")
    live_task = asyncio.create_task(live_conversation_task(shared), name="live")
    brain_task = asyncio.create_task(proactivity_task(shared), name="brain")
    wake_task = asyncio.create_task(wake_word_task(shared), name="wake")

    try:
        await asyncio.gather(watcher, live_task, brain_task, wake_task)
    except asyncio.CancelledError:
        pass
    finally:
        shared.shutdown.set()
        shared.voice_enabled.set()
        for task in (watcher, live_task, brain_task, wake_task):
            task.cancel()
        await asyncio.gather(
            watcher, live_task, brain_task, wake_task, return_exceptions=True
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
