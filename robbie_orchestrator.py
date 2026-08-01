#!/usr/bin/env python3
"""DEPRECATED — use ``main.py`` as the entry point.

This module re-exports the reorganized package so existing imports keep working:
  from robbie_orchestrator import set_bridge_url, VALID_VOICES, ...
"""

from __future__ import annotations

import asyncio

# Re-export public API used by bin/robbie and external callers
from config.settings import (  # noqa: F401
    AMBIENT_RMS_THRESHOLD,
    BRAIN_MODELS,
    BRAIN_MODELS_FULL,
    BRAIN_MODELS_PI,
    BRAIN_RETRIES_PER_MODEL,
    CHANNELS,
    CHUNK_FRAMES,
    CONFIG_DIR,
    CONFIG_PATH,
    DEFAULT_BRIDGE_TIMEOUT_S,
    DEFAULT_BRIDGE_URL,
    DIGIT_TO_DIR,
    DIGIT_TO_EXPR,
    DIR_NAME_TO_DIGIT,
    EXPR_NAME_TO_DIGIT,
    FALLBACK_SERIAL_COMMAND,
    FALLBACK_SERIAL_POOL,
    INPUT_SAMPLE_RATE,
    IS_PI,
    LIVE_MODEL,
    MAX_MEMORY_FACTS,
    MEMORY_PATH,
    MIC_QUEUE_SIZE,
    OUTPUT_SAMPLE_RATE,
    PLAY_QUEUE_SIZE,
    PROACTIVITY_INTERVAL_S,
    REACTIVE_BRAIN_MIN_INTERVAL_S,
    SERIAL_COMMAND_RE,
    TURN_AUDIO_MAX_BYTES,
    VALID_ACTION_TYPES,
    VALID_VOICES,
    VOICE_MODE_PATH,
    VOICE_POLL_S,
    WAKE_CLIP_S,
    WAKE_COOLDOWN_S,
    WAKE_RMS_THRESHOLD,
    is_pi_zero,
    log,
)
from src.app import main  # noqa: F401
from src.audio import (  # noqa: F401
    append_turn_audio,
    encode_audio_wav_b64,
    pcm16_to_wav_bytes,
)
from src.audio import chunk_rms as _chunk_rms  # noqa: F401
from src.brain import (  # noqa: F401
    PROTOCOL_BLOCK,
    JSON_SCHEMA_BLOCK,
    build_brain_prompt_idle,
    build_brain_prompt_reactive,
    call_brain,
    execute_brain_decision,
    merge_transcript,
    parse_brain_response,
    schedule_reactive_brain,
)
from src.bridge import (  # noqa: F401
    action_key,
    build_robot_action,
    build_serial_command,
    is_valid_serial_command,
    pick_fallback_serial,
    send_robot_action,
    send_robot_action_from_serial,
    serial_command_to_action,
)
from src.control import control_watcher  # noqa: F401
from src.live import live_conversation_task  # noqa: F401
from src.live_tools import handle_live_tool, live_tool_declarations  # noqa: F401
from src.persistence import (  # noqa: F401
    build_live_system_instruction,
    get_voice_name,
    load_bridge_config,
    load_config,
    load_memory,
    memory_summary_for_prompt,
    read_voice_mode_file,
    remember_fact,
    resolve_api_key,
    save_config,
    save_memory,
    set_bridge_url,
    set_voice_name,
    write_voice_mode_file,
)
from src.proactivity import proactivity_task  # noqa: F401
from src.state import SharedState  # noqa: F401
from src.wake import WAKE_PATTERNS, wake_word_task  # noqa: F401

if __name__ == "__main__":
    import warnings

    warnings.warn(
        "robbie_orchestrator.py is deprecated; run main.py instead",
        DeprecationWarning,
        stacklevel=1,
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
