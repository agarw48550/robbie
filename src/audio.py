"""WAV / PCM audio helpers."""

from __future__ import annotations

import base64
import io
import struct
import wave
from typing import Optional

from config.settings import OUTPUT_SAMPLE_RATE, TURN_AUDIO_MAX_BYTES
from src.state import SharedState


def pcm16_to_wav_bytes(pcm: bytes, rate: int = OUTPUT_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def encode_audio_wav_b64(pcm: bytes, rate: int = OUTPUT_SAMPLE_RATE) -> Optional[str]:
    if not pcm:
        return None
    wav = pcm16_to_wav_bytes(pcm, rate=rate)
    return base64.b64encode(wav).decode("ascii")


def append_turn_audio(shared: SharedState, pcm: bytes) -> None:
    if not pcm:
        return
    shared.turn_audio_pcm.extend(pcm)
    if len(shared.turn_audio_pcm) > TURN_AUDIO_MAX_BYTES:
        del shared.turn_audio_pcm[: len(shared.turn_audio_pcm) - TURN_AUDIO_MAX_BYTES]


def chunk_rms(pcm: bytes) -> float:
    if not pcm or len(pcm) < 2:
        return 0.0
    try:
        import audioop

        return float(audioop.rms(pcm, 2))
    except ImportError:
        count = len(pcm) // 2
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        if not samples:
            return 0.0
        ss = sum(s * s for s in samples)
        return (ss / len(samples)) ** 0.5
