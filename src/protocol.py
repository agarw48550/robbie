"""Protocol v2 envelope — dual-decode with bare v1 ESP32 JSON."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

PROTOCOL_VERSION = 2

# Canonical v1 body fields (unchanged ESP32 contract).
V1_ACTION_KEYS = (
    "direction",
    "duration_seconds",
    "speed",
    "expression",
    "audio",
    "audio_format",
    "sample_rate",
    "transcript",
    "source",
    "ts",
)

ENVELOPE_REQUIRED = (
    "protocol_version",
    "message_id",
    "timestamp",
    "type",
    "priority",
    "payload",
)


def wrap_v1_action(
    v1_dict: dict[str, Any],
    *,
    msg_type: str = "robot.action",
    priority: int = 0,
    message_id: Optional[str] = None,
) -> dict[str, Any]:
    """Wrap a bare v1 action dict into a protocol v2 envelope."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": message_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": msg_type,
        "priority": int(priority),
        "payload": dict(v1_dict),
    }


def _looks_like_v1(message: dict[str, Any]) -> bool:
    """True when direction/expression sit at the top level (bare v1 or dual path)."""
    return "direction" in message or "expression" in message


def unwrap_to_v1(message: dict[str, Any]) -> dict[str, Any]:
    """Extract a v1 action dict.

    Dual-decode:
    - If ``direction`` / ``expression`` are already at the top level and there is
      no ``protocol_version``, treat the whole message as v1.
    - Otherwise read ``payload`` from a v2 envelope (falling back to top-level
      v1 fields when present inside a mixed message).
    """
    if not isinstance(message, dict):
        return {}

    has_version = "protocol_version" in message
    if _looks_like_v1(message) and not has_version:
        return dict(message)

    payload = message.get("payload")
    if isinstance(payload, dict):
        if _looks_like_v1(payload) or payload:
            return dict(payload)

    if _looks_like_v1(message):
        return {k: message[k] for k in V1_ACTION_KEYS if k in message}

    return {}


def validate_envelope(message: Any) -> bool:
    """Return True if ``message`` is a well-formed protocol v2 envelope."""
    if not isinstance(message, dict):
        return False
    for key in ENVELOPE_REQUIRED:
        if key not in message:
            return False
    try:
        version = int(message["protocol_version"])
    except (TypeError, ValueError):
        return False
    if version != PROTOCOL_VERSION:
        return False
    if not isinstance(message["message_id"], str) or not message["message_id"]:
        return False
    if not isinstance(message["timestamp"], str) or not message["timestamp"]:
        return False
    if not isinstance(message["type"], str) or not message["type"]:
        return False
    try:
        int(message["priority"])
    except (TypeError, ValueError):
        return False
    if not isinstance(message["payload"], dict):
        return False
    return True
