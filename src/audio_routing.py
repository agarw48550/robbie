"""Audio routing — Pi sounddevice vs gated K10 body-audio cutover.

Paths
-----
**Pi path (default, ``ROBBIE_BODY_AUDIO=0``)**
- Mic capture: ``sounddevice`` RawInputStream in ``src/live.py`` / ``src/wake.py``
- Playback: local ``sounddevice`` RawOutputStream on the Pi
- Wake word: Pi-side energy gate + Gemini flash-lite transcription
- Body still receives optional base64 WAV on HTTP POST for K10 speaker play

**K10 path (flag on, ``ROBBIE_BODY_AUDIO=1``)**
- Intended future: K10 captures mic + local wake, streams PCM to Pi over WS;
  Pi stays silent on speaker; K10 plays TTS audio from the brain
- **Today:** flag only switches logging / metadata ``source`` hints.
  Pi ``sounddevice`` remains active (gated cutover pending WS audio streaming).
  Do not remove Pi audio until parity tests pass.

Helpers below keep the decision in one place so Live/Wake can log consistently.
"""

from __future__ import annotations

from config.env import env_flag
from config.settings import log

# Feature flag default OFF — also documented in config/settings.py
BODY_AUDIO_FLAG = "ROBBIE_BODY_AUDIO"


def body_audio_enabled() -> bool:
    """True when K10 body-audio cutover is selected (still gated)."""
    return env_flag(BODY_AUDIO_FLAG, default=False)


def audio_source_label(default: str = "pi") -> str:
    """Metadata label for bridge/transcript source fields."""
    if body_audio_enabled():
        return "k10_gated"
    return default


def log_audio_routing(context: str = "audio") -> None:
    """Log which path is active. Never disables Pi sounddevice."""
    if body_audio_enabled():
        log.info(
            "%s: ROBBIE_BODY_AUDIO=1 — K10 audio path selected; "
            "gated cutover pending (Pi sounddevice still active)",
            context,
        )
    else:
        log.debug("%s: Pi sounddevice path (ROBBIE_BODY_AUDIO=0)", context)
