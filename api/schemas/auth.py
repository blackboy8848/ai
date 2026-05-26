"""
backend/api/schemas/auth.py
============================
Pydantic v2 schemas for auth endpoints.
These are the request bodies and response shapes — not DB models.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Registration ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class RegisterResponse(BaseModel):
    id: UUID
    email: str
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds until access token expiry


class RefreshRequest(BaseModel):
    refresh_token: str


# ── User Profile ──────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    id: UUID
    email: str
    username: str
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Angel One Credentials ─────────────────────────────────────────────────────

class AngelOneCredentialsRequest(BaseModel):
    """
    Submitted once by the user from the Settings page.
    All fields are encrypted before DB storage.
    """
    api_key: str = Field(min_length=8)
    client_id: str = Field(min_length=3)
    password: str = Field(min_length=4, description="Angel One MPIN")
    totp_secret: str = Field(
        min_length=16,
        description="Base32 TOTP secret from Angel One QR code"
    )


class AngelOneCredentialsResponse(BaseModel):
    id: UUID
    broker: str
    is_active: bool
    last_verified_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class AngelOneVerifyResponse(BaseModel):
    success: bool
    profile: Optional[dict] = None
    message: str


# ── Trading Config ────────────────────────────────────────────────────────────

class TradingConfigUpdate(BaseModel):
    live_trading_enabled: Optional[bool] = None
    paper_balance: Optional[float] = Field(default=None, gt=0)
    max_daily_loss_pct: Optional[float] = Field(default=None, gt=0, le=100)
    max_trades_per_day: Optional[int] = Field(default=None, gt=0, le=100)
    min_ai_confidence: Optional[float] = Field(default=None, ge=0, le=100)
    max_position_size_pct: Optional[float] = Field(default=None, gt=0, le=100)
    ema_crossover_enabled: Optional[bool] = None
    vwap_breakout_enabled: Optional[bool] = None
    rsi_momentum_enabled: Optional[bool] = None
    news_sentiment_weight: Optional[float] = Field(default=None, ge=0, le=1)
    telegram_chat_id: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    email_alerts_enabled: Optional[bool] = None


class TradingConfigResponse(BaseModel):
    live_trading_enabled: bool
    paper_balance: float
    max_daily_loss_pct: float
    max_trades_per_day: int
    min_ai_confidence: float
    max_position_size_pct: float
    ema_crossover_enabled: bool
    vwap_breakout_enabled: bool
    rsi_momentum_enabled: bool
    news_sentiment_weight: float
    email_alerts_enabled: bool
    trading_mode: str          # "PAPER" | "LIVE"

    model_config = {"from_attributes": True}
