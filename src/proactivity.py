"""Idle proactivity brain loop."""

from __future__ import annotations

import asyncio
import time

from config.settings import BRAIN_MODELS, PROACTIVITY_INTERVAL_S, log
from src.brain import build_brain_prompt_idle, call_brain
from src.bridge import pick_fallback_serial
from src.state import SharedState


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
