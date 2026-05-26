"""
backend/websocket/market_stream.py
====================================
Background streaming engine.

Runs as a FastAPI lifespan background task.
Every N seconds it fetches all market data and broadcasts
to connected WebSocket clients.

Timing (when market is OPEN):
  - NIFTY spot + VIX     → every 1 second
  - Option chain          → every 5 seconds (heavy payload)
  - Futures               → every 2 seconds
  - Global markets        → every 30 seconds (external API, rate-limit friendly)
  - Market breadth        → every 60 seconds

When market is CLOSED:
  - Global markets only   → every 5 minutes
  - All other data paused (no point polling)
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select

from angel_one.client import AngelOneClient, AngelOneAuthError
from api.schemas.market import MarketSnapshot
from auth.encryption import decrypt
from config.settings import get_settings
from database.engine import AsyncSessionFactory
from database.models import APICredentials, MarketSnapshotRecord, OptionChainRecord
from services.candle_store import candle_store
from services.market_data import MarketDataService
from websocket.manager import ws_manager

log = structlog.get_logger(__name__)
settings = get_settings()

_system_client: Optional[AngelOneClient] = None


class MarketStreamEngine:
    """
    Manages the background market data polling and WebSocket broadcasting.

    Lifecycle:
        engine = MarketStreamEngine()
        await engine.start(angel_client)   # call in app lifespan startup
        await engine.stop()                # call in app lifespan shutdown
    """

    def __init__(self):
        self._running = False
        self._service: Optional[MarketDataService] = None
        self._tasks: list[asyncio.Task] = []

        # Cached last known values — sent even when some fetches fail
        self._last_snapshot = MarketSnapshot()

        # Counters for staggered fetching
        self._tick = 0

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, angel_client=None) -> None:
        """Start all background streaming tasks."""
        self._service = MarketDataService(angel_client)
        self._running = True

        # Main market data loop
        self._tasks.append(
            asyncio.create_task(self._stream_loop(), name="market_stream")
        )

        # Global markets loop (separate — hits external API)
        self._tasks.append(
            asyncio.create_task(self._global_loop(), name="global_stream")
        )

        log.info("market_stream.started")

    async def stop(self) -> None:
        """Cancel all background tasks gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

        if self._service:
            await self._service.close()

        log.info("market_stream.stopped")

    # ── Main stream loop ──────────────────────────────────────────────────────

    async def _stream_loop(self) -> None:
        """
        Core loop: fetches market data and broadcasts every second.
        Staggered fetching prevents hammering Angel One API.
        """
        while self._running:
            try:
                await self._tick_market()
                self._tick += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("market_stream.loop_error", error=str(e))

            await asyncio.sleep(1)  # 1-second base tick

    async def _tick_market(self) -> None:
        """
        Execute one market data tick.
        Different data is refreshed at different intervals.
        """
        if not self._service:
            return

        status = MarketDataService.get_market_status()

        if status == "CLOSED" and self._tick % 60 != 0:
            # Market closed: broadcast closed status, skip heavy fetches
            # Still update every 60 ticks in case it opens
            if ws_manager.client_count > 0:
                self._last_snapshot.market_status = "CLOSED"
                self._last_snapshot.last_updated = datetime.utcnow()
                await ws_manager.broadcast("market", {
                    "type": "market_snapshot",
                    "data": self._last_snapshot.model_dump(mode="json"),
                })
            return

        # ── Fetch data (parallel where possible) ─────────────────────────────

        fetch_tasks = [self._service.get_nifty_spot()]

        if self._tick % 3 == 0:   # VIX every 3 seconds
            fetch_tasks.append(self._service.get_india_vix())
        else:
            async def _cached_vix():
                return self._last_snapshot.vix
            fetch_tasks.append(_cached_vix())

        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        nifty = results[0] if not isinstance(results[0], Exception) else None
        vix = results[1] if not isinstance(results[1], Exception) else None

        # Update cache
        if nifty:
            self._last_snapshot.nifty = nifty
        if vix:
            self._last_snapshot.vix = vix

        # Futures every 2 seconds
        if self._tick % 2 == 0 and nifty:
            futures = await self._safe_fetch(
                self._service.get_nifty_futures(nifty.ltp)
            )
            if futures:
                self._last_snapshot.futures = futures

        # Option chain every 5 seconds (heavier call)
        if self._tick % 5 == 0 and nifty:
            option_chain = await self._safe_fetch(
                self._service.get_option_chain(spot_price=nifty.ltp)
            )
            if option_chain:
                self._last_snapshot.option_chain = option_chain
                # Broadcast option chain separately (large payload)
                await ws_manager.broadcast("option_chain", {
                    "type": "option_chain",
                    "data": option_chain.model_dump(mode="json"),
                })

        # ── Broadcast main snapshot ───────────────────────────────────────────
        self._last_snapshot.market_status = status
        self._last_snapshot.last_updated = datetime.utcnow()

        await ws_manager.broadcast("market", {
            "type": "market_snapshot",
            "data": self._last_snapshot.model_dump(mode="json"),
        })

        # Persist snapshot every 60 seconds when clients are connected
        if self._tick % 60 == 0 and ws_manager.client_count > 0:
            await _persist_snapshot(self._last_snapshot)

        # Log only occasionally to avoid noise
        if self._tick % 30 == 0 and nifty:
            log.info(
                "market_stream.tick",
                nifty_ltp=nifty.ltp,
                vix=vix.value if vix else "N/A",
                clients=ws_manager.client_count,
                tick=self._tick,
            )

    # ── Global markets loop ───────────────────────────────────────────────────

    async def _global_loop(self) -> None:
        """
        Fetches global indices every 30 seconds.
        Runs independently of the main loop to avoid blocking it.
        """
        while self._running:
            try:
                if not self._service:
                    await asyncio.sleep(30)
                    continue

                if ws_manager.client_count > 0:
                    global_data = await self._safe_fetch(
                        self._service.get_global_markets()
                    )
                    if global_data:
                        self._last_snapshot.global_markets = global_data
                        await ws_manager.broadcast("market", {
                            "type": "global_markets",
                            "data": global_data.model_dump(mode="json"),
                        })
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("market_stream.global_loop_error", error=str(e))

            await asyncio.sleep(30)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _safe_fetch(coro):
        """Wrap a coroutine so exceptions return None instead of crashing."""
        try:
            return await coro
        except Exception as e:
            log.warning("market_stream.fetch_error", error=str(e))
            return None

    def get_last_snapshot(self) -> MarketSnapshot:
        """Returns the most recent cached snapshot (for REST endpoints)."""
        return self._last_snapshot


# Global singleton
market_stream = MarketStreamEngine()


async def _resolve_system_angel_client() -> Optional[AngelOneClient]:
    """Build Angel One client from env settings or first active user credentials."""
    if (
        settings.angel_one_api_key
        and settings.angel_one_client_id
        and settings.angel_one_api_key != "your-api-key"
    ):
        client = AngelOneClient(
            api_key=settings.angel_one_api_key,
            client_id=settings.angel_one_client_id,
            password=settings.angel_one_password,
            totp_secret=settings.angel_one_totp_secret,
        )
        await client.login()
        return client

    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(APICredentials).where(APICredentials.is_active == True).limit(1)
        )
        creds = result.scalar_one_or_none()
        if not creds:
            return None

        client = AngelOneClient(
            api_key=decrypt(creds.encrypted_api_key),
            client_id=decrypt(creds.encrypted_client_id),
            password=decrypt(creds.encrypted_password),
            totp_secret=decrypt(creds.encrypted_totp_secret),
        )
        await client.login()
        log.info("market_stream.using_user_credentials", user_id=str(creds.user_id))
        return client


async def _persist_snapshot(snapshot: MarketSnapshot) -> None:
    """Save latest market snapshot and option chain to PostgreSQL."""
    try:
        payload = snapshot.model_dump(mode="json")
        async with AsyncSessionFactory() as db:
            record = MarketSnapshotRecord(
                nifty_ltp=snapshot.nifty.ltp if snapshot.nifty else None,
                vix_value=snapshot.vix.value if snapshot.vix else None,
                market_status=snapshot.market_status,
                pcr=snapshot.option_chain.pcr if snapshot.option_chain else None,
                payload_json=json.dumps(payload, default=str),
            )
            db.add(record)

            if snapshot.option_chain:
                db.add(
                    OptionChainRecord(
                        spot_price=snapshot.option_chain.spot_price,
                        expiry=snapshot.option_chain.expiry,
                        atm_strike=snapshot.option_chain.atm_strike,
                        pcr=snapshot.option_chain.pcr,
                        max_pain=snapshot.option_chain.max_pain,
                        payload_json=json.dumps(
                            snapshot.option_chain.model_dump(mode="json"),
                            default=str,
                        ),
                    )
                )
            await db.commit()
    except Exception as e:
        log.warning("market_stream.persist_failed", error=str(e))


async def start_market_stream() -> None:
    """
    Initialize Angel One and start background polling.
    Called from FastAPI lifespan via asyncio.create_task().
    """
    global _system_client
    try:
        _system_client = await _resolve_system_angel_client()
        if not _system_client:
            log.warning(
                "market_stream.no_angel_credentials",
                hint="Set ANGEL_ONE_* in .env or save credentials — global markets only",
            )
            await market_stream.start(None)
            return

        # Phase 3: preload OHLCV buffers before live stream (indicators need history)
        await candle_store.backfill_all_timeframes(_system_client, symbol="NIFTY")
        await market_stream.start(_system_client)
    except AngelOneAuthError as e:
        log.error("market_stream.auth_failed", error=str(e))
    except Exception as e:
        log.error("market_stream.start_failed", error=str(e))


async def stop_market_stream() -> None:
    """Stop stream and close system Angel One client."""
    global _system_client
    await market_stream.stop()
    if _system_client:
        try:
            await _system_client.close()
        except Exception as e:
            log.warning("market_stream.client_close_error", error=str(e))
        _system_client = None
