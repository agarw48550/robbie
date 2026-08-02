"""WebSocket transport — Pi hosts; K10 connects. Opt-in via bridge_transport=websocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from urllib.parse import urlparse

from config.settings import log
from src.persistence import load_bridge_config

DEFAULT_WS_URL = "ws://0.0.0.0:8765"
HEARTBEAT_INTERVAL_S = 20.0
OUTBOUND_MAX = 64


def _parse_ws_bind(url: str) -> tuple[str, int]:
    raw = (url or DEFAULT_WS_URL).strip()
    if "://" not in raw:
        raw = "ws://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or "0.0.0.0"
    port = parsed.port or 8765
    return host, int(port)


class WebSocketTransport:
    """Transport implementation: Pi WebSocket server + outbound queue.

    If the ``websockets`` package is missing, ``connect()`` logs a warning and
    ``send()`` queues messages then returns False (stub mode).
    """

    def __init__(
        self,
        *,
        ws_url: Optional[str] = None,
        heartbeat_s: float = HEARTBEAT_INTERVAL_S,
    ) -> None:
        bridge = load_bridge_config()
        self._ws_url = (ws_url or bridge.get("bridge_ws_url") or DEFAULT_WS_URL).strip()
        self._host, self._port = _parse_ws_bind(self._ws_url)
        self._heartbeat_s = float(heartbeat_s)
        self._connected = False
        self._stub = False
        self._server: Any = None
        self._clients: set[Any] = set()
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=OUTBOUND_MAX)
        self._flush_task: Optional[asyncio.Task] = None
        self._websockets: Any = None

    @property
    def url(self) -> str:
        return self._ws_url

    @property
    def stub_mode(self) -> bool:
        return self._stub

    async def connect(self) -> None:
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            log.warning(
                "WebSocketTransport: 'websockets' not installed — stub mode "
                "(send queues messages and returns False). pip install websockets"
            )
            self._stub = True
            self._connected = True
            return

        self._websockets = websockets
        self._stub = False

        async def _handler(websocket: Any) -> None:
            self._clients.add(websocket)
            log.info("WebSocketTransport client connected (%d total)", len(self._clients))
            try:
                async for raw in websocket:
                    # Optional inbound (ACK / sensor); ignore for now.
                    log.debug("WebSocketTransport inbound: %s", str(raw)[:120])
            except Exception as exc:
                log.debug("WebSocketTransport client closed: %s", exc)
            finally:
                self._clients.discard(websocket)
                log.info("WebSocketTransport client disconnected (%d left)", len(self._clients))

        try:
            self._server = await websockets.serve(
                _handler,
                self._host,
                self._port,
                ping_interval=self._heartbeat_s,
                ping_timeout=self._heartbeat_s * 2,
            )
            self._connected = True
            self._flush_task = asyncio.create_task(self._flush_loop(), name="ws_flush")
            log.info("WebSocketTransport listening on ws://%s:%d", self._host, self._port)
        except Exception as exc:
            log.error("WebSocketTransport failed to bind %s:%d: %s", self._host, self._port, exc)
            self._stub = True
            self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        for client in list(self._clients):
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        log.info("WebSocketTransport disconnected")

    def _enqueue(self, message: dict[str, Any]) -> None:
        try:
            self._outbound.put_nowait(message)
        except asyncio.QueueFull:
            try:
                _ = self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._outbound.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("WebSocketTransport outbound queue full — dropped oldest")

    async def _send_to_clients(self, message: dict[str, Any]) -> bool:
        if not self._clients:
            return False
        raw = json.dumps(message)
        dead: list[Any] = []
        ok_any = False
        for client in list(self._clients):
            try:
                await client.send(raw)
                ok_any = True
            except Exception as exc:
                log.warning("WebSocketTransport send failed: %s", exc)
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
        return ok_any

    async def _flush_loop(self) -> None:
        while self._connected:
            try:
                message = await asyncio.wait_for(self._outbound.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            if not await self._send_to_clients(message):
                # Re-queue so commands aren't lost while disconnected.
                self._enqueue(message)
                await asyncio.sleep(0.5)

    async def send(self, message: dict[str, Any]) -> bool:
        if not self._connected:
            await self.connect()
        if self._stub:
            self._enqueue(message)
            log.warning("WebSocketTransport stub send — queued, returning False")
            return False
        if self._clients:
            return await self._send_to_clients(message)
        # No client yet — queue for flush loop / later reconnect.
        self._enqueue(message)
        log.debug("WebSocketTransport queued (%d waiting for client)", self._outbound.qsize())
        return False
