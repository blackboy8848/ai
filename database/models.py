"""
backend/database/models.py
==========================
All ORM models for Phase 1.
Models for later phases (trades, signals, etc.) will be added
as we build each phase — they live here to keep migrations simple.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database.engine import Base


# ── Mixin: auto timestamps ────────────────────────────────────────────────────
class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── User ──────────────────────────────────────────────────────────────────────
class User(TimestampMixin, Base):
    """
    Platform user. Stores hashed password — never plaintext.
    One user can have multiple API credential sets (paper vs live).
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)

    # Relationships
    api_credentials = relationship(
        "APICredentials", back_populates="user", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    trading_config = relationship(
        "TradingConfig", back_populates="user", uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"


# ── API Credentials ───────────────────────────────────────────────────────────
class APICredentials(TimestampMixin, Base):
    """
    Angel One SmartAPI credentials stored per user.
    Sensitive fields (api_key, password, totp_secret) are AES-encrypted
    at the application layer before insert (see auth/encryption.py).
    """
    __tablename__ = "api_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "broker", name="uq_user_broker"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    broker = Column(String(50), nullable=False, default="angel_one")

    # Encrypted fields — never store raw
    encrypted_api_key = Column(Text, nullable=False)
    encrypted_client_id = Column(Text, nullable=False)
    encrypted_password = Column(Text, nullable=False)
    encrypted_totp_secret = Column(Text, nullable=False)

    is_active = Column(Boolean, default=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    user = relationship("User", back_populates="api_credentials")

    def __repr__(self) -> str:
        return f"<APICredentials user={self.user_id} broker={self.broker}>"


# ── User Session ──────────────────────────────────────────────────────────────
class UserSession(TimestampMixin, Base):
    """
    Tracks refresh tokens for multi-device login and forced logout support.
    Access tokens are stateless JWT; refresh tokens are stored here.
    """
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    refresh_token_hash = Column(String(255), nullable=False, unique=True)
    device_info = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)

    # Relationship
    user = relationship("User", back_populates="sessions")


# ── Trading Config ────────────────────────────────────────────────────────────
class TradingConfig(TimestampMixin, Base):
    """
    Per-user trading configuration and risk parameters.
    The LIVE_TRADING toggle is stored here so users can switch modes
    from the dashboard without restarting the server.
    """
    __tablename__ = "trading_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )

    # Trading mode — this is the master safety switch
    live_trading_enabled = Column(Boolean, default=False, nullable=False)
    paper_balance = Column(Float, default=1_000_000.0, nullable=False)

    # Risk parameters
    max_daily_loss_pct = Column(Float, default=3.0)    # stop at 3% loss
    max_trades_per_day = Column(Integer, default=10)
    min_ai_confidence = Column(Float, default=70.0)    # skip < 70%
    max_position_size_pct = Column(Float, default=5.0) # max 5% per trade

    # Strategy toggles
    ema_crossover_enabled = Column(Boolean, default=True)
    vwap_breakout_enabled = Column(Boolean, default=True)
    rsi_momentum_enabled = Column(Boolean, default=True)
    news_sentiment_weight = Column(Float, default=0.3)  # 30% weight in signal

    # Notifications
    telegram_chat_id = Column(String(100), nullable=True)
    telegram_bot_token = Column(Text, nullable=True)
    email_alerts_enabled = Column(Boolean, default=False)

    # Relationship
    user = relationship("User", back_populates="trading_config")


# ── Market Snapshot (Phase 2) ─────────────────────────────────────────────────
class MarketSnapshotRecord(Base):
    """
    Periodic snapshots of live market state from the stream engine.
    Written every ~60s while WebSocket clients are connected.
    """
    __tablename__ = "market_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nifty_ltp = Column(Float, nullable=True)
    vix_value = Column(Float, nullable=True)
    market_status = Column(String(20), nullable=False, default="CLOSED")
    pcr = Column(Float, nullable=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# ── Option Chain Snapshot (Phase 2) ───────────────────────────────────────────
class OptionChainRecord(Base):
    """Option chain snapshots persisted alongside market snapshots."""
    __tablename__ = "option_chain_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spot_price = Column(Float, nullable=False)
    expiry = Column(String(20), nullable=False)
    atm_strike = Column(Float, nullable=False)
    pcr = Column(Float, nullable=True)
    max_pain = Column(Float, nullable=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
