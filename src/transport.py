"""Body transport abstraction — HTTP first; WebSocket is a later implementation."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Optional, Protocol, runtime_checkable

from config.settings import DEFAULT_BRIDGE_TIMEOUT_S, DEFAULT_BRIDGE_URL, log
from src.persistence import load_bridge_config


@runtime_checkable
class Transport(Protocol):
    """Transport-only interface for body communication."""

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def send(self, message: dict[str, Any]) -> bool:
        ...


def _post_json_sync(url: str, body: bytes, timeout_s: float, token: str) -> bool:
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        log.error("Bridge POST HTTP %s: %s", exc.code, exc.reason)
        return False
    except urllib.error.URLError as exc:
        log.error("Bridge POST failed: %s", exc.reason)
        return False
    except Exception as exc:
        log.error("Bridge POST failed: %s", exc)
        return False


class HttpTransport:
    """Current production transport: one HTTP POST per message."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        timeout_s: Optional[float] = None,
        token: Optional[str] = None,
    ) -> None:
        bridge = load_bridge_config()
        self._url = (url or bridge.get("bridge_url") or DEFAULT_BRIDGE_URL).strip()
        self._timeout_s = float(
            timeout_s if timeout_s is not None else bridge.get("bridge_timeout_s", DEFAULT_BRIDGE_TIMEOUT_S)
        )
        self._token = (token if token is not None else bridge.get("bridge_token") or "").strip()
        self._connected = False
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    @property
    def url(self) -> str:
        return self._url

    async def connect(self) -> None:
        self._connected = True
        log.info("HttpTransport ready → %s", self._url)

    async def disconnect(self) -> None:
        self._connected = False
        log.info("HttpTransport disconnected")

    async def send(self, message: dict[str, Any]) -> bool:
        if not self._connected:
            await self.connect()
        if not self._url:
            log.warning("HttpTransport send skipped — no bridge URL")
            return False
        body = json.dumps(message).encode("utf-8")
        return await asyncio.to_thread(
            _post_json_sync,
            self._url,
            body,
            self._timeout_s,
            self._token,
        )


def create_transport(kind: Optional[str] = None) -> Transport:
    """Factory — ``http`` default; ``websocket`` added in a later phase."""
    bridge = load_bridge_config()
    name = (kind or bridge.get("bridge_transport") or "http").strip().lower()
    if name in {"http", "https", ""}:
        return HttpTransport()
    if name in {"websocket", "ws", "wss"}:
        # Lazy import so HTTP-only installs never need websockets package
        from src.ws_transport import WebSocketTransport

        return WebSocketTransport()
    log.warning("Unknown bridge_transport %r — falling back to HTTP", name)
    return HttpTransport()
