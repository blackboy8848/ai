"""
backend/main.py
===============
FastAPI application factory and startup/shutdown lifecycle.

Run with:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload   (dev)
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 (prod — 1 worker for WebSocket state)
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from config.logging import configure_logging
from config.settings import get_settings
from database.engine import close_db, init_db
from angel_one.registry import angel_registry
from api.routes import auth as auth_router
from api.routes import indicators as indicators_router
from api.routes import market as market_router
from services.candle_store import candle_store
from websocket.market_stream import market_stream, start_market_stream, stop_market_stream

# Configure structured logging first — before any log calls
configure_logging()
log = structlog.get_logger(__name__)
settings = get_settings()


# ── Lifespan (startup + shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs startup logic before yield, shutdown logic after.
    FastAPI calls this automatically.
    """
    # ── STARTUP ──
    log.info(
        "app.starting",
        env=settings.app_env,
        trading_mode=settings.trading_mode_label,
        debug=settings.debug,
    )

    await init_db()
    log.info("app.db.ready")

    # Phase 2: Angel One + background market stream (must start after DB)
    stream_task = asyncio.create_task(start_market_stream())
    app.state.market_stream_task = stream_task
    log.info("app.market_stream.scheduled")

    yield  # ← app runs here

    # ── SHUTDOWN ──
    log.info("app.shutting_down")
    await stop_market_stream()
    if hasattr(app.state, "market_stream_task"):
        app.state.market_stream_task.cancel()
        try:
            await app.state.market_stream_task
        except asyncio.CancelledError:
            pass
    await angel_registry.shutdown()
    await close_db()
    log.info("app.stopped")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Trading System",
        description="NIFTY 50 Options Trading Platform",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,  # hide docs in prod
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"]
        if not settings.is_production
        else ["https://yourdomain.com"],  # lock down in production
        allow_origin_regex=r"http://localhost(:[0-9]+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(market_router.router, prefix="/api/v1")
    app.include_router(indicators_router.router, prefix="/api/v1")

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health():
        return {
            "status": "ok",
            "env": settings.app_env,
            "trading_mode": settings.trading_mode_label,
            "candles_5m": candle_store.candle_count("NIFTY", "5m"),
            "candles_15m": candle_store.candle_count("NIFTY", "15m"),
            "candles_1h": candle_store.candle_count("NIFTY", "1h"),
            "stream_running": market_stream.is_running,
        }

    return app


app = create_app()
