"""Gemini Live audio I/O and conversation session."""

from __future__ import annotations

import asyncio
import base64
import queue as std_queue
import time
from typing import Any, Optional

import sounddevice as sd
from google.genai import types

from config.settings import (
    CHANNELS,
    CHUNK_FRAMES,
    INPUT_SAMPLE_RATE,
    LIVE_MODEL,
    MIC_QUEUE_SIZE,
    OUTPUT_SAMPLE_RATE,
    PLAY_QUEUE_SIZE,
    VOICE_POLL_S,
    log,
)
from src.audio import append_turn_audio
from src.audio_routing import log_audio_routing
from src.brain import merge_transcript, schedule_reactive_brain
from src.live_tools import handle_live_tool, live_tool_declarations
from src.persistence import build_live_system_instruction, get_voice_name, remember_fact
from src.robot_state import RobotState
from src.state import SharedState


# --- Speech / mic capture (Pi sounddevice; K10 path gated via ROBBIE_BODY_AUDIO) ---
async def _mic_send_loop(session: Any, shared: SharedState) -> None:
    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MIC_QUEUE_SIZE)

    def _callback(indata: Any, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        if status:
            log.debug("Mic status: %s", status)
        pcm = bytes(indata)
        try:
            loop.call_soon_threadsafe(audio_queue.put_nowait, pcm)
        except asyncio.QueueFull:
            pass

    stream = sd.RawInputStream(
        samplerate=INPUT_SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_FRAMES,
        callback=_callback,
    )
    stream.start()
    log.info("Microphone streaming started (%d Hz)", INPUT_SAMPLE_RATE)
    try:
        while (
            not shared.shutdown.is_set()
            and shared.voice_enabled.is_set()
            and not shared.force_live_reconnect
        ):
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            # Half-duplex: silence only while Robbie is speaking (prevents echo barge-in).
            # Do NOT zero quiet listening audio — that made soft speech get ignored.
            if shared.is_playing:
                chunk = b"\x00" * len(chunk)

            try:
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                )
            except Exception as exc:
                if shared.shutdown.is_set() or not shared.voice_enabled.is_set():
                    break
                log.error("Mic send failed: %s", exc)
                raise
    finally:
        stream.stop()
        stream.close()
        log.info("Microphone streaming stopped")


# --- Conversation receive + Speech playback + Tool calling ---
async def _receive_loop(session: Any, shared: SharedState) -> None:
    play_q: std_queue.Queue[Optional[bytes]] = std_queue.Queue(maxsize=PLAY_QUEUE_SIZE)

    def _play_worker() -> None:
        with sd.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_FRAMES,
        ) as out:
            while True:
                item = play_q.get()
                if item is None:
                    break
                try:
                    out.write(item)
                except Exception as exc:
                    log.debug("Playback write error: %s", exc)

    player_task = asyncio.create_task(asyncio.to_thread(_play_worker))

    try:
        while (
            not shared.shutdown.is_set()
            and shared.voice_enabled.is_set()
            and not shared.force_live_reconnect
        ):
            turn_model_audio_seen = False
            turn_had_user = False
            shared.tool_moved_this_turn = False
            shared.brain_scheduled_this_turn = False
            shared.turn_audio_pcm.clear()

            async for response in session.receive():
                if (
                    shared.shutdown.is_set()
                    or not shared.voice_enabled.is_set()
                    or shared.force_live_reconnect
                ):
                    return

                # --- Tool calling (move / voice-off / remember / set_voice) ---
                tool_call = getattr(response, "tool_call", None)
                if tool_call and getattr(tool_call, "function_calls", None):
                    function_responses = []
                    for fc in tool_call.function_calls:
                        args = dict(fc.args or {})
                        log.info("Live tool: %s(%s)", fc.name, args)
                        result = await handle_live_tool(shared, fc.name, args)
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response=result,
                            )
                        )
                    await session.send_tool_response(function_responses=function_responses)
                    continue

                # --- Conversation transcripts ---
                content = getattr(response, "server_content", None)
                if content is None:
                    continue

                if getattr(content, "input_transcription", None):
                    transcript = content.input_transcription.text or ""
                    if transcript.strip():
                        if shared.is_playing:
                            log.debug("Ignoring echo transcript: %r", transcript[:60])
                        else:
                            shared.last_interaction_time = time.monotonic()
                            shared.last_user_transcript = merge_transcript(
                                shared.last_user_transcript, transcript
                            )
                            turn_had_user = True
                            log.info("User speech: %r", transcript.strip()[:120])

                if getattr(content, "output_transcription", None):
                    out_t = content.output_transcription.text or ""
                    if out_t.strip():
                        shared.last_model_transcript = merge_transcript(
                            shared.last_model_transcript, out_t
                        )
                        log.info("Robbie said: %r", out_t.strip()[:120])

                # --- Speech: model audio → local playback + turn buffer ---
                model_turn = getattr(content, "model_turn", None)
                if model_turn and getattr(model_turn, "parts", None):
                    for part in model_turn.parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            if not shared.is_playing:
                                shared.is_playing = True
                                log.info("Robbie speaking — half-duplex silence")
                                if shared.state_machine is not None:
                                    shared.state_machine.set_state_nowait(
                                        RobotState.SPEAKING, reason="live_audio"
                                    )
                                # Fire motion ASAP so the body moves with the voice
                                schedule_reactive_brain(
                                    shared,
                                    shared.last_user_transcript,
                                    shared.last_model_transcript,
                                )
                            turn_model_audio_seen = True
                            audio_bytes = inline.data
                            if isinstance(audio_bytes, str):
                                audio_bytes = base64.b64decode(audio_bytes)
                            append_turn_audio(shared, audio_bytes)
                            try:
                                play_q.put_nowait(audio_bytes)
                            except std_queue.Full:
                                pass

                if getattr(content, "interrupted", False):
                    log.info("Model interrupted — clearing playback")
                    shared.is_playing = False
                    shared.turn_audio_pcm.clear()
                    while not play_q.empty():
                        try:
                            play_q.get_nowait()
                        except std_queue.Empty:
                            break

                if getattr(content, "turn_complete", False):
                    log.info("Live turn complete")
                    shared.is_playing = False
                    if shared.state_machine is not None and shared.voice_enabled.is_set():
                        shared.state_machine.set_state_nowait(
                            RobotState.LISTENING, reason="turn_complete"
                        )
                    user_t = shared.last_user_transcript
                    model_t = shared.last_model_transcript
                    shared.last_user_transcript = ""
                    shared.last_model_transcript = ""

                    if user_t or model_t:
                        snippet = f"User said {user_t[:80]!r}; Robbie replied {model_t[:80]!r}."
                        remember_fact(snippet, source="turn")

                    # Only schedule here if we somehow never started speaking audio
                    if not shared.brain_scheduled_this_turn and (
                        turn_model_audio_seen or (turn_had_user and model_t)
                    ):
                        schedule_reactive_brain(shared, user_t, model_t)

                    shared.tool_moved_this_turn = False
                    shared.brain_scheduled_this_turn = False
                    shared.turn_audio_pcm.clear()
    finally:
        shared.is_playing = False
        play_q.put(None)
        await player_task
        log.info("Live receive loop ended")


async def live_conversation_task(shared: SharedState) -> None:
    """Gemini Live session supervisor (conversation + tools + speech I/O)."""
    client = shared.client
    backoff = 1.0
    log_audio_routing("live")

    while not shared.shutdown.is_set():
        if not shared.voice_enabled.is_set():
            shared.live_session = None
            shared.is_playing = False
            log.info("Voice off — Live idle (proactivity still running)")
            await shared.voice_enabled.wait()
            if shared.shutdown.is_set():
                break
            backoff = 1.0

        try:
            voice = shared.voice_name or get_voice_name()
            log.info("Connecting Live %s voice=%s …", LIVE_MODEL, voice)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                system_instruction=build_live_system_instruction(),
                tools=live_tool_declarations(),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
                realtime_input_config=types.RealtimeInputConfig(
                    # Allow natural barge-in after Robbie finishes; hear soft speech better
                    activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                        prefix_padding_ms=40,
                        silence_duration_ms=800,
                    ),
                ),
            )
            shared.force_live_reconnect = False
            async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                shared.live_session = session
                shared.is_playing = False
                backoff = 1.0
                log.info("Live session connected")

                mic_task = asyncio.create_task(_mic_send_loop(session, shared))
                recv_task = asyncio.create_task(_receive_loop(session, shared))

                async def _wait_stop() -> None:
                    while (
                        shared.voice_enabled.is_set()
                        and not shared.shutdown.is_set()
                        and not shared.force_live_reconnect
                    ):
                        await asyncio.sleep(VOICE_POLL_S)

                stop_task = asyncio.create_task(_wait_stop())
                shutdown_waiter = asyncio.create_task(shared.shutdown.wait())

                done, pending = await asyncio.wait(
                    {mic_task, recv_task, stop_task, shutdown_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                if shared.shutdown.is_set():
                    break
                if shared.force_live_reconnect:
                    log.info("Reconnecting Live (voice/config change)")
                    continue
                if not shared.voice_enabled.is_set():
                    log.info("Voice turned off — disconnecting Live")
                    continue

                for task in done:
                    if task in (stop_task, shutdown_waiter):
                        continue
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    if exc:
                        raise exc

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            shared.live_session = None
            if shared.shutdown.is_set():
                break
            if not shared.voice_enabled.is_set():
                continue
            log.error("Live session error: %s — reconnecting in %.1fs", exc, backoff)
            try:
                await asyncio.wait_for(shared.shutdown.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)
        finally:
            shared.live_session = None
            shared.is_playing = False

    log.info("Live conversation task stopped")
