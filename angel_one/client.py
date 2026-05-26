"""
backend/angel_one/client.py
============================
Angel One SmartAPI wrapper.

Handles:
- TOTP-based login (required by Angel One)
- Session token caching (avoid re-login on every request)
- Automatic re-authentication on token expiry
- All HTTP calls via async httpx with retry logic
- Structured error logging

Angel One API docs: https://smartapi.angelone.in/docs
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pyotp
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# Angel One API endpoints
_BASE = settings.angel_one_base_url
_ENDPOINTS = {
    "login":        f"{_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
    "logout":       f"{_BASE}/rest/secure/angelbroking/user/v1/logout",
    "profile":      f"{_BASE}/rest/secure/angelbroking/user/v1/getProfile",
    "quote":        f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
    "option_chain": f"{_BASE}/rest/secure/angelbroking/market/v1/getCandleData",
    "place_order":  f"{_BASE}/rest/secure/angelbroking/order/v1/placeOrder",
    "order_book":   f"{_BASE}/rest/secure/angelbroking/order/v1/getOrderBook",
    "positions":    f"{_BASE}/rest/secure/angelbroking/order/v1/getPosition",
    "holdings":     f"{_BASE}/rest/secure/angelbroking/portfolio/v1/getHolding",
    "candle_data":  f"{_BASE}/rest/secure/angelbroking/historical/v1/getCandleData",
}


class AngelOneAuthError(Exception):
    """Raised when authentication with Angel One fails."""
    pass


class AngelOneAPIError(Exception):
    """Raised when an Angel One API call returns an error."""
    def __init__(self, message: str, status_code: int = 0, error_code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class AngelOneClient:
    """
    Async Angel One SmartAPI client.

    Usage:
        client = AngelOneClient(api_key, client_id, password, totp_secret)
        await client.ensure_authenticated()
        quote = await client.get_quote("NSE", "NIFTY-EQ", "99926000")

    The client maintains a single session and auto-renews it when expired.
    """

    def __init__(
        self,
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str,
    ):
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret

        # Session state
        self._jwt_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._lock = asyncio.Lock()

        # Shared async HTTP client (connection pooling)
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": self.api_key,
            },
        )

    # ── Authentication ────────────────────────────────────────────────────────

    def _generate_totp(self) -> str:
        """Generates the current TOTP code from the base32 secret."""
        return pyotp.TOTP(self.totp_secret).now()

    async def login(self) -> None:
        """
        Authenticates with Angel One using client ID + password + TOTP.
        Angel One requires TOTP on every login — no way around this.
        """
        totp_code = self._generate_totp()
        payload = {
            "clientcode": self.client_id,
            "password": self.password,
            "totp": totp_code,
        }

        log.info("angel_one.login.attempt", client_id=self.client_id)

        try:
            resp = await self._http.post(_ENDPOINTS["login"], json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise AngelOneAuthError(f"HTTP error during login: {e}")
        except httpx.RequestError as e:
            raise AngelOneAuthError(f"Network error during login: {e}")

        if not data.get("status"):
            error_msg = data.get("message", "Unknown login error")
            log.error("angel_one.login.failed", error=error_msg)
            raise AngelOneAuthError(f"Login failed: {error_msg}")

        token_data = data.get("data", {})
        self._jwt_token = token_data.get("jwtToken")
        self._refresh_token = token_data.get("refreshToken")
        self._feed_token = token_data.get("feedToken")

        # Angel One tokens expire after ~24 hours; we refresh at 23h
        self._token_expiry = datetime.now(timezone.utc) + timedelta(hours=23)

        # Update Authorization header for subsequent calls
        self._http.headers.update({"Authorization": f"Bearer {self._jwt_token}"})

        log.info(
            "angel_one.login.success",
            client_id=self.client_id,
            token_expiry=self._token_expiry.isoformat(),
        )

    async def ensure_authenticated(self) -> None:
        """
        Checks if the current session is valid; re-authenticates if not.
        Thread-safe via asyncio.Lock — prevents duplicate login storms.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            if (
                self._jwt_token is None
                or self._token_expiry is None
                or now >= self._token_expiry
            ):
                await self.login()

    async def logout(self) -> None:
        """Invalidates the current Angel One session."""
        try:
            await self._authenticated_post(
                _ENDPOINTS["logout"],
                {"clientcode": self.client_id},
            )
        except Exception as e:
            log.warning("angel_one.logout.error", error=str(e))
        finally:
            self._jwt_token = None
            self._token_expiry = None

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _authenticated_get(self, url: str, params: dict = None) -> dict:
        """GET with auto-auth refresh and retry on network errors."""
        await self.ensure_authenticated()
        resp = await self._http.get(url, params=params or {})
        return self._handle_response(resp)

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _authenticated_post(self, url: str, payload: dict) -> dict:
        """POST with auto-auth refresh and retry on network errors."""
        await self.ensure_authenticated()
        resp = await self._http.post(url, json=payload)
        return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> dict:
        """Parses Angel One response, raises on error status."""
        try:
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise AngelOneAPIError(
                f"HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        if not data.get("status"):
            raise AngelOneAPIError(
                message=data.get("message", "API error"),
                error_code=data.get("errorcode", ""),
            )
        return data.get("data", {})

    # ── Market Data ───────────────────────────────────────────────────────────

    async def get_quote(
        self, exchange: str, symbol_token: str, trading_symbol: str
    ) -> dict:
        """
        Fetch LTP + OHLCV for a single instrument.

        Args:
            exchange: "NSE" | "NFO" | "BSE"
            symbol_token: Angel One token ID (e.g., "99926000" for NIFTY)
            trading_symbol: e.g., "Nifty 50"
        """
        payload = {
            "mode": "FULL",
            "exchangeTokens": {exchange: [symbol_token]},
        }
        data = await self._authenticated_post(_ENDPOINTS["quote"], payload)
        log.debug("angel_one.quote.fetched", symbol=trading_symbol)
        return data

    async def get_candle_data(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[list]:
        """
        Fetch historical OHLCV candles.

        Args:
            interval: ONE_MINUTE | THREE_MINUTE | FIVE_MINUTE | TEN_MINUTE |
                      FIFTEEN_MINUTE | THIRTY_MINUTE | ONE_HOUR | ONE_DAY
            from_date: "YYYY-MM-DD HH:MM"
            to_date:   "YYYY-MM-DD HH:MM"

        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        payload = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        data = await self._authenticated_post(_ENDPOINTS["candle_data"], payload)
        return data  # returns raw list directly

    async def get_profile(self) -> dict:
        """Fetch the authenticated user's Angel One profile."""
        return await self._authenticated_get(_ENDPOINTS["profile"])

    # ── Order Management ──────────────────────────────────────────────────────

    async def place_order(
        self,
        variety: str,
        trading_symbol: str,
        symbol_token: str,
        transaction_type: str,   # "BUY" | "SELL"
        exchange: str,           # "NFO" for options
        order_type: str,         # "MARKET" | "LIMIT" | "SL" | "SL-M"
        product_type: str,       # "CARRYFORWARD" | "INTRADAY" | "DELIVERY"
        duration: str,           # "DAY" | "IOC"
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> str:
        """
        Places a live order. Returns the Angel One order ID.

        SAFETY: Only callable when LIVE_TRADING = True.
        All paper trading goes through paper_trading/engine.py instead.
        """
        from config.settings import get_settings
        if not get_settings().live_trading:
            raise RuntimeError(
                "Live order placement blocked: LIVE_TRADING=False. "
                "Use paper_trading/engine.py for simulated orders."
            )

        payload = {
            "variety": variety,
            "tradingsymbol": trading_symbol,
            "symboltoken": symbol_token,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": product_type,
            "duration": duration,
            "quantity": str(quantity),
            "price": str(price),
            "triggerprice": str(trigger_price),
        }

        log.info(
            "angel_one.order.placing",
            symbol=trading_symbol,
            side=transaction_type,
            qty=quantity,
        )
        data = await self._authenticated_post(_ENDPOINTS["place_order"], payload)
        order_id = data.get("orderid", "")
        log.info("angel_one.order.placed", order_id=order_id)
        return order_id

    async def get_order_book(self) -> list[dict]:
        """Fetch today's order book."""
        data = await self._authenticated_get(_ENDPOINTS["order_book"])
        return data or []

    async def get_positions(self) -> list[dict]:
        """Fetch open positions."""
        data = await self._authenticated_get(_ENDPOINTS["positions"])
        return data or []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on app shutdown."""
        await self._http.aclose()
