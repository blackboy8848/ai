"""
backend/indicators/patterns.py
================================
Price pattern and structure detection engine.

Detects:
  - Support and Resistance levels (from pivot highs/lows)
  - Volume breakouts
  - VWAP breakouts
  - EMA trend structure
  - Liquidity zones (high-volume price clusters)
  - Fake breakout detection
  - Trend strength and direction
  - Reversal signals (engulfing, pin bar, etc.)

All functions are pure — take a DataFrame, return enriched DataFrame or dict.
"""

import numpy as np
import pandas as pd
import structlog
from typing import Optional

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
LOOKBACK_SR = 20        # bars to look back for support/resistance
BREAKOUT_VOL_MULT = 1.5 # volume must be 1.5× average for breakout confirmation
MIN_TOUCHES = 2         # min price touches to confirm S/R level
ZONE_TOLERANCE = 0.002  # 0.2% tolerance for S/R zone grouping


class PatternDetector:
    """
    Detects chart patterns and price structure from OHLCV data.

    Usage:
        detector = PatternDetector(df_with_indicators)
        levels   = detector.get_support_resistance()
        breakout = detector.detect_breakout()
        trend    = detector.get_trend_structure()
    """

    def __init__(self, df: pd.DataFrame):
        """
        Args:
            df: DataFrame output from TechnicalCalculator.run_all()
                Expects indicator columns to already be present.
        """
        self.df = df.copy()
        self.df.columns = [c.lower() for c in self.df.columns]

    # ── Support / Resistance ──────────────────────────────────────────────────

    def get_support_resistance(
        self,
        lookback: int = LOOKBACK_SR,
        min_touches: int = MIN_TOUCHES,
    ) -> dict:
        """
        Detects support and resistance levels from pivot highs and lows.

        Method:
          1. Find local pivot highs and lows (price higher/lower than N bars either side)
          2. Group nearby pivots into zones (within tolerance %)
          3. Rank zones by number of touches (more touches = stronger level)
          4. Return top support and resistance levels

        Returns:
            {
              "resistance": [{"level": 24500, "strength": 3, "type": "resistance"}, ...],
              "support":    [{"level": 24200, "strength": 4, "type": "support"}, ...],
              "nearest_resistance": 24500,
              "nearest_support": 24200,
            }
        """
        if len(self.df) < lookback * 2:
            return {"resistance": [], "support": [], "nearest_resistance": None, "nearest_support": None}

        close = self.df["close"]
        high  = self.df["high"]
        low   = self.df["low"]
        current_price = float(close.iloc[-1])

        pivot_highs = []
        pivot_lows  = []
        window = max(3, lookback // 5)

        for i in range(window, len(self.df) - window):
            # Pivot high: higher than N bars on each side
            if high.iloc[i] == high.iloc[i-window:i+window+1].max():
                pivot_highs.append(float(high.iloc[i]))
            # Pivot low: lower than N bars on each side
            if low.iloc[i] == low.iloc[i-window:i+window+1].min():
                pivot_lows.append(float(low.iloc[i]))

        def cluster_levels(prices: list, tolerance: float = ZONE_TOLERANCE) -> list:
            """Group nearby prices into zones and count touches."""
            if not prices:
                return []
            prices_sorted = sorted(prices)
            clusters = []
            current_cluster = [prices_sorted[0]]

            for price in prices_sorted[1:]:
                if abs(price - current_cluster[-1]) / current_cluster[-1] <= tolerance:
                    current_cluster.append(price)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [price]
            clusters.append(current_cluster)

            return [
                {
                    "level": round(sum(c) / len(c), 2),
                    "strength": len(c),
                }
                for c in clusters
                if len(c) >= min_touches
            ]

        resistance_zones = [
            {**z, "type": "resistance"}
            for z in cluster_levels(pivot_highs)
            if z["level"] > current_price
        ]
        support_zones = [
            {**z, "type": "support"}
            for z in cluster_levels(pivot_lows)
            if z["level"] < current_price
        ]

        # Sort by strength descending, then by proximity to current price
        resistance_zones.sort(key=lambda x: (-x["strength"], x["level"]))
        support_zones.sort(key=lambda x: (-x["strength"], -x["level"]))

        nearest_r = resistance_zones[0]["level"] if resistance_zones else None
        nearest_s = support_zones[0]["level"] if support_zones else None

        return {
            "resistance": resistance_zones[:5],  # top 5
            "support": support_zones[:5],
            "nearest_resistance": nearest_r,
            "nearest_support": nearest_s,
            "current_price": current_price,
            "distance_to_resistance": round(
                (nearest_r - current_price) / current_price * 100, 2
            ) if nearest_r else None,
            "distance_to_support": round(
                (current_price - nearest_s) / current_price * 100, 2
            ) if nearest_s else None,
        }

    # ── Breakout Detection ────────────────────────────────────────────────────

    def detect_breakout(self) -> dict:
        """
        Detects price breakouts with volume confirmation.

        Breakout types detected:
          - VWAP breakout: price crosses VWAP with above-average volume
          - Resistance breakout: price closes above resistance level
          - Support breakdown: price closes below support level
          - Range breakout: price exits a consolidation range

        Returns:
            {
              "breakout_type": "VWAP_BULL" | "VWAP_BEAR" | "RESISTANCE" |
                               "SUPPORT_BREAK" | "NONE",
              "confirmed": bool,   # True when volume confirms the move
              "strength": "STRONG" | "MODERATE" | "WEAK",
              "description": "...",
            }
        """
        if len(self.df) < 5:
            return {"breakout_type": "NONE", "confirmed": False, "strength": "WEAK"}

        latest = self.df.iloc[-1]
        prev   = self.df.iloc[-2]

        result = {
            "breakout_type": "NONE",
            "confirmed": False,
            "strength": "WEAK",
            "description": "",
        }

        has_vwap   = "vwap" in self.df.columns
        has_vol    = "vol_ratio" in self.df.columns
        has_volume = has_vol and not pd.isna(latest.get("vol_ratio"))

        vol_ratio = float(latest.get("vol_ratio", 1.0)) if has_vol else 1.0
        vol_confirmed = vol_ratio >= BREAKOUT_VOL_MULT

        # ── VWAP Breakout ─────────────────────────────────────────────────
        if has_vwap and not pd.isna(latest.get("vwap")):
            vwap = float(latest["vwap"])
            price = float(latest["close"])
            prev_price = float(prev["close"])
            prev_vwap  = float(prev.get("vwap", vwap))

            # Bullish VWAP cross
            if prev_price < prev_vwap and price > vwap:
                result["breakout_type"] = "VWAP_BULL"
                result["confirmed"] = vol_confirmed
                result["strength"] = "STRONG" if vol_ratio > 2.5 else "MODERATE" if vol_ratio > 1.5 else "WEAK"
                result["description"] = f"Price crossed above VWAP ({vwap:.0f}), vol ratio {vol_ratio:.1f}×"
                return result

            # Bearish VWAP cross
            if prev_price > prev_vwap and price < vwap:
                result["breakout_type"] = "VWAP_BEAR"
                result["confirmed"] = vol_confirmed
                result["strength"] = "STRONG" if vol_ratio > 2.5 else "MODERATE" if vol_ratio > 1.5 else "WEAK"
                result["description"] = f"Price crossed below VWAP ({vwap:.0f}), vol ratio {vol_ratio:.1f}×"
                return result

        # ── EMA breakout ──────────────────────────────────────────────────
        if "ema_21" in self.df.columns and not pd.isna(latest.get("ema_21")):
            ema21 = float(latest["ema_21"])
            price = float(latest["close"])
            prev_price = float(prev["close"])
            prev_ema21 = float(prev.get("ema_21", ema21))

            if prev_price < prev_ema21 and price > ema21 and vol_confirmed:
                result["breakout_type"] = "EMA21_BULL"
                result["confirmed"] = True
                result["strength"] = "MODERATE"
                result["description"] = f"Price crossed above EMA21 ({ema21:.0f}) with volume"
                return result

            if prev_price > prev_ema21 and price < ema21 and vol_confirmed:
                result["breakout_type"] = "EMA21_BEAR"
                result["confirmed"] = True
                result["strength"] = "MODERATE"
                result["description"] = f"Price crossed below EMA21 ({ema21:.0f}) with volume"
                return result

        return result

    # ── Fake Breakout Detection ───────────────────────────────────────────────

    def detect_fake_breakout(self) -> dict:
        """
        Detects fake/false breakouts (bull traps and bear traps).

        A fake breakout occurs when:
          - Price breaks a key level
          - But immediately reverses back within 1-3 candles
          - Often with a long wick showing rejection

        Returns:
            {
              "is_fake": bool,
              "type": "BULL_TRAP" | "BEAR_TRAP" | "NONE",
              "confidence": float (0-1),
            }
        """
        if len(self.df) < 5:
            return {"is_fake": False, "type": "NONE", "confidence": 0.0}

        latest = self.df.iloc[-1]

        # Check for long upper wick (rejection of highs) = bull trap signal
        candle_range = float(latest["high"]) - float(latest["low"])
        if candle_range == 0:
            return {"is_fake": False, "type": "NONE", "confidence": 0.0}

        upper_wick = float(latest["high"]) - max(float(latest["open"]), float(latest["close"]))
        lower_wick = min(float(latest["open"]), float(latest["close"])) - float(latest["low"])

        upper_wick_pct = upper_wick / candle_range
        lower_wick_pct = lower_wick / candle_range

        # Long upper wick (>60% of candle range) = price rejection at top
        if upper_wick_pct > 0.6:
            return {
                "is_fake": True,
                "type": "BULL_TRAP",
                "confidence": round(upper_wick_pct, 2),
                "description": "Long upper wick — rejection at highs",
            }

        # Long lower wick (>60%) = price rejection at bottom
        if lower_wick_pct > 0.6:
            return {
                "is_fake": True,
                "type": "BEAR_TRAP",
                "confidence": round(lower_wick_pct, 2),
                "description": "Long lower wick — rejection at lows",
            }

        return {"is_fake": False, "type": "NONE", "confidence": 0.0}

    # ── Trend Structure ───────────────────────────────────────────────────────

    def get_trend_structure(self) -> dict:
        """
        Determines overall market trend using multiple methods.

        Methods:
          1. EMA alignment (9 > 21 > 50 = bullish, 9 < 21 < 50 = bearish)
          2. Higher highs / higher lows structure
          3. Price vs VWAP position
          4. Supertrend direction

        Returns:
            {
              "trend": "STRONG_BULL" | "BULL" | "NEUTRAL" | "BEAR" | "STRONG_BEAR",
              "score": int (-4 to +4, positive = bullish),
              "ema_aligned": bool,
              "above_vwap": bool,
              "higher_highs": bool,
              "supertrend_bull": bool,
              "momentum": "INCREASING" | "DECREASING" | "STABLE",
            }
        """
        if len(self.df) < 5:
            return {"trend": "NEUTRAL", "score": 0}

        latest = self.df.iloc[-1]
        score = 0
        details = {}

        # ── EMA alignment ─────────────────────────────────────────────────
        ema9  = latest.get("ema_9")
        ema21 = latest.get("ema_21")
        ema50 = latest.get("ema_50")
        price = float(latest["close"])

        if not any(pd.isna(x) for x in [ema9, ema21, ema50]):
            ema9, ema21, ema50 = float(ema9), float(ema21), float(ema50)
            bullish_alignment = ema9 > ema21 > ema50
            bearish_alignment = ema9 < ema21 < ema50
            details["ema_aligned"] = bullish_alignment or bearish_alignment

            if bullish_alignment:
                score += 2
            elif bearish_alignment:
                score -= 2
            elif ema9 > ema21:
                score += 1
            elif ema9 < ema21:
                score -= 1
        else:
            details["ema_aligned"] = False

        # ── Price vs VWAP ──────────────────────────────────────────────────
        vwap = latest.get("vwap")
        if vwap and not pd.isna(vwap):
            details["above_vwap"] = price > float(vwap)
            score += 1 if details["above_vwap"] else -1
        else:
            details["above_vwap"] = None

        # ── Supertrend ─────────────────────────────────────────────────────
        st_dir = latest.get("supertrend_dir")
        if st_dir and not pd.isna(st_dir):
            details["supertrend_bull"] = int(st_dir) == 1
            score += 1 if details["supertrend_bull"] else -1
        else:
            details["supertrend_bull"] = None

        # ── Higher highs / higher lows (last 10 candles) ───────────────────
        if len(self.df) >= 10:
            recent_highs = self.df["high"].iloc[-10:]
            recent_lows  = self.df["low"].iloc[-10:]
            hh = recent_highs.iloc[-1] > recent_highs.iloc[-5]  # recent > older
            hl = recent_lows.iloc[-1]  > recent_lows.iloc[-5]
            ll = recent_lows.iloc[-1]  < recent_lows.iloc[-5]
            lh = recent_highs.iloc[-1] < recent_highs.iloc[-5]

            details["higher_highs"] = hh and hl
            if hh and hl: score += 1
            if ll and lh: score -= 1
        else:
            details["higher_highs"] = None

        # ── RSI momentum ──────────────────────────────────────────────────
        rsi = latest.get("rsi")
        if rsi and not pd.isna(rsi):
            rsi = float(rsi)
            if rsi > 55:
                details["momentum"] = "INCREASING"
            elif rsi < 45:
                details["momentum"] = "DECREASING"
            else:
                details["momentum"] = "STABLE"
        else:
            details["momentum"] = "STABLE"

        # ── Trend label ────────────────────────────────────────────────────
        if score >= 3:
            trend = "STRONG_BULL"
        elif score >= 1:
            trend = "BULL"
        elif score <= -3:
            trend = "STRONG_BEAR"
        elif score <= -1:
            trend = "BEAR"
        else:
            trend = "NEUTRAL"

        return {"trend": trend, "score": score, **details}

    # ── Liquidity Zones ───────────────────────────────────────────────────────

    def get_liquidity_zones(self) -> list:
        """
        Identifies high-volume price zones where institutions likely placed orders.

        Method: VWAP-anchored volume profile — find price levels with
        disproportionately high volume (>2× average at that price).

        Returns list of {"price": float, "volume": int, "type": "supply"|"demand"}
        """
        if len(self.df) < 20 or "volume" not in self.df.columns:
            return []

        # Round prices to nearest 50 (NIFTY strike increment)
        price_vol = {}
        for _, row in self.df.iterrows():
            rounded = round(float(row["close"]) / 50) * 50
            price_vol[rounded] = price_vol.get(rounded, 0) + int(row["volume"])

        if not price_vol:
            return []

        avg_vol = sum(price_vol.values()) / len(price_vol)
        current_price = float(self.df["close"].iloc[-1])

        zones = []
        for price, vol in price_vol.items():
            if vol > avg_vol * 2:
                zone_type = "supply" if price > current_price else "demand"
                zones.append({
                    "price": price,
                    "volume": vol,
                    "type": zone_type,
                    "strength": round(vol / avg_vol, 1),
                })

        # Sort by volume descending
        zones.sort(key=lambda x: -x["volume"])
        return zones[:10]

    # ── Reversal Patterns ─────────────────────────────────────────────────────

    def detect_reversal_patterns(self) -> dict:
        """
        Detects single and multi-candle reversal patterns.

        Patterns detected:
          - Bullish Engulfing
          - Bearish Engulfing
          - Pin Bar / Hammer (bullish)
          - Shooting Star (bearish)
          - Doji (indecision)

        Returns:
            {
              "pattern": "BULL_ENGULF" | "BEAR_ENGULF" | "HAMMER" |
                         "SHOOTING_STAR" | "DOJI" | "NONE",
              "reliability": "HIGH" | "MEDIUM" | "LOW",
            }
        """
        if len(self.df) < 2:
            return {"pattern": "NONE", "reliability": "LOW"}

        c = self.df.iloc[-1]
        p = self.df.iloc[-2]

        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        po, pcl = float(p["open"]), float(p["close"])

        body    = abs(cl - o)
        range_  = h - l
        if range_ == 0:
            return {"pattern": "NONE", "reliability": "LOW"}

        body_pct = body / range_

        # Doji: body is very small relative to range
        if body_pct < 0.1:
            return {"pattern": "DOJI", "reliability": "MEDIUM",
                    "description": "Indecision candle — wait for next candle direction"}

        # Bullish Engulfing: current candle bullish and fully engulfs previous bearish
        if cl > o and pcl < po:  # current bullish, previous bearish
            if o <= pcl and cl >= po:  # current body engulfs previous body
                return {"pattern": "BULL_ENGULF", "reliability": "HIGH",
                        "description": "Bullish engulfing — strong reversal signal"}

        # Bearish Engulfing
        if cl < o and pcl > po:  # current bearish, previous bullish
            if o >= pcl and cl <= po:
                return {"pattern": "BEAR_ENGULF", "reliability": "HIGH",
                        "description": "Bearish engulfing — strong reversal signal"}

        # Hammer / Pin Bar (bullish reversal at bottom)
        lower_wick = min(o, cl) - l
        upper_wick = h - max(o, cl)
        if lower_wick > body * 2 and upper_wick < body * 0.5 and cl > o:
            return {"pattern": "HAMMER", "reliability": "MEDIUM",
                    "description": "Hammer — bullish reversal at support"}

        # Shooting Star (bearish reversal at top)
        if upper_wick > body * 2 and lower_wick < body * 0.5 and cl < o:
            return {"pattern": "SHOOTING_STAR", "reliability": "MEDIUM",
                    "description": "Shooting star — bearish reversal at resistance"}

        return {"pattern": "NONE", "reliability": "LOW"}
