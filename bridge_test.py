#!/usr/bin/env python3
"""Smoke test for the ESP32-S3 HTTP bridge.

Posts a sample motion + short WAV clip to the configured bridge URL.
Usage:
  python bridge_test.py
  python bridge_test.py http://192.168.4.1/robot
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import struct
import sys
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "robbie" / "config.json"
DEFAULT_URL = "http://192.168.4.1/robot"


def load_bridge_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url.strip()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            url = data.get("bridge_url")
            if isinstance(url, str) and url.strip():
                return url.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_URL


def make_test_wav(duration_s: float = 0.25, rate: int = 24000) -> bytes:
    """Generate a quiet 440 Hz tone as mono 16-bit PCM WAV."""
    frames = int(duration_s * rate)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        samples = []
        for i in range(frames):
            sample = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
            samples.append(struct.pack("<h", sample))
        wf.writeframes(b"".join(samples))
    return buf.getvalue()


def post_payload(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    print(f"POST {url} ({len(body)} bytes)")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            print(f"HTTP {resp.status}: {text[:200]}")
    except urllib.error.HTTPError as exc:
        print(f"HTTP error {exc.code}: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Robbie HTTP bridge")
    parser.add_argument("url", nargs="?", help="Bridge URL (default from config)")
    args = parser.parse_args()

    url = load_bridge_url(args.url)
    wav = make_test_wav()
    payload = {
        "direction": "forward",
        "duration_seconds": 1,
        "speed": 5,
        "expression": "curious",
        "audio": base64.b64encode(wav).decode("ascii"),
        "audio_format": "wav",
        "sample_rate": 24000,
        "transcript": "Bridge test ping",
        "source": "bridge_test",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    post_payload(url, payload)
    print("Bridge test OK")


if __name__ == "__main__":
    main()
