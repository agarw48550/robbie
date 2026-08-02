"""Asyncio event bus — subsystems communicate only through events."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from config.settings import log

EventHandler = Callable[["Event"], Any]

_TRACE_MAXLEN = 100


@dataclass(frozen=True)
class Event:
    """Immutable bus message."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)
    priority: int = 0  # higher first
    sticky: bool = False


class EventBus:
    """Fan-out event bus with priority drain, sticky retention, and tracing."""

    def __init__(self, *, maxsize: int = 0) -> None:
        # Unused for capacity (heap is unbounded); kept for API compatibility.
        self._maxsize = maxsize
        self._heap: list[tuple[int, int, Optional[Event]]] = []
        self._seq = itertools.count()
        self._wake = asyncio.Event()
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._sticky: dict[str, dict[str, Any]] = {}
        self._trace: deque[Event] = deque(maxlen=_TRACE_MAXLEN)
        self._running = False
        self._stopped = False

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

    def get_sticky(self, event_type: str) -> Optional[dict[str, Any]]:
        """Return the last sticky payload for ``event_type``, if any."""
        payload = self._sticky.get(event_type)
        return dict(payload) if payload is not None else None

    def get_trace(self) -> list[Event]:
        """Return a copy of the last N published events (newest last)."""
        return list(self._trace)

    def _enqueue(self, event: Optional[Event], *, priority: int = 0) -> None:
        # heapq is min-heap → negate priority so higher values drain first.
        heapq.heappush(self._heap, (-int(priority), next(self._seq), event))
        self._wake.set()

    async def publish(
        self,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
        sticky: bool = False,
    ) -> Event:
        event = Event(
            type=event_type,
            payload=dict(payload or {}),
            priority=int(priority),
            sticky=bool(sticky),
        )
        if event.sticky:
            self._sticky[event.type] = dict(event.payload)
        self._trace.append(event)
        self._enqueue(event, priority=event.priority)
        return event

    def publish_nowait(
        self,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
        sticky: bool = False,
    ) -> Event:
        event = Event(
            type=event_type,
            payload=dict(payload or {}),
            priority=int(priority),
            sticky=bool(sticky),
        )
        if event.sticky:
            self._sticky[event.type] = dict(event.payload)
        self._trace.append(event)
        self._enqueue(event, priority=event.priority)
        return event

    async def _get_next(self) -> Optional[Event]:
        while True:
            if self._heap:
                _prio, _seq, event = heapq.heappop(self._heap)
                return event
            if self._stopped:
                return None
            self._wake.clear()
            # Re-check after clear to avoid a lost wakeup.
            if self._heap:
                continue
            if self._stopped:
                return None
            await self._wake.wait()

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
        """Drain the priority heap until ``stop()`` is called."""
        self._running = True
        self._stopped = False
        log.info("EventBus started")
        try:
            while True:
                event = await self._get_next()
                if event is None:
                    break
                await self._dispatch(event)
        finally:
            self._running = False
            log.info("EventBus stopped")

    async def stop(self) -> None:
        self._stopped = True
        # Low priority sentinel: drain pending events first, then wake the loop.
        self._enqueue(None, priority=-(10**9))


# Canonical event type strings (architecture contract)
EVT_STATE_CHANGED = "robot.state_changed"
EVT_EMOTION_CHANGED = "robot.emotion_changed"
EVT_ROBOT_ACTION = "robot.action"
EVT_INTENTION = "robot.intention"
EVT_SHUTDOWN = "system.shutdown"
