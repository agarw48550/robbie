"""Robbie configuration constants and runtime defaults.

Moved from robbie_orchestrator.py without behavioural changes.
"""

from __future__ import annotations

import logging
import os
import platform
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "robbie"
CONFIG_PATH = CONFIG_DIR / "config.json"
VOICE_MODE_PATH = CONFIG_DIR / "voice_mode"  # "on" | "off"
MEMORY_PATH = CONFIG_DIR / "memory.json"
DB_PATH = CONFIG_DIR / "robbie.db"

# Gated K10 mic/wake/playback cutover (default OFF — Pi sounddevice stays active).
# When ROBBIE_BODY_AUDIO=1, code logs K10 path selection but does not remove Pi I/O
# until WebSocket audio streaming + parity tests land. See src/audio_routing.py.
ROBBIE_BODY_AUDIO_DEFAULT = False

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
