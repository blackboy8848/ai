"""
backend/api/schemas/market.py
==============================
Pydantic schemas for all market data structures.
Used by REST endpoints and WebSocket broadcast payloads.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ── NIFTY Spot ────────────────────────────────────────────────────────────────

class NiftySpotData(BaseModel):
    symbol: str = "NIFTY 50"
    ltp: float                        # Last traded price
    open: float
    high: float
    low: float
    close: float                      # Previous close
    change: float                     # Absolute change
    change_pct: float                 # % change
    volume: int
    timestamp: datetime

    @property
    def is_positive(self) -> bool:
        return self.change >= 0


# ── India VIX ─────────────────────────────────────────────────────────────────

class VIXData(BaseModel):
    value: float
    change: float
    change_pct: float
    timestamp: datetime

    @property
    def sentiment(self) -> str:
        """VIX interpretation for options traders."""
        if self.value < 13:
            return "Very Low Volatility"
        elif self.value < 16:
            return "Low Volatility"
        elif self.value < 20:
            return "Moderate Volatility"
        elif self.value < 25:
            return "High Volatility"
        else:
            return "Extreme Volatility — Caution"


# ── Option Chain Strike ───────────────────────────────────────────────────────

class OptionStrike(BaseModel):
    strike: float
    expiry: str                       # "28-NOV-2024"

    # CE (Call) data
    ce_ltp: Optional[float] = None
    ce_oi: Optional[int] = None       # Open Interest
    ce_oi_change: Optional[int] = None
    ce_volume: Optional[int] = None
    ce_iv: Optional[float] = None     # Implied Volatility %
    ce_delta: Optional[float] = None
    ce_bid: Optional[float] = None
    ce_ask: Optional[float] = None

    # PE (Put) data
    pe_ltp: Optional[float] = None
    pe_oi: Optional[int] = None
    pe_oi_change: Optional[int] = None
    pe_volume: Optional[int] = None
    pe_iv: Optional[float] = None
    pe_delta: Optional[float] = None
    pe_bid: Optional[float] = None
    pe_ask: Optional[float] = None

    # Derived
    pcr: Optional[float] = None       # PE OI / CE OI for this strike
    is_atm: bool = False              # At The Money strike


# ── Option Chain ─────────────────────────────────────────────────────────────

class OptionChainData(BaseModel):
    underlying: str = "NIFTY"
    spot_price: float
    expiry: str
    timestamp: datetime

    strikes: List[OptionStrike] = []

    # Aggregate stats
    total_ce_oi: int = 0
    total_pe_oi: int = 0
    pcr: float = 0.0                  # Overall PCR
    max_pain: float = 0.0             # Strike with max combined OI
    atm_strike: float = 0.0

    @property
    def pcr_sentiment(self) -> str:
        if self.pcr > 1.2:
            return "Bullish"
        elif self.pcr < 0.8:
            return "Bearish"
        else:
            return "Neutral"


# ── Futures Data ──────────────────────────────────────────────────────────────

class FuturesData(BaseModel):
    symbol: str                       # "NIFTY24NOVFUT"
    ltp: float
    basis: float                      # Futures - Spot
    basis_pct: float
    oi: int
    oi_change: int
    volume: int
    expiry: str
    timestamp: datetime


# ── Global Market ────────────────────────────────────────────────────────────

class GlobalIndex(BaseModel):
    name: str                         # "Dow Jones", "Nasdaq", "S&P 500"
    symbol: str                       # "^DJI"
    ltp: float
    change: float
    change_pct: float
    timestamp: datetime


class GlobalMarketsData(BaseModel):
    indices: List[GlobalIndex] = []
    crude_oil: Optional[GlobalIndex] = None
    gold: Optional[GlobalIndex] = None
    usd_inr: Optional[float] = None
    timestamp: datetime


# ── Market Breadth ────────────────────────────────────────────────────────────

class MarketBreadthData(BaseModel):
    advances: int = 0
    declines: int = 0
    unchanged: int = 0
    advance_decline_ratio: float = 0.0
    nifty50_above_200dma: int = 0     # stocks above 200 DMA
    timestamp: datetime


# ── Full Market Snapshot (broadcast payload) ──────────────────────────────────

class MarketSnapshot(BaseModel):
    """
    Complete market state sent to frontend via WebSocket every second.
    The frontend stores this in marketStore and renders all widgets from it.
    """
    nifty: Optional[NiftySpotData] = None
    vix: Optional[VIXData] = None
    futures: Optional[FuturesData] = None
    option_chain: Optional[OptionChainData] = None
    global_markets: Optional[GlobalMarketsData] = None
    breadth: Optional[MarketBreadthData] = None
    market_status: str = "CLOSED"     # "PRE_OPEN" | "OPEN" | "CLOSED"
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ── REST response schemas ─────────────────────────────────────────────────────

class MarketStatusResponse(BaseModel):
    status: str
    is_open: bool
    next_open: Optional[str] = None
    next_close: Optional[str] = None
    current_time_ist: str


class OptionChainRequest(BaseModel):
    expiry: Optional[str] = None      # None = nearest expiry
    strikes_range: int = Field(default=10, ge=5, le=30)  # ATM ± N strikes
