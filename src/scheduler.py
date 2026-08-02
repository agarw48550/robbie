"""Lightweight asyncio scheduler that emits events after delays / intervals / cron."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import log
from src.events import EventBus

# Simple reminder event type (tools / proactive can subscribe)
EVT_REMINDER = "scheduler.reminder"
EVT_CRON = "scheduler.cron"

_CRON_RE = re.compile(
    r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$"
)


def _cron_field_matches(field: str, value: int, *, min_v: int, max_v: int) -> bool:
    """Match a single cron field (supports *, N, */N, A-B, comma lists)."""
    field = field.strip()
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                return False
            if step <= 0:
                return False
            if value % step == 0 and min_v <= value <= max_v:
                return True
            continue
        if "-" in part:
            try:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                return False
            if lo <= value <= hi:
                return True
            continue
        try:
            if int(part) == value:
                return True
        except ValueError:
            return False
    return False


def cron_matches(cron_expr: str, when: Optional[datetime] = None) -> bool:
    """Return True if ``cron_expr`` (min hour dom mon dow) matches ``when`` (UTC)."""
    m = _CRON_RE.match(cron_expr or "")
    if not m:
        return False
    minute_f, hour_f, dom_f, mon_f, dow_f = m.groups()
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)

    # cron dow: 0=Sunday … 6=Saturday; Python weekday(): 0=Monday … 6=Sunday
    dow = (when.weekday() + 1) % 7
    return (
        _cron_field_matches(minute_f, when.minute, min_v=0, max_v=59)
        and _cron_field_matches(hour_f, when.hour, min_v=0, max_v=23)
        and _cron_field_matches(dom_f, when.day, min_v=1, max_v=31)
        and _cron_field_matches(mon_f, when.month, min_v=1, max_v=12)
        and _cron_field_matches(dow_f, dow, min_v=0, max_v=6)
    )


class Scheduler:
    """Schedule future EventBus publications without embedding subsystem logic."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._tasks: set[asyncio.Task[Any]] = set()
        self._shutdown = asyncio.Event()

    def _track(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def call_later(
        self,
        delay_s: float,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
    ) -> asyncio.Task[Any]:
        async def _run() -> None:
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=max(0.0, delay_s))
                return  # shut down before fire
            except asyncio.TimeoutError:
                pass
            if self._shutdown.is_set():
                return
            await self._bus.publish(event_type, payload, priority=priority)

        task = asyncio.create_task(_run(), name=f"sched:{event_type}")
        return self._track(task)

    def call_periodic(
        self,
        interval_s: float,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
    ) -> asyncio.Task[Any]:
        async def _run() -> None:
            while not self._shutdown.is_set():
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(), timeout=max(0.01, interval_s)
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                if self._shutdown.is_set():
                    break
                await self._bus.publish(event_type, payload, priority=priority)

        task = asyncio.create_task(_run(), name=f"sched-periodic:{event_type}")
        return self._track(task)

    def schedule_cron(
        self,
        cron_expr: str,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
        check_interval_s: float = 30.0,
    ) -> asyncio.Task[Any]:
        """Fire ``event_type`` when ``cron_expr`` matches (polled approx every 30s).

        Uses a simple 5-field cron parser (no croniter dependency). Interval
        approximation: checks wall-clock each ``check_interval_s`` and fires at
        most once per matching minute.
        """
        base_payload = dict(payload or {})
        base_payload.setdefault("cron", cron_expr)

        async def _run() -> None:
            last_minute: Optional[str] = None
            while not self._shutdown.is_set():
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=max(1.0, check_interval_s),
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                if self._shutdown.is_set():
                    break
                now = datetime.now(timezone.utc)
                minute_key = now.strftime("%Y-%m-%dT%H:%M")
                if minute_key == last_minute:
                    continue
                if cron_matches(cron_expr, now):
                    last_minute = minute_key
                    await self._bus.publish(
                        event_type,
                        {**base_payload, "fired_at": now.isoformat()},
                        priority=priority,
                    )

        task = asyncio.create_task(_run(), name=f"sched-cron:{event_type}")
        return self._track(task)

    def schedule_reminder(
        self,
        when_iso: str,
        text: str,
        *,
        priority: int = 5,
        event_type: str = EVT_REMINDER,
    ) -> asyncio.Task[Any]:
        """Schedule a reminder at an ISO-8601 timestamp; publishes an event."""
        try:
            when = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
        except ValueError:
            log.warning("Invalid reminder time %r — firing immediately", when_iso)
            when = datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delay = max(0.0, (when - now).total_seconds())
        return self.call_later(
            delay,
            event_type,
            {"text": text, "when": when.isoformat(), "source": "reminder"},
            priority=priority,
        )

    def schedule_priority(
        self,
        delay_s: float,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        priority: int = 0,
    ) -> asyncio.Task[Any]:
        """Priority job helper — same as call_later with explicit priority."""
        return self.call_later(delay_s, event_type, payload, priority=priority)

    async def run(self) -> None:
        """Keep the scheduler supervisor alive until stop()."""
        log.info("Scheduler started")
        try:
            await self._shutdown.wait()
        finally:
            for task in list(self._tasks):
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            log.info("Scheduler stopped")

    def stop(self) -> None:
        self._shutdown.set()
