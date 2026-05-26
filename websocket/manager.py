"""
backend/websocket/manager.py
=============================
WebSocket connection manager.

Responsibilities:
- Track all connected frontend clients per user
- Broadcast market data updates to all subscribers
- Handle client connect / disconnect cleanly
- Support room-based broadcasting (e.g. only send option chain
  to clients that subscribed to it)

Architecture:
  Market stream (background task)
       │
       ▼ publish(data)
  WebSocketManager
       │
       ├── client_1 (browser tab 1)
       ├── client_2 (browser tab 2)
       └── client_3 (mobile)
"""

import asyncio
import json
from collections import defaultdict
from typing import Dict, List, Set

import structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)


class WebSocketManager:
    """
    Manages all active WebSocket connections.

    Clients subscribe to channels:
        - "market"        → NIFTY spot, VIX, PCR, futures
        - "option_chain"  → Full option chain data
        - "signals"       → Trade signals from strategy engine
        - "trades"        → Paper/live trade updates
        - "logs"          → System logs
    """

    def __init__(self):
        # channel → set of websockets subscribed to it
        self._channels: Dict[str, Set[WebSocket]] = defaultdict(set)
        # websocket → set of channels it's subscribed to
        self._subscriptions: Dict[WebSocket, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channels: List[str]) -> None:
        """
        Accept a new WebSocket connection and subscribe to channels.
        Called when frontend connects.
        """
        await websocket.accept()
        async with self._lock:
            for channel in channels:
                self._channels[channel].add(websocket)
                self._subscriptions[websocket].add(channel)

        log.info(
            "websocket.client_connected",
            channels=channels,
            total_clients=len(self._subscriptions),
        )

        # Send immediate confirmation
        await self._send_to(websocket, {
            "type": "connected",
            "channels": channels,
            "message": "Subscribed to live market data",
        })

    async def disconnect(self, websocket: WebSocket) -> None:
        """Clean up when a client disconnects."""
        async with self._lock:
            channels = self._subscriptions.pop(websocket, set())
            for channel in channels:
                self._channels[channel].discard(websocket)

        log.info(
            "websocket.client_disconnected",
            total_clients=len(self._subscriptions),
        )

    async def broadcast(self, channel: str, data: dict) -> None:
        """
        Send data to all clients subscribed to a channel.
        Dead connections are removed automatically.
        """
        subscribers = list(self._channels.get(channel, set()))
        if not subscribers:
            return

        message = json.dumps(data)
        dead: List[WebSocket] = []

        for ws in subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    channels = self._subscriptions.pop(ws, set())
                    for ch in channels:
                        self._channels[ch].discard(ws)
            log.warning("websocket.dead_connections_removed", count=len(dead))

    async def broadcast_all(self, data: dict) -> None:
        """Send to every connected client regardless of channel."""
        all_ws = list(self._subscriptions.keys())
        message = json.dumps(data)
        dead = []
        for ws in all_ws:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    channels = self._subscriptions.pop(ws, set())
                    for ch in channels:
                        self._channels[ch].discard(ws)

    async def _send_to(self, websocket: WebSocket, data: dict) -> None:
        """Send to a single websocket."""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception as e:
            log.warning("websocket.send_failed", error=str(e))

    @property
    def client_count(self) -> int:
        return len(self._subscriptions)

    def channel_count(self, channel: str) -> int:
        return len(self._channels.get(channel, set()))


# Global singleton — imported by routes and stream engine
ws_manager = WebSocketManager()
