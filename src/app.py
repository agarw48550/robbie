"""Orchestrator assembly — asyncio entry for Robbie."""

from __future__ import annotations

import asyncio

from google import genai

from config.env import load_dotenv_files
from config.logging_setup import setup_logging
from config.settings import (
    CONFIG_PATH,
    DEFAULT_BRIDGE_TIMEOUT_S,
    DEFAULT_BRIDGE_URL,
    IS_PI,
    BRAIN_MODELS,
    MEMORY_PATH,
    MIC_QUEUE_SIZE,
    PLAY_QUEUE_SIZE,
    VOICE_MODE_PATH,
    log,
)
from src.command_bus import CommandBus
from src.control import control_watcher
from src.emotion_engine import EmotionEngine
from src.events import EventBus
from src.live import live_conversation_task
from src.persistence import (
    get_voice_name,
    load_bridge_config,
    load_config,
    resolve_api_key,
    save_config,
    save_memory,
    write_voice_mode_file,
)
from src.proactivity import proactivity_task
from src.robot_state import RobotState, RobotStateMachine
from src.scheduler import Scheduler
from src.state import SharedState
from src.perf import get_metrics
from src.transport import create_transport
from src.wake import wake_word_task


async def main() -> None:
    load_dotenv_files()
    setup_logging()
    metrics = get_metrics()

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
    if "bridge_transport" not in cfg:
        cfg["bridge_transport"] = "http"
        save_config(cfg)
    if not VOICE_MODE_PATH.exists():
        write_voice_mode_file(False)
    if not MEMORY_PATH.exists():
        save_memory({"facts": []})

    shared = SharedState()
    shared.client = genai.Client(api_key=api_key)
    shared.voice_name = get_voice_name()

    # --- Event-driven OS layer (before Live AI) ---
    event_bus = EventBus()
    scheduler = Scheduler(event_bus)
    emotion_engine = EmotionEngine(event_bus)
    transport = create_transport()
    await transport.connect()
    command_bus = CommandBus(event_bus, shared, transport)
    state_machine = RobotStateMachine(event_bus, RobotState.BOOTING)

    shared.event_bus = event_bus
    shared.scheduler = scheduler
    shared.emotion_engine = emotion_engine
    shared.command_bus = command_bus
    shared.state_machine = state_machine
    shared.transport = transport

    bus_task = asyncio.create_task(event_bus.run(), name="event_bus")
    scheduler_task = asyncio.create_task(scheduler.run(), name="scheduler")
    await state_machine.set_state(RobotState.IDLE, reason="boot_complete")

    bridge = load_bridge_config()
    log.info(
        "Body transport=%s target=%s",
        bridge.get("bridge_transport", "http"),
        bridge["bridge_url"],
    )
    if IS_PI:
        log.info("Pi Zero slim mode: brain=%s mic_q=%d play_q=%d", BRAIN_MODELS, MIC_QUEUE_SIZE, PLAY_QUEUE_SIZE)
        # Smaller event trace on constrained RAM
        if hasattr(event_bus, "_trace") and getattr(event_bus._trace, "maxlen", None) != 32:
            from collections import deque

            event_bus._trace = deque(event_bus._trace, maxlen=32)

    # Body controller (sole hardware egress façade)
    from src.body_controller import BodyController

    body = BodyController(event_bus, command_bus, state_machine)
    shared.body_controller = body
    metrics.mark_boot_complete()
    metrics.log_snapshot()

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
        scheduler.stop()
        await event_bus.stop()
        await transport.disconnect()
        for task in (watcher, live_task, brain_task, wake_task, bus_task, scheduler_task):
            task.cancel()
        await asyncio.gather(
            watcher,
            live_task,
            brain_task,
            wake_task,
            bus_task,
            scheduler_task,
            return_exceptions=True,
        )
