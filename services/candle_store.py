"""
backend/services/candle_store.py
==================================
In-memory candle buffer for the technical analysis engine.

Responsibilities:
  - Store the last N candles per symbol per timeframe
  - Build candles from tick data (1m, 3m, 5m, 15m, 1h)
  - Provide DataFrames ready for TechnicalCalculator
  - Backfill historical candles from Angel One on startup

Why in-memory?
  - Technical indicators only need the last 100–200 candles
  - Database writes for every tick would be too slow
  - Redis could replace this for multi-worker setups (future)

Supported timeframes: 1m, 3m, 5m, 15m, 30m, 1h
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
import pytz
import structlog

from angel_one.client import AngelOneClient

log = structlog.get_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# How many candles to keep in memory per timeframe
BUFFER_SIZES = {
    "1m":  200,
    "3m":  200,
    "5m":  200,
    "15m": 150,
    "30m": 100,
    "1h":  100,
}

# Angel One interval strings
ANGEL_INTERVALS = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h":  "ONE_HOUR",
}

# NIFTY symbol token on NSE
NIFTY_TOKEN   = "99926000"
NIFTY_EXCHANGE = "NSE"


class CandleStore:
    """
    In-memory OHLCV candle buffer.

    Usage:
        store = CandleStore()
        await store.backfill("NIFTY", "5m", angel_client)
        df = store.get_dataframe("NIFTY", "5m")
    """

    def __init__(self):
        # {symbol: {timeframe: deque([{open,high,low,close,volume,timestamp}])}}
        self._candles: Dict[str, Dict[str, deque]] = {}
        self._lock = asyncio.Lock()

    def _init_symbol(self, symbol: str, timeframe: str) -> None:
        if symbol not in self._candles:
            self._candles[symbol] = {}
        if timeframe not in self._candles[symbol]:
            max_size = BUFFER_SIZES.get(timeframe, 200)
            self._candles[symbol][timeframe] = deque(maxlen=max_size)

    async def add_candle(
        self,
        symbol: str,
        timeframe: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        timestamp: datetime,
    ) -> None:
        """Add or update the latest candle."""
        async with self._lock:
            self._init_symbol(symbol, timeframe)
            candle = {
                "open":      open_,
                "high":      high,
                "low":       low,
                "close":     close,
                "volume":    volume,
                "timestamp": timestamp,
            }
            buf = self._candles[symbol][timeframe]

            # Update last candle if same timestamp, else append
            if buf and buf[-1]["timestamp"] == timestamp:
                buf[-1] = candle
            else:
                buf.append(candle)

    def get_dataframe(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Returns a pandas DataFrame of OHLCV candles.
        Returns None if no data available.
        """
        if symbol not in self._candles:
            return None
        if timeframe not in self._candles[symbol]:
            return None

        buf = list(self._candles[symbol][timeframe])
        if len(buf) < 2:
            return None

        df = pd.DataFrame(buf)
        df = df.set_index("timestamp")
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(IST)
        df = df.sort_index()

        # Ensure correct dtypes
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

        return df

    def candle_count(self, symbol: str, timeframe: str) -> int:
        """Returns number of candles currently buffered."""
        try:
            return len(self._candles[symbol][timeframe])
        except KeyError:
            return 0

    # ── Backfill from Angel One ───────────────────────────────────────────────

    async def backfill(
        self,
        symbol: str,
        timeframe: str,
        client: AngelOneClient,
        bars: int = 150,
    ) -> int:
        """
        Fetches historical candles from Angel One to pre-populate the buffer.
        Called at startup so indicators have enough data from the start.

        Returns number of candles loaded.
        """
        angel_interval = ANGEL_INTERVALS.get(timeframe)
        if not angel_interval:
            log.warning("candle_store.backfill.unknown_timeframe", timeframe=timeframe)
            return 0

        # Determine token for symbol
        token_map = {"NIFTY": NIFTY_TOKEN}
        token = token_map.get(symbol, NIFTY_TOKEN)

        # Calculate from/to dates
        now = datetime.now(IST)
        # Add buffer for weekends and holidays
        lookback_days = max(5, bars // 75 + 3)
        from_dt = now - timedelta(days=lookback_days)

        from_str = from_dt.strftime("%Y-%m-%d %H:%M")
        to_str   = now.strftime("%Y-%m-%d %H:%M")

        try:
            raw_candles = await client.get_candle_data(
                exchange=NIFTY_EXCHANGE,
                symbol_token=token,
                interval=angel_interval,
                from_date=from_str,
                to_date=to_str,
            )
        except Exception as e:
            log.error("candle_store.backfill.error", symbol=symbol, tf=timeframe, error=str(e))
            return 0

        if not raw_candles:
            log.warning("candle_store.backfill.no_data", symbol=symbol, tf=timeframe)
            return 0

        loaded = 0
        for candle in raw_candles[-bars:]:
            # Angel One returns: [timestamp, open, high, low, close, volume]
            try:
                ts_raw = candle[0]
                ts = pd.to_datetime(ts_raw).tz_localize(IST) if not hasattr(pd.to_datetime(ts_raw), 'tzinfo') or pd.to_datetime(ts_raw).tzinfo is None else pd.to_datetime(ts_raw).tz_convert(IST)

                await self.add_candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_=float(candle[1]),
                    high=float(candle[2]),
                    low=float(candle[3]),
                    close=float(candle[4]),
                    volume=int(candle[5]) if len(candle) > 5 else 0,
                    timestamp=ts,
                )
                loaded += 1
            except Exception as e:
                log.warning("candle_store.backfill.parse_error", error=str(e))
                continue

        log.info(
            "candle_store.backfill.complete",
            symbol=symbol,
            timeframe=timeframe,
            candles_loaded=loaded,
        )
        return loaded

    async def backfill_all_timeframes(
        self,
        client: AngelOneClient,
        symbol: str = "NIFTY",
    ) -> None:
        """Backfills 5m and 15m timeframes in parallel at startup."""
        tasks = [
            self.backfill(symbol, "5m",  client, bars=150),
            self.backfill(symbol, "15m", client, bars=100),
            self.backfill(symbol, "1h",  client, bars=100),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for tf, result in zip(["5m", "15m", "1h"], results):
            if isinstance(result, Exception):
                log.error("candle_store.backfill_all.error", tf=tf, error=str(result))
            else:
                log.info("candle_store.backfill_all.done", tf=tf, loaded=result)


# Global singleton shared across the app
candle_store = CandleStore()
