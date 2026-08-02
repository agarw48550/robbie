#!/usr/bin/env python3
"""tools/audio_echo_test.py"""

import socket
import base64
import urllib.request
import json
import time
import sys

UDP_IP = "0.0.0.0"
UDP_PORT = 5005
K10_HTTP_URL = "http://192.168.1.25:8080/robot"  # <--- Verify your K10 IP address

def send_to_k10(audio_bytes):
    b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
    payload = json.dumps({
        "expression": "happy",
        "audio": b64_audio
    }).encode('utf-8')

    req = urllib.request.Request(
        K10_HTTP_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f" -> Echoed {len(audio_bytes)} bytes back to K10 speaker successfully!")
    except Exception as e:
        print(f" -> Failed to send HTTP back to K10: {e}")

def main():
    print("--- K10 Audio Echo Test ---")
    print(f"Targeting K10 HTTP at: {K10_HTTP_URL}")
    print(f"Attempting to listen on UDP port {UDP_PORT}...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind((UDP_IP, UDP_PORT))
        print(f"SUCCESS: Listening on UDP port {UDP_PORT}!")
        print("Waiting for audio packets from K10 mic...\n")
    except Exception as e:
        print(f"ERROR: Could not bind to port {UDP_PORT}: {e}")
        print("Run 'killall python3' to free the port.")
        sys.exit(1)

    chunk_count = 0
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            if data:
                chunk_count += 1
                print(f"[Chunk #{chunk_count}] Received {len(data)} bytes from K10 ({addr[0]})")
                send_to_k10(data)
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping Echo Test...")

if __name__ == "__main__":
    main()
