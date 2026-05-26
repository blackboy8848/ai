"""
backend/api/schemas/indicators.py
====================================
Pydantic v2 schemas for the technical analysis API.
"""

from typing import Optional, List
from pydantic import BaseModel


class SupportResistanceLevel(BaseModel):
    level: float
    strength: int
    type: str            # "support" | "resistance"


class SupportResistanceData(BaseModel):
    resistance: List[SupportResistanceLevel] = []
    support: List[SupportResistanceLevel] = []
    nearest_resistance: Optional[float] = None
    nearest_support: Optional[float] = None
    current_price: Optional[float] = None
    distance_to_resistance: Optional[float] = None
    distance_to_support: Optional[float] = None


class BreakoutData(BaseModel):
    breakout_type: str = "NONE"
    confirmed: bool = False
    strength: str = "WEAK"
    description: str = ""


class TrendData(BaseModel):
    trend: str = "NEUTRAL"
    score: int = 0
    ema_aligned: Optional[bool] = None
    above_vwap: Optional[bool] = None
    higher_highs: Optional[bool] = None
    supertrend_bull: Optional[bool] = None
    momentum: str = "STABLE"


class ReversalData(BaseModel):
    pattern: str = "NONE"
    reliability: str = "LOW"
    description: str = ""


class LiquidityZone(BaseModel):
    price: float
    volume: int
    type: str            # "supply" | "demand"
    strength: float


class TechnicalSignalResponse(BaseModel):
    # Signal
    signal: str          # "BUY_CE" | "BUY_PE" | "WAIT"
    direction: str       # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: float    # 0–100

    # Indicator votes (for dashboard display)
    ema_vote: int = 0
    rsi_vote: int = 0
    macd_vote: int = 0
    vwap_vote: int = 0
    supertrend_vote: int = 0
    volume_vote: int = 0
    bb_vote: int = 0
    breakout_vote: int = 0
    reversal_vote: int = 0

    # Raw values
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

    # Risk
    suggested_sl_points: Optional[float] = None
    suggested_target_points: Optional[float] = None
    risk_reward: Optional[float] = None

    # Meta
    symbol: str = "NIFTY"
    timeframe: str = "5m"
    timestamp: Optional[str] = None
    candle_count: int = 0


class IndicatorSummaryResponse(BaseModel):
    """Compact summary for dashboard header display."""
    symbol: str
    timeframe: str
    signal: str
    direction: str
    confidence: float
    trend: str
    rsi: Optional[float]
    macd_hist: Optional[float]
    above_vwap: Optional[bool]
    supertrend_bull: Optional[bool]
    timestamp: Optional[str]
