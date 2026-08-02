"""Robot operating-state model."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

from config.settings import log
from src.events import EVT_STATE_CHANGED, EventBus

if TYPE_CHECKING:
    from src.state import SharedState


class RobotState(str, Enum):
    BOOTING = "BOOTING"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    MOVING = "MOVING"
    SLEEPING = "SLEEPING"
    ERROR = "ERROR"
    HAPPY = "HAPPY"
    CONFUSED = "CONFUSED"
    CELEBRATING = "CELEBRATING"
    UPDATING = "UPDATING"


class RobotStateMachine:
    """Tracks ``RobotState`` and publishes changes on the EventBus."""

    def __init__(self, bus: EventBus, initial: RobotState = RobotState.BOOTING) -> None:
        self._bus = bus
        self._state = initial

    @property
    def state(self) -> RobotState:
        return self._state

    async def set_state(self, new_state: RobotState, *, reason: str = "") -> None:
        if new_state is self._state:
            return
        old = self._state
        self._state = new_state
        log.info("RobotState %s → %s%s", old.value, new_state.value, f" ({reason})" if reason else "")
        await self._bus.publish(
            EVT_STATE_CHANGED,
            {
                "from": old.value,
                "to": new_state.value,
                "reason": reason,
            },
        )

    def set_state_nowait(self, new_state: RobotState, *, reason: str = "") -> None:
        if new_state is self._state:
            return
        old = self._state
        self._state = new_state
        log.info("RobotState %s → %s%s", old.value, new_state.value, f" ({reason})" if reason else "")
        self._bus.publish_nowait(
            EVT_STATE_CHANGED,
            {
                "from": old.value,
                "to": new_state.value,
                "reason": reason,
            },
        )


def parse_robot_state(value: Optional[str]) -> Optional[RobotState]:
    if not value:
        return None
    try:
        return RobotState(value)
    except ValueError:
        return None


async def apply_runtime_state(
    shared: "SharedState",
    state: RobotState,
    reason: str = "",
) -> None:
    """Set robot state via SharedState's state machine when attached."""
    sm = getattr(shared, "state_machine", None)
    if sm is None:
        return
    await sm.set_state(state, reason=reason)
