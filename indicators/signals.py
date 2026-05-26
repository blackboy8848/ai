"""
backend/indicators/signals.py
================================
Unified signal aggregator.

Takes all indicator values + pattern detection results and produces
a single, weighted trade signal with confidence score.

Signal logic:
  - Each indicator votes: +1 (bullish), -1 (bearish), 0 (neutral)
  - Votes are weighted by reliability
  - Final score → BUY_CE / BUY_PE / WAIT
  - Confidence = |score| / max_possible_score × 100

This module is consumed by:
  - Strategy engine (Phase 6) — adds news + OI votes
  - AI engine (Phase 7) — uses signal as one feature
  - WebSocket stream — broadcasts to dashboard
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

# ── Vote weights ──────────────────────────────────────────────────────────────
# Higher weight = more reliable indicator
WEIGHTS = {
    "ema_trend":       2.0,   # EMA alignment is most reliable
    "supertrend":      2.0,   # Supertrend is highly reliable
    "vwap_position":   1.5,   # VWAP position matters a lot intraday
    "rsi":             1.0,
    "macd":            1.0,
    "macd_cross":      1.5,   # MACD crossover > simple position
    "volume":          1.0,   # Volume confirmation
    "bb_position":     0.5,   # BB position is supplementary
    "reversal":        1.5,   # Reversal pattern against trend = warning
    "breakout":        1.5,
}

MAX_SCORE = sum(WEIGHTS.values())


@dataclass
class TechnicalSignal:
    """
    Complete technical analysis signal output.
    Passed to strategy engine and frontend dashboard.
    """
    # Direction
    signal: str = "WAIT"             # "BUY_CE" | "BUY_PE" | "WAIT"
    direction: str = "NEUTRAL"       # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: float = 0.0          # 0–100%

    # Individual votes (for debugging / dashboard display)
    ema_vote: int = 0
    rsi_vote: int = 0
    macd_vote: int = 0
    vwap_vote: int = 0
    supertrend_vote: int = 0
    volume_vote: int = 0
    bb_vote: int = 0
    breakout_vote: int = 0
    reversal_vote: int = 0

    # Raw values for display
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    vwap: Optional[float] = None
    atr: Optional[float] = None
    supertrend_dir: Optional[int] = None
    bb_pct_b: Optional[float] = None

    # Structure
    trend: str = "NEUTRAL"
    trend_score: int = 0
    pattern: str = "NONE"
    breakout_type: str = "NONE"
    breakout_confirmed: bool = False

    # Risk parameters (calculated from ATR)
    suggested_sl_points: Optional[float] = None
    suggested_target_points: Optional[float] = None
    risk_reward: Optional[float] = None

    # Metadata
    symbol: str = "NIFTY"
    timeframe: str = "5m"
    timestamp: Optional[str] = None


class SignalAggregator:
    """
    Aggregates all technical indicator votes into a final signal.

    Usage:
        from indicators.calculator import TechnicalCalculator
        from indicators.patterns import PatternDetector
        from indicators.signals import SignalAggregator

        calc = TechnicalCalculator(df).run_all()
        detector = PatternDetector(calc)
        aggregator = SignalAggregator(calc)
        signal = aggregator.generate()
    """

    def __init__(self, df: pd.DataFrame, symbol: str = "NIFTY", timeframe: str = "5m"):
        self.df = df
        self.symbol = symbol
        self.timeframe = timeframe

    def generate(self) -> TechnicalSignal:
        """
        Generate a complete technical signal from the indicator DataFrame.
        """
        if self.df.empty or len(self.df) < 2:
            return TechnicalSignal(symbol=self.symbol, timeframe=self.timeframe)

        latest = self.df.iloc[-1]
        signal = TechnicalSignal(symbol=self.symbol, timeframe=self.timeframe)

        # Extract raw values for display
        signal.rsi         = self._safe_float(latest.get("rsi"))
        signal.macd        = self._safe_float(latest.get("macd"))
        signal.macd_signal = self._safe_float(latest.get("macd_signal"))
        signal.macd_hist   = self._safe_float(latest.get("macd_hist"))
        signal.ema_9       = self._safe_float(latest.get("ema_9"))
        signal.ema_21      = self._safe_float(latest.get("ema_21"))
        signal.ema_50      = self._safe_float(latest.get("ema_50"))
        signal.vwap        = self._safe_float(latest.get("vwap"))
        signal.atr         = self._safe_float(latest.get("atr"))
        signal.bb_pct_b    = self._safe_float(latest.get("bb_pct_b"))

        st_dir = latest.get("supertrend_dir")
        signal.supertrend_dir = int(st_dir) if st_dir and not pd.isna(st_dir) else None

        weighted_score = 0.0

        # ── EMA trend vote ────────────────────────────────────────────────
        ema9  = signal.ema_9
        ema21 = signal.ema_21
        ema50 = signal.ema_50
        price = float(latest["close"])

        if ema9 and ema21 and ema50:
            if ema9 > ema21 > ema50 and price > ema9:
                signal.ema_vote = 1
                weighted_score += WEIGHTS["ema_trend"]
            elif ema9 < ema21 < ema50 and price < ema9:
                signal.ema_vote = -1
                weighted_score -= WEIGHTS["ema_trend"]
            elif ema9 > ema21:
                signal.ema_vote = 1
                weighted_score += WEIGHTS["ema_trend"] * 0.5
            elif ema9 < ema21:
                signal.ema_vote = -1
                weighted_score -= WEIGHTS["ema_trend"] * 0.5

        # ── RSI vote ──────────────────────────────────────────────────────
        if signal.rsi:
            if signal.rsi > 60:
                signal.rsi_vote = 1
                weighted_score += WEIGHTS["rsi"]
            elif signal.rsi < 40:
                signal.rsi_vote = -1
                weighted_score -= WEIGHTS["rsi"]
            elif signal.rsi > 50:
                signal.rsi_vote = 1
                weighted_score += WEIGHTS["rsi"] * 0.5
            elif signal.rsi < 50:
                signal.rsi_vote = -1
                weighted_score -= WEIGHTS["rsi"] * 0.5

        # ── MACD vote ─────────────────────────────────────────────────────
        macd_cross = latest.get("macd_cross")
        if macd_cross and not pd.isna(macd_cross):
            cross_val = int(macd_cross)
            if cross_val == 1:
                signal.macd_vote = 1
                weighted_score += WEIGHTS["macd_cross"]
            elif cross_val == -1:
                signal.macd_vote = -1
                weighted_score -= WEIGHTS["macd_cross"]
        elif signal.macd and signal.macd_signal:
            if signal.macd > signal.macd_signal and signal.macd_hist and signal.macd_hist > 0:
                signal.macd_vote = 1
                weighted_score += WEIGHTS["macd"]
            elif signal.macd < signal.macd_signal and signal.macd_hist and signal.macd_hist < 0:
                signal.macd_vote = -1
                weighted_score -= WEIGHTS["macd"]

        # ── VWAP vote ─────────────────────────────────────────────────────
        if signal.vwap:
            if price > signal.vwap:
                signal.vwap_vote = 1
                weighted_score += WEIGHTS["vwap_position"]
            else:
                signal.vwap_vote = -1
                weighted_score -= WEIGHTS["vwap_position"]

        # ── Supertrend vote ───────────────────────────────────────────────
        if signal.supertrend_dir is not None:
            signal.supertrend_vote = signal.supertrend_dir
            weighted_score += WEIGHTS["supertrend"] * signal.supertrend_dir

        # ── Volume vote ───────────────────────────────────────────────────
        vol_ratio = latest.get("vol_ratio")
        if vol_ratio and not pd.isna(vol_ratio):
            if float(vol_ratio) > 1.5:
                # High volume — amplifies direction
                direction_vote = 1 if price > float(self.df["close"].iloc[-2]) else -1
                signal.volume_vote = direction_vote
                weighted_score += WEIGHTS["volume"] * direction_vote

        # ── Bollinger Band vote ───────────────────────────────────────────
        if signal.bb_pct_b is not None:
            if signal.bb_pct_b > 0.8:    # near upper band
                signal.bb_vote = -1       # overbought warning
                weighted_score -= WEIGHTS["bb_position"]
            elif signal.bb_pct_b < 0.2:  # near lower band
                signal.bb_vote = 1        # oversold (potential bounce)
                weighted_score += WEIGHTS["bb_position"]

        # ── Pattern detection ─────────────────────────────────────────────
        from indicators.patterns import PatternDetector
        detector = PatternDetector(self.df)

        reversal = detector.detect_reversal_patterns()
        signal.pattern = reversal.get("pattern", "NONE")
        if signal.pattern in ("BULL_ENGULF", "HAMMER"):
            signal.reversal_vote = 1
            weighted_score += WEIGHTS["reversal"]
        elif signal.pattern in ("BEAR_ENGULF", "SHOOTING_STAR"):
            signal.reversal_vote = -1
            weighted_score -= WEIGHTS["reversal"]

        breakout = detector.detect_breakout()
        signal.breakout_type = breakout.get("breakout_type", "NONE")
        signal.breakout_confirmed = breakout.get("confirmed", False)
        if signal.breakout_type in ("VWAP_BULL", "EMA21_BULL") and signal.breakout_confirmed:
            signal.breakout_vote = 1
            weighted_score += WEIGHTS["breakout"]
        elif signal.breakout_type in ("VWAP_BEAR", "EMA21_BEAR") and signal.breakout_confirmed:
            signal.breakout_vote = -1
            weighted_score -= WEIGHTS["breakout"]

        trend = detector.get_trend_structure()
        signal.trend = trend.get("trend", "NEUTRAL")
        signal.trend_score = trend.get("score", 0)

        # ── Final signal calculation ──────────────────────────────────────
        confidence = min(abs(weighted_score) / MAX_SCORE * 100, 100.0)
        signal.confidence = round(confidence, 1)

        # Only signal if confidence is meaningful
        if weighted_score >= 2.0 and confidence >= 40:
            signal.signal = "BUY_CE"
            signal.direction = "BULLISH"
        elif weighted_score <= -2.0 and confidence >= 40:
            signal.signal = "BUY_PE"
            signal.direction = "BEARISH"
        else:
            signal.signal = "WAIT"
            signal.direction = "NEUTRAL"

        # ── Risk parameters ───────────────────────────────────────────────
        if signal.atr:
            signal.suggested_sl_points = round(signal.atr * 1.5, 1)
            signal.suggested_target_points = round(signal.atr * 2.5, 1)
            if signal.suggested_sl_points > 0:
                signal.risk_reward = round(
                    signal.suggested_target_points / signal.suggested_sl_points, 2
                )

        from datetime import datetime
        import pytz
        signal.timestamp = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()

        log.debug(
            "signal.generated",
            symbol=self.symbol,
            signal=signal.signal,
            confidence=signal.confidence,
            trend=signal.trend,
            weighted_score=round(weighted_score, 2),
        )

        return signal

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        try:
            if val is None or pd.isna(val):
                return None
            return round(float(val), 4)
        except Exception:
            return None
