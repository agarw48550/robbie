"""Wake word ("robbie") listener while proactive-only."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Optional

import sounddevice as sd
from google import genai
from google.genai import types

from config.settings import (
    CHANNELS,
    CHUNK_FRAMES,
    INPUT_SAMPLE_RATE,
    WAKE_CLIP_S,
    WAKE_COOLDOWN_S,
    WAKE_RMS_THRESHOLD,
    log,
)
from src.audio import chunk_rms, pcm16_to_wav_bytes
from src.audio_routing import log_audio_routing
from src.bridge import pick_fallback_serial, send_robot_action, serial_command_to_action
from src.persistence import write_voice_mode_file
from src.state import SharedState

WAKE_PATTERNS = re.compile(
    r"\b(hey\s+)?robbie\b|\bरॉबी\b|\bरोबी\b|罗比|羅比",
    re.IGNORECASE,
)


async def _clip_contains_wake_word(client: genai.Client, wav_bytes: bytes) -> bool:
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                        types.Part(
                            text=(
                                "Transcribe briefly. Then answer YES or NO on its own line: "
                                "did the speaker clearly say the wake word Robbie "
                                "(or Hey Robbie / रॉबी / 罗比)?"
                            )
                        ),
                    ],
                )
            ],
        )
        text = (getattr(response, "text", None) or "").strip()
        log.info("Wake check: %r", text[:120])
        if WAKE_PATTERNS.search(text):
            return True
        last = text.splitlines()[-1].strip().upper() if text else ""
        return last.startswith("YES")
    except Exception as exc:
        log.warning("Wake-word check failed: %s", exc)
        return False


async def wake_word_task(shared: SharedState) -> None:
    """When voice is OFF, listen for 'Robbie' and flip voice mode on."""
    log.info("Wake-word listener ready (say 'Robbie' in proactive mode)")
    log_audio_routing("wake")
    loop = asyncio.get_running_loop()
    audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
    last_wake = 0.0

    def _callback(indata: Any, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        if status:
            log.debug("Wake mic status: %s", status)
        pcm = bytes(indata)
        try:
            loop.call_soon_threadsafe(audio_q.put_nowait, pcm)
        except asyncio.QueueFull:
            pass

    stream: Optional[sd.RawInputStream] = None

    try:
        while not shared.shutdown.is_set():
            # Only listen while proactive-only
            if shared.voice_enabled.is_set():
                if stream is not None:
                    stream.stop()
                    stream.close()
                    stream = None
                    log.info("Wake mic paused (voice ON)")
                await asyncio.sleep(0.4)
                continue

            if stream is None:
                stream = sd.RawInputStream(
                    samplerate=INPUT_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_FRAMES,
                    callback=_callback,
                )
                stream.start()
                log.info("Wake mic listening for 'Robbie'…")

            # Collect an energy-gated clip
            clip = bytearray()
            speech_started = False
            silence_chunks = 0
            need_chunks = int(WAKE_CLIP_S * INPUT_SAMPLE_RATE / CHUNK_FRAMES)
            max_chunks = need_chunks + 8
            chunks = 0

            while chunks < max_chunks and not shared.shutdown.is_set() and not shared.voice_enabled.is_set():
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if speech_started:
                        break
                    continue
                rms = chunk_rms(chunk)
                if rms >= WAKE_RMS_THRESHOLD:
                    speech_started = True
                    silence_chunks = 0
                    clip.extend(chunk)
                elif speech_started:
                    silence_chunks += 1
                    clip.extend(chunk)
                    if silence_chunks >= 6:  # ~0.4s quiet after speech
                        break
                chunks += 1

            if shared.voice_enabled.is_set() or shared.shutdown.is_set():
                continue
            if len(clip) < INPUT_SAMPLE_RATE:  # < ~0.5s of audio
                continue
            if time.monotonic() - last_wake < WAKE_COOLDOWN_S:
                continue

            wav = pcm16_to_wav_bytes(bytes(clip), rate=INPUT_SAMPLE_RATE)
            hit = await _clip_contains_wake_word(shared.client, wav)
            if hit:
                last_wake = time.monotonic()
                log.info("Wake word detected — enabling voice mode")
                write_voice_mode_file(True)
                shared.voice_enabled.set()
                # Tiny acknowledgment motion
                fallback = serial_command_to_action(pick_fallback_serial(shared))
                if fallback:
                    await send_robot_action(
                        shared,
                        direction=fallback["direction"],
                        duration_seconds=fallback["duration_seconds"],
                        speed=fallback["speed"],
                        expression=fallback["expression"],
                        source="wake",
                        include_audio=False,
                    )

    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        log.info("Wake-word listener stopped")
