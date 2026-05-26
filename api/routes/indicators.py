"""
backend/api/routes/indicators.py
==================================
Technical analysis REST endpoints.

Routes:
  GET /indicators/signal/{timeframe}     — full technical signal
  GET /indicators/summary                — compact multi-timeframe summary
  GET /indicators/support-resistance     — S/R levels
  GET /indicators/breakout               — breakout detection
  GET /indicators/trend                  — trend structure
  GET /indicators/candles/{timeframe}    — raw OHLCV candles
  GET /indicators/liquidity              — liquidity zones
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.indicators import (
    BreakoutData,
    IndicatorSummaryResponse,
    LiquidityZone,
    SupportResistanceData,
    TechnicalSignalResponse,
    TrendData,
)
from auth.dependencies import get_current_user
from database.engine import get_db
from database.models import User
from indicators.calculator import TechnicalCalculator
from indicators.patterns import PatternDetector
from indicators.signals import SignalAggregator
from services.candle_store import candle_store

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/indicators", tags=["Technical Analysis"])

VALID_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h"]


def _get_signal(symbol: str, timeframe: str) -> TechnicalSignalResponse:
    """
    Core function: get candles → run indicators → generate signal.
    Raises HTTPException if not enough data.
    """
    df = candle_store.get_dataframe(symbol, timeframe)
    count = candle_store.candle_count(symbol, timeframe)

    if df is None or len(df) < 15:
        raise HTTPException(
            status_code=503,
            detail=f"Insufficient candle data for {symbol} {timeframe}. "
                   f"Have {count} candles, need at least 15. "
                   f"Market may be closed or data still loading.",
        )

    calc = TechnicalCalculator(df)
    enriched_df = calc.run_all()

    aggregator = SignalAggregator(enriched_df, symbol=symbol, timeframe=timeframe)
    sig = aggregator.generate()

    return TechnicalSignalResponse(
        **sig.__dict__,
        candle_count=count,
    )


@router.get("/signal/{timeframe}", response_model=TechnicalSignalResponse)
async def get_signal(
    timeframe: str,
    symbol: str = Query(default="NIFTY"),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a complete technical signal for the given symbol and timeframe.

    Returns all indicator values, votes, trend structure, and a final
    BUY_CE / BUY_PE / WAIT signal with confidence score.

    Example: GET /indicators/signal/5m?symbol=NIFTY
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe. Valid: {VALID_TIMEFRAMES}",
        )
    return _get_signal(symbol, timeframe)


@router.get("/summary", response_model=List[IndicatorSummaryResponse])
async def get_summary(
    symbol: str = Query(default="NIFTY"),
    current_user: User = Depends(get_current_user),
):
    """
    Returns compact signals across all available timeframes.
    Used by the dashboard header to show multi-timeframe alignment.
    """
    summaries = []
    for tf in ["5m", "15m", "1h"]:
        try:
            sig = _get_signal(symbol, tf)
            df = candle_store.get_dataframe(symbol, tf)
            enriched = TechnicalCalculator(df).run_all() if df is not None else None
            trend = (
                PatternDetector(enriched).get_trend_structure()
                if enriched is not None
                else {}
            )
            summaries.append(IndicatorSummaryResponse(
                symbol=symbol,
                timeframe=tf,
                signal=sig.signal,
                direction=sig.direction,
                confidence=sig.confidence,
                trend=sig.trend,
                rsi=sig.rsi,
                macd_hist=sig.macd_hist,
                above_vwap=trend.get("above_vwap"),
                supertrend_bull=trend.get("supertrend_bull"),
                timestamp=sig.timestamp,
            ))
        except HTTPException:
            summaries.append(IndicatorSummaryResponse(
                symbol=symbol,
                timeframe=tf,
                signal="WAIT",
                direction="NEUTRAL",
                confidence=0.0,
                trend="NEUTRAL",
                rsi=None,
                macd_hist=None,
                above_vwap=None,
                supertrend_bull=None,
                timestamp=None,
            ))
    return summaries


@router.get("/support-resistance", response_model=SupportResistanceData)
async def get_support_resistance(
    symbol: str = Query(default="NIFTY"),
    timeframe: str = Query(default="15m"),
    current_user: User = Depends(get_current_user),
):
    """Detect key support and resistance levels."""
    df = candle_store.get_dataframe(symbol, timeframe)
    if df is None:
        raise HTTPException(status_code=503, detail="No candle data available")

    calc = TechnicalCalculator(df).run_all()
    detector = PatternDetector(calc)
    sr = detector.get_support_resistance()

    return SupportResistanceData(
        resistance=[{"level": r["level"], "strength": r["strength"], "type": "resistance"}
                    for r in sr.get("resistance", [])],
        support=[{"level": s["level"], "strength": s["strength"], "type": "support"}
                 for s in sr.get("support", [])],
        nearest_resistance=sr.get("nearest_resistance"),
        nearest_support=sr.get("nearest_support"),
        current_price=sr.get("current_price"),
        distance_to_resistance=sr.get("distance_to_resistance"),
        distance_to_support=sr.get("distance_to_support"),
    )


@router.get("/breakout", response_model=BreakoutData)
async def get_breakout(
    symbol: str = Query(default="NIFTY"),
    timeframe: str = Query(default="5m"),
    current_user: User = Depends(get_current_user),
):
    """Detect active breakouts with volume confirmation."""
    df = candle_store.get_dataframe(symbol, timeframe)
    if df is None:
        raise HTTPException(status_code=503, detail="No candle data available")

    calc = TechnicalCalculator(df).run_all()
    detector = PatternDetector(calc)
    breakout = detector.detect_breakout()
    return BreakoutData(**breakout)


@router.get("/trend", response_model=TrendData)
async def get_trend(
    symbol: str = Query(default="NIFTY"),
    timeframe: str = Query(default="15m"),
    current_user: User = Depends(get_current_user),
):
    """Get overall trend structure and direction."""
    df = candle_store.get_dataframe(symbol, timeframe)
    if df is None:
        raise HTTPException(status_code=503, detail="No candle data available")

    calc = TechnicalCalculator(df).run_all()
    detector = PatternDetector(calc)
    trend = detector.get_trend_structure()
    return TrendData(**trend)


@router.get("/candles/{timeframe}")
async def get_candles(
    timeframe: str,
    symbol: str = Query(default="NIFTY"),
    limit: int = Query(default=100, ge=10, le=500),
    current_user: User = Depends(get_current_user),
):
    """
    Returns raw OHLCV candles — used by the frontend charting library.
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}")

    df = candle_store.get_dataframe(symbol, timeframe)
    if df is None:
        raise HTTPException(status_code=503, detail="No candle data available")

    df_limited = df.tail(limit)
    records = []
    for ts, row in df_limited.iterrows():
        records.append({
            "t": int(ts.timestamp() * 1000),  # milliseconds for TradingView
            "o": round(float(row["open"]),  2),
            "h": round(float(row["high"]),  2),
            "l": round(float(row["low"]),   2),
            "c": round(float(row["close"]), 2),
            "v": int(row["volume"]),
        })

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(records),
        "candles": records,
    }


@router.get("/liquidity", response_model=List[LiquidityZone])
async def get_liquidity_zones(
    symbol: str = Query(default="NIFTY"),
    timeframe: str = Query(default="15m"),
    current_user: User = Depends(get_current_user),
):
    """Get high-volume price zones (institutional interest areas)."""
    df = candle_store.get_dataframe(symbol, timeframe)
    if df is None:
        raise HTTPException(status_code=503, detail="No candle data available")

    calc = TechnicalCalculator(df).run_all()
    detector = PatternDetector(calc)
    zones = detector.get_liquidity_zones()
    return [LiquidityZone(**z) for z in zones]
