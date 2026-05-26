"""
backend/indicators/calculator.py
==================================
Pure technical analysis engine — no side effects, fully testable.

Every function takes a pandas DataFrame with OHLCV columns and returns
the same DataFrame with new indicator columns appended.

Required DataFrame columns:
    open, high, low, close, volume
    index: DatetimeIndex (IST)

All calculations use pandas-ta for accuracy, with manual fallbacks
where pandas-ta behaviour differs from tradingview conventions.

Usage:
    from indicators.calculator import TechnicalCalculator

    df = await candle_store.get_dataframe("NIFTY", "5m")
    calc = TechnicalCalculator(df)
    result = calc.run_all()
    # result has columns: ema_9, ema_21, ema_50, rsi, macd, vwap, ...
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
import structlog
from typing import Optional

log = structlog.get_logger(__name__)


class TechnicalCalculator:
    """
    Calculates all technical indicators on a price DataFrame.

    Immutable — each method returns a new copy so you can chain calls
    or run individual indicators independently.
    """

    def __init__(self, df: pd.DataFrame):
        """
        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                Must have at least 50 rows for reliable indicator values.
        """
        if df is None or len(df) < 2:
            raise ValueError("DataFrame must have at least 2 rows")

        # Normalize column names to lowercase
        self.df = df.copy()
        self.df.columns = [c.lower() for c in self.df.columns]

        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")

        # Ensure numeric types
        for col in required:
            self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    # ── EMA ───────────────────────────────────────────────────────────────────

    def add_ema(self, period: int) -> "TechnicalCalculator":
        """
        Exponential Moving Average.

        EMA gives more weight to recent prices than SMA.
        Key levels: 9 (scalping), 21 (short-term), 50 (medium-term).

        Column added: ema_{period}
        """
        col = f"ema_{period}"
        self.df[col] = ta.ema(self.df["close"], length=period)
        return self

    def add_all_emas(self) -> "TechnicalCalculator":
        """Add EMA 9, 21, and 50 in one call."""
        return self.add_ema(9).add_ema(21).add_ema(50)

    # ── RSI ───────────────────────────────────────────────────────────────────

    def add_rsi(self, period: int = 14) -> "TechnicalCalculator":
        """
        Relative Strength Index (0–100).

        Interpretation:
          > 70 = Overbought (potential reversal down)
          < 30 = Oversold  (potential reversal up)
          50–70 = Bullish momentum zone
          30–50 = Bearish momentum zone

        Column added: rsi
        """
        self.df["rsi"] = ta.rsi(self.df["close"], length=period)
        return self

    # ── MACD ──────────────────────────────────────────────────────────────────

    def add_macd(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> "TechnicalCalculator":
        """
        Moving Average Convergence Divergence.

        Components:
          macd_line    = EMA(12) - EMA(26)
          signal_line  = EMA(9) of MACD line
          histogram    = MACD line - Signal line

        Bullish signals:
          - MACD line crosses above signal line
          - Histogram turning positive after negative
          - MACD above zero line

        Columns added: macd, macd_signal, macd_hist, macd_cross
        """
        macd_df = ta.macd(
            self.df["close"],
            fast=fast,
            slow=slow,
            signal=signal,
        )
        if macd_df is not None and not macd_df.empty:
            self.df["macd"] = macd_df.iloc[:, 0]        # MACD line
            self.df["macd_hist"] = macd_df.iloc[:, 1]   # Histogram
            self.df["macd_signal"] = macd_df.iloc[:, 2] # Signal line

            # Crossover detection: 1=bullish cross, -1=bearish cross, 0=none
            self.df["macd_cross"] = 0
            prev_above = self.df["macd"].shift(1) > self.df["macd_signal"].shift(1)
            curr_above = self.df["macd"] > self.df["macd_signal"]
            self.df.loc[~prev_above & curr_above, "macd_cross"] = 1   # bullish
            self.df.loc[prev_above & ~curr_above, "macd_cross"] = -1  # bearish
        return self

    # ── VWAP ──────────────────────────────────────────────────────────────────

    def add_vwap(self) -> "TechnicalCalculator":
        """
        Volume Weighted Average Price.

        VWAP = Cumulative(Price × Volume) / Cumulative(Volume)
        Resets at the start of each trading day.

        Used by institutions to benchmark execution quality.
        Price above VWAP = bullish institutional bias.
        Price below VWAP = bearish institutional bias.

        Columns added: vwap, vwap_upper1, vwap_lower1 (±1 std dev bands)
        """
        # Calculate typical price
        typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3

        # Group by date for daily reset
        if isinstance(self.df.index, pd.DatetimeIndex):
            dates = self.df.index.date
        else:
            dates = pd.Series([0] * len(self.df))

        vwap_values = []
        upper_values = []
        lower_values = []

        for date in pd.unique(dates):
            if isinstance(dates, np.ndarray):
                mask = dates == date
            else:
                mask = dates.values == date

            day_tp = typical_price[mask]
            day_vol = self.df["volume"][mask]

            cum_tpv = (day_tp * day_vol).cumsum()
            cum_vol = day_vol.cumsum()
            day_vwap = cum_tpv / cum_vol

            # VWAP standard deviation bands
            variance = ((day_tp - day_vwap) ** 2 * day_vol).cumsum() / cum_vol
            std_dev = np.sqrt(variance)

            vwap_values.extend(day_vwap.tolist())
            upper_values.extend((day_vwap + std_dev).tolist())
            lower_values.extend((day_vwap - std_dev).tolist())

        self.df["vwap"] = vwap_values
        self.df["vwap_upper"] = upper_values
        self.df["vwap_lower"] = lower_values
        return self

    # ── ATR ───────────────────────────────────────────────────────────────────

    def add_atr(self, period: int = 14) -> "TechnicalCalculator":
        """
        Average True Range — measures volatility.

        True Range = max of:
          - High - Low
          - |High - Previous Close|
          - |Low  - Previous Close|

        ATR = Average of True Range over N periods.

        Used for:
          - Dynamic stop loss calculation (SL = entry - 1.5×ATR)
          - Position sizing (wider ATR = smaller position)
          - Detecting volatility expansion/contraction

        Columns added: atr, atr_pct (ATR as % of close)
        """
        self.df["atr"] = ta.atr(
            self.df["high"],
            self.df["low"],
            self.df["close"],
            length=period,
        )
        # ATR as percentage of close price (normalised for comparison)
        self.df["atr_pct"] = (self.df["atr"] / self.df["close"] * 100).round(3)
        return self

    # ── Supertrend ────────────────────────────────────────────────────────────

    def add_supertrend(
        self,
        period: int = 10,
        multiplier: float = 3.0,
    ) -> "TechnicalCalculator":
        """
        Supertrend Indicator.

        Based on ATR. Flips between bullish and bearish based on price
        crossing the upper/lower bands.

        Parameters:
          period:     ATR period (default 10)
          multiplier: Band width = multiplier × ATR (default 3.0)

        Columns added:
          supertrend        — the supertrend line value
          supertrend_dir    — 1 = bullish, -1 = bearish
          supertrend_signal — "BUY" | "SELL" | "HOLD"
        """
        st_df = ta.supertrend(
            self.df["high"],
            self.df["low"],
            self.df["close"],
            length=period,
            multiplier=multiplier,
        )
        if st_df is not None and not st_df.empty:
            # pandas-ta supertrend column names vary by version
            st_cols = st_df.columns.tolist()
            trend_col = [c for c in st_cols if "SUPERT_" in c and "d" not in c.lower()]
            dir_col   = [c for c in st_cols if "SUPERTd" in c]

            if trend_col:
                self.df["supertrend"] = st_df[trend_col[0]]
            if dir_col:
                direction = st_df[dir_col[0]]
                self.df["supertrend_dir"] = direction
                self.df["supertrend_signal"] = direction.map(
                    {1: "BUY", -1: "SELL"}
                ).fillna("HOLD")
        return self

    # ── Bollinger Bands ───────────────────────────────────────────────────────

    def add_bollinger_bands(
        self,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> "TechnicalCalculator":
        """
        Bollinger Bands.

        Upper Band  = SMA(20) + 2×StdDev
        Middle Band = SMA(20)
        Lower Band  = SMA(20) - 2×StdDev

        Key signals:
          - Price touching upper band = overbought
          - Price touching lower band = oversold
          - Band squeeze (low width) = low volatility, breakout likely soon
          - %B > 1 = above upper band
          - %B < 0 = below lower band

        Columns added:
          bb_upper, bb_mid, bb_lower, bb_width, bb_pct_b, bb_squeeze
        """
        bb_df = ta.bbands(self.df["close"], length=period, std=std_dev)
        if bb_df is not None and not bb_df.empty:
            cols = bb_df.columns.tolist()
            lower_col  = [c for c in cols if "BBL" in c]
            mid_col    = [c for c in cols if "BBM" in c]
            upper_col  = [c for c in cols if "BBU" in c]
            width_col  = [c for c in cols if "BBB" in c]
            pctb_col   = [c for c in cols if "BBP" in c]

            if lower_col:  self.df["bb_lower"] = bb_df[lower_col[0]]
            if mid_col:    self.df["bb_mid"]   = bb_df[mid_col[0]]
            if upper_col:  self.df["bb_upper"] = bb_df[upper_col[0]]
            if width_col:  self.df["bb_width"] = bb_df[width_col[0]]
            if pctb_col:   self.df["bb_pct_b"] = bb_df[pctb_col[0]]

            # Squeeze: band width below 20-period average = compression
            if "bb_width" in self.df.columns:
                avg_width = self.df["bb_width"].rolling(20).mean()
                self.df["bb_squeeze"] = self.df["bb_width"] < avg_width * 0.75
        return self

    # ── Volume Analysis ───────────────────────────────────────────────────────

    def add_volume_analysis(self, period: int = 20) -> "TechnicalCalculator":
        """
        Volume indicators.

        Columns added:
          vol_sma       — 20-period volume SMA
          vol_ratio     — current volume / vol_sma (>2 = spike)
          vol_spike     — True when volume > 2× average
          obv           — On Balance Volume (trend confirmation)
          vol_trend     — "RISING" | "FALLING" | "NEUTRAL"
        """
        # Volume SMA and ratio
        self.df["vol_sma"] = self.df["volume"].rolling(period).mean()
        self.df["vol_ratio"] = (self.df["volume"] / self.df["vol_sma"]).round(2)
        self.df["vol_spike"] = self.df["vol_ratio"] > 2.0

        # On Balance Volume
        self.df["obv"] = ta.obv(self.df["close"], self.df["volume"])

        # Volume trend (rising/falling over last 5 bars)
        vol_change = self.df["volume"].pct_change(5)
        self.df["vol_trend"] = "NEUTRAL"
        self.df.loc[vol_change > 0.2, "vol_trend"] = "RISING"
        self.df.loc[vol_change < -0.2, "vol_trend"] = "FALLING"

        return self

    # ── Run all indicators ────────────────────────────────────────────────────

    def run_all(self) -> pd.DataFrame:
        """
        Calculate every indicator and return the enriched DataFrame.
        Use this when you want the full picture for the strategy engine.
        """
        try:
            (
                self
                .add_all_emas()
                .add_rsi()
                .add_macd()
                .add_vwap()
                .add_atr()
                .add_supertrend()
                .add_bollinger_bands()
                .add_volume_analysis()
            )
        except Exception as e:
            log.error("indicators.run_all.error", error=str(e))

        return self.df

    def get_latest(self) -> dict:
        """
        Returns the most recent row as a clean dict.
        Used by the strategy engine and WebSocket broadcaster.
        """
        if self.df.empty:
            return {}

        row = self.df.iloc[-1]
        result = {}
        for col in self.df.columns:
            val = row[col]
            if pd.isna(val):
                result[col] = None
            elif isinstance(val, (np.integer,)):
                result[col] = int(val)
            elif isinstance(val, (np.floating,)):
                result[col] = round(float(val), 4)
            elif isinstance(val, (bool, np.bool_)):
                result[col] = bool(val)
            else:
                result[col] = val
        return result
