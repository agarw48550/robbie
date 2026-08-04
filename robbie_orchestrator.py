#!/usr/bin/env python3
"""live_orchestrator.py — Gemini Live Audio-to-Audio Orchestrator"""

import os
import sys
import asyncio
import socket
import json
import urllib.request
import pyaudio
from google import genai
from google.genai import types

# --- CONFIGURATION ---
K10_HTTP_URL = "http://192.168.1.25:8080/robot"  # <--- Verify your K10 IP address
UDP_PORT = 5005
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY environment variable not set!")
    sys.exit(1)

# PyAudio setup for local playback on Pi (or USB speaker connected to Pi)
p = pyaudio.PyAudio()
audio_stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=24000,  # Gemini Live returns 24kHz audio
    output=True
)

def send_k10_action(expression="happy", direction="stop", duration=0, speed=5):
    """Sends lightweight action JSON payload to K10."""
    payload = json.dumps({
        "expression": expression,
        "direction": direction,
        "duration": duration,
        "speed": speed
    }).encode('utf-8')

    req = urllib.request.Request(
        K10_HTTP_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            print(f"[Action Executed] {expression} | {direction} for {duration}s")
    except Exception as e:
        print(f"[Action Failed]: {e}")

# Tool definition so Gemini can trigger physical movements
robot_tools = [{
    "function_declarations": [
        {
            "name": "control_robot",
            "description": "Control the physical movement and screen expression of Robbie the robot.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "expression": {
                        "type": "STRING",
                        "description": "Screen expression: happy, sad, curious, angry, calm, surprised"
                    },
                    "direction": {
                        "type": "STRING",
                        "description": "Motor direction: forward, backward, spin_left, spin_right, stop"
                    },
                    "duration": {
                        "type": "NUMBER",
                        "description": "Duration in seconds (e.g. 1.5)"
                    }
                },
                "required": ["expression"]
            }
        }
    ]
}]

async def udp_audio_receiver(session, loop):
    """Receives UDP chunks from UNIHIKER K10 and forwards them to Gemini Live."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)
    print(f"UDP Audio Receiver listening on port {UDP_PORT}...")

    while True:
        try:
            data, _ = await loop.sock_recvfrom(sock, 65535)
            if data:
                # Send raw audio directly into Gemini Live WebSocket
                await session.send(input={"data": data, "mime_type": "audio/pcm;rate=16000"})
        except Exception:
            await asyncio.sleep(0.01)

async def gemini_response_listener(session):
    """Listens for returning audio stream and tool calls from Gemini Live."""
    async for response in session.receive():
        server_content = response.server_content
        if server_content and server_content.model_turn:
            for part in server_content.model_turn.parts:
                # Real-time returning PCM audio from Gemini
                if part.inline_data:
                    audio_stream.write(part.inline_data.data)

        # Handle Gemini Live tool calls for motion/expression
        if response.tool_call:
            for call in response.tool_call.function_calls:
                if call.name == "control_robot":
                    args = call.args
                    send_k10_action(
                        expression=args.get("expression", "happy"),
                        direction=args.get("direction", "stop"),
                        duration=args.get("duration", 0)
                    )

async def main():
    client = genai.Client(api_key=GEMINI_API_KEY)
    loop = asyncio.get_running_loop()

    config = types.LiveConnectConfig(
        response_modalities=[types.LiveModality.AUDIO],  # Audio-to-audio mode!
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(name="Puck")
            )
        ),
        tools=robot_tools,
        system_instruction=types.Content(
            parts=[types.Part.from_text(
                "You are Robbie, an expressive desktop pet robot. Respond with short, friendly speech. "
                "Use the control_robot function tool frequently during conversation to trigger expressions and movements."
            )]
        )
    )

    print("Connecting to Gemini Live (Audio-to-Audio)...")
    async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
        print("Connected to Gemini Live!")
        await asyncio.gather(
            udp_audio_receiver(session, loop),
            gemini_response_listener(session)
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down Robbie Live Orchestrator.")
        audio_stream.stop_stream()
        audio_stream.close()
        p.terminate()
