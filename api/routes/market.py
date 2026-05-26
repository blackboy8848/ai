"""
backend/api/routes/market.py
==============================
Market data endpoints.

REST endpoints (for initial page load / polling fallback):
  GET  /market/status          — current market status (OPEN/CLOSED)
  GET  /market/snapshot        — latest full market snapshot
  GET  /market/nifty           — NIFTY spot data
  GET  /market/vix             — India VIX
  GET  /market/option-chain    — current option chain
  GET  /market/global          — global indices

WebSocket endpoint:
  WS   /market/ws              — subscribe to live market stream

WebSocket message format (client → server):
  {"action": "subscribe", "channels": ["market", "option_chain"]}
  {"action": "unsubscribe", "channels": ["option_chain"]}

WebSocket message format (server → client):
  {"type": "market_snapshot", "data": {...}}
  {"type": "option_chain",    "data": {...}}
  {"type": "global_markets",  "data": {...}}
  {"type": "connected",       "channels": [...]}
  {"type": "error",           "message": "..."}
"""

import json
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from angel_one.registry import angel_registry
from api.schemas.market import (
    MarketSnapshot,
    MarketStatusResponse,
    OptionChainData,
    OptionChainRequest,
)
from auth.dependencies import get_current_user
from database.engine import get_db
from database.models import User
from services.market_data import MarketDataService
from websocket.manager import ws_manager
from websocket.market_stream import market_stream

import pytz
from datetime import datetime

log = structlog.get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

router = APIRouter(prefix="/market", tags=["Market Data"])

# Default channels a client subscribes to when connecting
DEFAULT_CHANNELS = ["market", "option_chain", "signals"]


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def market_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token passed as query param"),
):
    """
    Live market data WebSocket.

    Connect with:
        ws://localhost:8000/api/v1/market/ws?token=<access_token>

    After connecting, the server streams:
        - market_snapshot  (every 1 second when market is open)
        - option_chain     (every 5 seconds)
        - global_markets   (every 30 seconds)
        - signals          (when strategy engine generates a signal)

    Client can send:
        {"action": "ping"}   → server replies {"type": "pong"}
        {"action": "subscribe", "channels": ["option_chain"]}
    """
    # Validate JWT before accepting WebSocket
    from auth.jwt import decode_access_token
    from jose import JWTError

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Connect client to default channels
    await ws_manager.connect(websocket, DEFAULT_CHANNELS)

    # Send current snapshot immediately so client doesn't wait 1s
    snapshot = market_stream.get_last_snapshot()
    try:
        await websocket.send_json({
            "type": "market_snapshot",
            "data": snapshot.model_dump(mode="json"),
        })
    except Exception:
        pass

    try:
        while True:
            # Listen for client messages (ping, channel changes, etc.)
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "ping":
                    await websocket.send_json({"type": "pong"})

                elif action == "subscribe":
                    channels = msg.get("channels", [])
                    for ch in channels:
                        if ch not in ws_manager._subscriptions[websocket]:
                            ws_manager._channels[ch].add(websocket)
                            ws_manager._subscriptions[websocket].add(ch)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channels": channels,
                    })

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
        log.info("market.ws.disconnected", user_id=user_id)


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/status", response_model=MarketStatusResponse)
async def get_market_status():
    """Current NSE market status — no auth required."""
    status_str = MarketDataService.get_market_status()
    now_ist = datetime.now(IST)

    return MarketStatusResponse(
        status=status_str,
        is_open=(status_str == "OPEN"),
        next_open="09:15 IST" if status_str == "CLOSED" else None,
        next_close="15:30 IST" if status_str == "OPEN" else None,
        current_time_ist=now_ist.strftime("%H:%M:%S IST"),
    )


@router.get("/snapshot", response_model=MarketSnapshot)
@router.get("/overview", response_model=MarketSnapshot, include_in_schema=True)
async def get_snapshot(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the latest cached market snapshot.
    Use this for initial page load — then switch to WebSocket for live updates.
    """
    return market_stream.get_last_snapshot()


@router.get("/nifty")
async def get_nifty(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch fresh NIFTY spot data on demand."""
    try:
        client = await angel_registry.get_client(current_user.id, db)
        service = MarketDataService(client)
        data = await service.get_nifty_spot()
        if not data:
            raise HTTPException(status_code=503, detail="Could not fetch NIFTY data")
        return data
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/vix")
async def get_vix(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch fresh India VIX on demand."""
    try:
        client = await angel_registry.get_client(current_user.id, db)
        service = MarketDataService(client)
        data = await service.get_india_vix()
        if not data:
            raise HTTPException(status_code=503, detail="Could not fetch VIX data")
        return data
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/option-chain", response_model=Optional[OptionChainData])
async def get_option_chain(
    expiry: Optional[str] = Query(default=None, description="DD-MON-YYYY e.g. 28-NOV-2024"),
    strikes_range: int = Query(default=10, ge=5, le=30),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch NIFTY option chain.
    Returns ATM ± strikes_range strikes for the given (or nearest) expiry.
    """
    try:
        client = await angel_registry.get_client(current_user.id, db)
        service = MarketDataService(client)
        data = await service.get_option_chain(
            expiry=expiry,
            strikes_range=strikes_range,
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/global")
@router.get("/globals", include_in_schema=True)
async def get_global_markets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch global indices (Dow, Nasdaq, S&P 500, Crude, Gold)."""
    try:
        client = await angel_registry.get_client(current_user.id, db)
        service = MarketDataService(client)
        data = await service.get_global_markets()
        return data
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
