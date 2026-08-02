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
    voice_style: str = "neutral"
    eye_animation: str = "idle"
    blink_frequency_hz: float = 0.3
    idle_behaviour: str = "calm"


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
        voice_style="neutral",
        eye_animation="boot",
        blink_frequency_hz=0.4,
        idle_behaviour="boot",
    ),
    RobotState.IDLE: EmotionOutput(
        face="calm",
        motor=None,
        led_colour="#4488FF",
        voice_speed=1.0,
        voice_style="neutral",
        eye_animation="idle",
        blink_frequency_hz=0.25,
        idle_behaviour="calm",
    ),
    RobotState.LISTENING: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#00CCFF",
        voice_speed=1.0,
        voice_style="attentive",
        eye_animation="focus",
        blink_frequency_hz=0.2,
        idle_behaviour="listen",
    ),
    RobotState.THINKING: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#AA66FF",
        voice_speed=1.0,
        voice_style="thoughtful",
        eye_animation="think",
        blink_frequency_hz=0.35,
        idle_behaviour="think",
    ),
    RobotState.SPEAKING: EmotionOutput(
        face="happy",
        motor=None,
        led_colour="#FFAA00",
        voice_speed=1.0,
        voice_style="expressive",
        eye_animation="talk",
        blink_frequency_hz=0.45,
        idle_behaviour="talk",
    ),
    RobotState.MOVING: EmotionOutput(
        face="surprised",
        motor=None,
        led_colour="#FF6600",
        voice_speed=1.0,
        voice_style="energetic",
        eye_animation="motion",
        blink_frequency_hz=0.5,
        idle_behaviour="move",
    ),
    RobotState.SLEEPING: EmotionOutput(
        face="calm",
        motor=None,
        led_colour="#223355",
        voice_speed=0.9,
        voice_style="soft",
        eye_animation="sleep",
        blink_frequency_hz=0.05,
        idle_behaviour="sleep",
    ),
    RobotState.ERROR: EmotionOutput(
        face="worried",
        motor=None,
        led_colour="#FF0000",
        voice_speed=1.0,
        voice_style="concerned",
        eye_animation="alert",
        blink_frequency_hz=0.6,
        idle_behaviour="error",
    ),
    RobotState.HAPPY: EmotionOutput(
        face="happy",
        motor=None,
        led_colour="#FFD700",
        voice_speed=1.05,
        voice_style="cheerful",
        eye_animation="sparkle",
        blink_frequency_hz=0.4,
        idle_behaviour="happy",
    ),
    RobotState.CONFUSED: EmotionOutput(
        face="curious",
        motor=None,
        led_colour="#CC88FF",
        voice_speed=0.95,
        voice_style="uncertain",
        eye_animation="tilt",
        blink_frequency_hz=0.55,
        idle_behaviour="confused",
    ),
    RobotState.CELEBRATING: EmotionOutput(
        face="silly",
        motor=None,
        led_colour="#FF44AA",
        voice_speed=1.1,
        voice_style="excited",
        eye_animation="celebrate",
        blink_frequency_hz=0.7,
        idle_behaviour="celebrate",
    ),
    RobotState.UPDATING: EmotionOutput(
        face="calm",
        motor=None,
        led_colour="#888888",
        voice_speed=1.0,
        voice_style="neutral",
        eye_animation="progress",
        blink_frequency_hz=0.3,
        idle_behaviour="updating",
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
            "EmotionEngine %s → face=%s led=%s voice_speed=%.2f style=%s",
            state.value,
            output.face,
            output.led_colour,
            output.voice_speed,
            output.voice_style,
        )
        await self._bus.publish(
            EVT_EMOTION_CHANGED,
            {
                "state": state.value,
                "face": output.face,
                "led_colour": output.led_colour,
                "voice_speed": output.voice_speed,
                "voice_style": output.voice_style,
                "eye_animation": output.eye_animation,
                "blink_frequency_hz": output.blink_frequency_hz,
                "idle_behaviour": output.idle_behaviour,
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
