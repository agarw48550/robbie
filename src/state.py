"""Shared asyncio state for the Robbie orchestrator."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.command_bus import CommandBus
    from src.emotion_engine import EmotionEngine
    from src.events import EventBus
    from src.robot_state import RobotStateMachine
    from src.scheduler import Scheduler


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
    # Event-driven OS layer (attached in app.py before Live AI)
    event_bus: Optional["EventBus"] = None
    scheduler: Optional["Scheduler"] = None
    emotion_engine: Optional["EmotionEngine"] = None
    command_bus: Optional["CommandBus"] = None
    state_machine: Optional["RobotStateMachine"] = None
