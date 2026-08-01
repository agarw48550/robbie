"""Asyncio event bus — subsystems communicate only through events."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from config.settings import log

EventHandler = Callable[["Event"], Any]


@dataclass(frozen=True)
class Event:
    """Immutable bus message."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)


class EventBus:
    """Fan-out event bus backed by an ``asyncio.Queue``."""

    def __init__(self, *, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[Optional[Event]] = asyncio.Queue(maxsize=maxsize)
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._running = False

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    async def publish(self, event_type: str, payload: Optional[dict[str, Any]] = None) -> Event:
        event = Event(type=event_type, payload=dict(payload or {}))
        await self._queue.put(event)
        return event

    def publish_nowait(self, event_type: str, payload: Optional[dict[str, Any]] = None) -> Event:
        event = Event(type=event_type, payload=dict(payload or {}))
        self._queue.put_nowait(event)
        return event

    async def _dispatch(self, event: Event) -> None:
        handlers = list(self._handlers.get(event.type, ()))
        handlers.extend(self._handlers.get("*", ()))
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    await result  # type: ignore[misc]
            except Exception as exc:
                log.error("Event handler error for %s: %s", event.type, exc)

    async def run(self) -> None:
        """Drain the queue until ``stop()`` is called."""
        self._running = True
        log.info("EventBus started")
        try:
            while True:
                event = await self._queue.get()
                if event is None:
                    break
                await self._dispatch(event)
        finally:
            self._running = False
            log.info("EventBus stopped")

    async def stop(self) -> None:
        await self._queue.put(None)


# Canonical event type strings (architecture contract)
EVT_STATE_CHANGED = "robot.state_changed"
EVT_EMOTION_CHANGED = "robot.emotion_changed"
EVT_ROBOT_ACTION = "robot.action"
EVT_SHUTDOWN = "system.shutdown"
