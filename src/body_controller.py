"""Body controller — sole hardware egress façade over CommandBus."""

from __future__ import annotations

from typing import Any, Optional

from config.settings import log
from src.command_bus import CommandBus
from src.events import EVT_INTENTION, EVT_ROBOT_ACTION, Event, EventBus
from src.robot_state import RobotState, RobotStateMachine


class BodyController:
    """Subscribes to action/intention events and executes via CommandBus.

    Takes over ``EVT_ROBOT_ACTION`` from CommandBus to avoid double-sends, while
    keeping ``CommandBus.send`` as the actual transport path (same ESP32 JSON).
    """

    def __init__(
        self,
        event_bus: EventBus,
        command_bus: CommandBus,
        state_machine: RobotStateMachine,
    ) -> None:
        self._bus = event_bus
        self._cmd = command_bus
        self._sm = state_machine
        # Face / motor / LED / audio / sensor façades (no direct transport).
        self.face = FaceController(self)
        self.motor = MotorController(self)
        self.led = LEDController(self)
        self.audio = AudioController(self)
        self.sensor = SensorController(self)

        # Avoid double-dispatch: CommandBus also subscribed to EVT_ROBOT_ACTION.
        event_bus.unsubscribe(EVT_ROBOT_ACTION, command_bus._on_action_event)
        event_bus.subscribe(EVT_ROBOT_ACTION, self._on_robot_action)
        event_bus.subscribe(EVT_INTENTION, self._on_intention)
        log.info("BodyController attached (action + intention)")

    async def execute_action(
        self,
        *,
        direction: str,
        duration_seconds: int,
        speed: int,
        expression: str,
        source: str,
        transcript: str = "",
        include_audio: bool = True,
        set_moving: bool = True,
    ) -> bool:
        """Execute a body action (same kwargs as ``CommandBus.send``)."""
        prev = self._sm.state
        if set_moving and prev is not RobotState.MOVING:
            await self._sm.set_state(RobotState.MOVING, reason=source or "body")
        try:
            return await self._cmd.send(
                direction=direction,
                duration_seconds=duration_seconds,
                speed=speed,
                expression=expression,
                source=source,
                transcript=transcript,
                include_audio=include_audio,
            )
        finally:
            if set_moving and prev is not RobotState.MOVING and self._sm.state is RobotState.MOVING:
                await self._sm.set_state(prev, reason=f"restore_after_{source or 'body'}")

    async def _on_robot_action(self, event: Event) -> None:
        await self._execute_from_payload(event.payload, default_source="event")

    async def _on_intention(self, event: Event) -> None:
        payload = event.payload
        # Intention may nest action fields under "action" or be flat.
        nested = payload.get("action")
        if isinstance(nested, dict):
            data = {**payload, **nested}
        else:
            data = payload
        await self._execute_from_payload(data, default_source="intention")

    async def _execute_from_payload(
        self,
        payload: dict[str, Any],
        *,
        default_source: str,
    ) -> None:
        direction = str(payload.get("direction", "") or "")
        if not direction:
            log.debug("BodyController skip — no direction in %s", default_source)
            return
        await self.execute_action(
            direction=direction,
            duration_seconds=int(payload.get("duration_seconds", 0) or 0),
            speed=int(payload.get("speed", 5) or 5),
            expression=str(payload.get("expression", "curious")),
            source=str(payload.get("source", default_source)),
            transcript=str(payload.get("transcript", "")),
            include_audio=bool(payload.get("include_audio", True)),
        )


class FaceController:
    """Thin façade — expression via BodyController only."""

    def __init__(self, body: BodyController) -> None:
        self._body = body

    async def set_expression(
        self,
        expression: str,
        *,
        source: str = "face",
        include_audio: bool = False,
    ) -> bool:
        # duration 0 → no drive on ESP32 (same as actions.express).
        return await self._body.execute_action(
            direction="forward",
            duration_seconds=0,
            speed=5,
            expression=expression,
            source=source,
            include_audio=include_audio,
            set_moving=False,
        )


class MotorController:
    """Thin façade — motion via BodyController only."""

    def __init__(self, body: BodyController) -> None:
        self._body = body

    async def drive(
        self,
        direction: str,
        duration_seconds: int,
        speed: int = 5,
        *,
        expression: str = "curious",
        source: str = "motor",
    ) -> bool:
        return await self._body.execute_action(
            direction=direction,
            duration_seconds=duration_seconds,
            speed=speed,
            expression=expression,
            source=source,
            include_audio=False,
        )


class LEDController:
    """Thin façade — LED colour is emotion-layer today; no direct transport."""

    def __init__(self, body: BodyController) -> None:
        self._body = body
        self._colour: str = "#4488FF"

    @property
    def colour(self) -> str:
        return self._colour

    async def set_colour(self, colour: str, *, source: str = "led") -> None:
        # LED is not yet an ESP32 JSON field; retain locally for Emotion/OS use.
        self._colour = colour
        log.debug("LEDController colour=%s source=%s", colour, source)


class AudioController:
    """Thin façade — speech playback piggybacks on action audio field."""

    def __init__(self, body: BodyController) -> None:
        self._body = body

    async def speak_with_action(
        self,
        *,
        direction: str = "forward",
        duration_seconds: int = 0,
        speed: int = 5,
        expression: str = "happy",
        source: str = "audio",
        transcript: str = "",
    ) -> bool:
        return await self._body.execute_action(
            direction=direction,
            duration_seconds=duration_seconds,
            speed=speed,
            expression=expression,
            source=source,
            transcript=transcript,
            include_audio=True,
            set_moving=duration_seconds > 0,
        )


class SensorController:
    """Thin façade — sensors not on the wire yet; placeholder for EventBus feeds."""

    def __init__(self, body: BodyController) -> None:
        self._body = body
        self._last: dict[str, Any] = {}

    @property
    def last(self) -> dict[str, Any]:
        return dict(self._last)

    def note_reading(self, name: str, value: Any) -> None:
        self._last[name] = value
