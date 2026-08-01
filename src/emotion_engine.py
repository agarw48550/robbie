"""Emotion / embodiment mapping from RobotState.

No Gemini logic — pure state → face / motion / LED / voice-speed lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config.settings import log
from src.actions import MotorMotion
from src.events import EVT_EMOTION_CHANGED, EVT_STATE_CHANGED, Event, EventBus
from src.robot_state import RobotState, parse_robot_state


@dataclass(frozen=True)
class EmotionOutput:
    """Embodiment parameters derived from robot state."""

    face: str
    motor: Optional[MotorMotion]
    led_colour: str
    voice_speed: float


# Face names match existing expression vocabulary.
# Motor is None here so EmotionEngine never invents extra motion (behaviour preserved).
# LED / voice_speed are architectural outputs; ESP32 JSON path unchanged unless CommandBus
# is explicitly asked to send an action.
_STATE_MAP: dict[RobotState, EmotionOutput] = {
    RobotState.BOOTING: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#00FF00",
        voice_speed=1.0,
    ),
    RobotState.IDLE: EmotionOutput(
        face="calm",
        motor=None,
        led_colour="#4488FF",
        voice_speed=1.0,
    ),
    RobotState.LISTENING: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#00CCFF",
        voice_speed=1.0,
    ),
    RobotState.THINKING: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#AA66FF",
        voice_speed=1.0,
    ),
    RobotState.SPEAKING: EmotionOutput(
        face="happy",
        motor=None,
        led_colour="#FFAA00",
        voice_speed=1.0,
    ),
    RobotState.MOVING: EmotionOutput(
        face="surprised",
        motor=None,
        led_colour="#FF6600",
        voice_speed=1.0,
    ),
    RobotState.SLEEPING: EmotionOutput(
        face="calm",
        motor=None,
        led_colour="#223355",
        voice_speed=0.9,
    ),
    RobotState.ERROR: EmotionOutput(
        face="worried",
        motor=None,
        led_colour="#FF0000",
        voice_speed=1.0,
    ),
}


class EmotionEngine:
    """Subscribes to state changes and publishes emotion outputs."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._current: EmotionOutput = _STATE_MAP[RobotState.BOOTING]
        bus.subscribe(EVT_STATE_CHANGED, self._on_state_changed)

    @property
    def current(self) -> EmotionOutput:
        return self._current

    def evaluate(self, state: RobotState) -> EmotionOutput:
        return _STATE_MAP.get(state, _STATE_MAP[RobotState.IDLE])

    async def _on_state_changed(self, event: Event) -> None:
        state = parse_robot_state(str(event.payload.get("to", "")))
        if state is None:
            return
        output = self.evaluate(state)
        self._current = output
        log.debug(
            "EmotionEngine %s → face=%s led=%s voice_speed=%.2f",
            state.value,
            output.face,
            output.led_colour,
            output.voice_speed,
        )
        await self._bus.publish(
            EVT_EMOTION_CHANGED,
            {
                "state": state.value,
                "face": output.face,
                "led_colour": output.led_colour,
                "voice_speed": output.voice_speed,
                "motor": _motor_payload(output.motor),
            },
        )


def _motor_payload(motor: Optional[MotorMotion]) -> Optional[dict[str, Any]]:
    if motor is None:
        return None
    return {
        "direction": motor.direction,
        "duration_seconds": motor.duration_seconds,
        "speed": motor.speed,
    }
