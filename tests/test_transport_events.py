"""Transport + EventBus parity tests."""

from __future__ import annotations

import asyncio

from src.command_bus import CommandBus
from src.events import EVT_INTENTION, EventBus
from src.state import SharedState
from src.transport import HttpTransport, create_transport


def test_create_transport_defaults_to_http() -> None:
    t = create_transport("http")
    assert isinstance(t, HttpTransport)


def test_http_transport_connect_disconnect() -> None:
    async def _run() -> None:
        t = HttpTransport(url="http://127.0.0.1:9/robot")
        await t.connect()
        await t.disconnect()

    asyncio.run(_run())


def test_command_bus_requires_transport() -> None:
    shared = SharedState()
    bus = EventBus()
    t = HttpTransport(url="http://127.0.0.1/robot")
    cmd = CommandBus(bus, shared, t)
    payload = cmd.to_esp32_json(
        direction="forward",
        duration_seconds=1,
        speed=5,
        expression="happy",
        source="test",
    )
    assert payload is not None
    assert payload["expression"] == "happy"


def test_event_bus_priority_and_sticky() -> None:
    async def _run() -> None:
        bus = EventBus()
        seen: list[str] = []

        async def handler(event) -> None:  # type: ignore[no-untyped-def]
            seen.append(event.type)

        bus.subscribe("a", handler)
        bus.subscribe("b", handler)
        task = asyncio.create_task(bus.run())
        await bus.publish("a", {"x": 1}, priority=1)
        await bus.publish("b", {"y": 2}, priority=10, sticky=True)
        await asyncio.sleep(0.05)
        await bus.stop()
        await task
        assert "b" in seen and "a" in seen
        # higher priority b should appear before a
        assert seen.index("b") < seen.index("a")
        assert bus.get_sticky("b") == {"y": 2}
        assert EVT_INTENTION == "robot.intention"

    asyncio.run(_run())
