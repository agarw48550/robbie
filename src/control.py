"""Control-file watchers for voice mode and speaking voice."""

from __future__ import annotations

import asyncio

from config.settings import VOICE_POLL_S, log
from src.persistence import get_voice_name, read_voice_mode_file
from src.state import SharedState


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
