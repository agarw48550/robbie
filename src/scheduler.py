"""Lightweight asyncio scheduler that emits events after delays / intervals."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from config.settings import log
from src.events import EventBus


class Scheduler:
    """Schedule future EventBus publications without embedding subsystem logic."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._tasks: set[asyncio.Task[Any]] = set()
        self._shutdown = asyncio.Event()

    def call_later(
        self,
        delay_s: float,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> asyncio.Task[Any]:
        async def _run() -> None:
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=max(0.0, delay_s))
                return  # shut down before fire
            except asyncio.TimeoutError:
                pass
            if self._shutdown.is_set():
                return
            await self._bus.publish(event_type, payload)

        task = asyncio.create_task(_run(), name=f"sched:{event_type}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def call_periodic(
        self,
        interval_s: float,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
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
                await self._bus.publish(event_type, payload)

        task = asyncio.create_task(_run(), name=f"sched-periodic:{event_type}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

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
