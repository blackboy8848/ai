"""
backend/config/settings.py
==========================
Central configuration loaded from environment variables.
All modules import from here — never read os.environ directly.
"""

from functools import lru_cache
from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_secret_key: str = Field(..., min_length=32)
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    debug: bool = Field(default=False)

    # ── JWT ──────────────────────────────────────────────
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=60)
    jwt_refresh_token_expire_days: int = Field(default=7)

    # ── PostgreSQL ───────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://trading_user:password@localhost:5432/trading_db"
    )

    # ── Redis ────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379")

    # ── Angel One SmartAPI ───────────────────────────────
    angel_one_api_key: str = Field(default="")
    angel_one_client_id: str = Field(default="")
    angel_one_password: str = Field(default="")
    angel_one_totp_secret: str = Field(default="")
    angel_one_base_url: str = Field(
        default="https://apiconnect.angelone.in"
    )

    # ── Trading Mode ─────────────────────────────────────
    live_trading: bool = Field(default=False)          # CRITICAL safety flag
    paper_trading_balance: float = Field(default=1_000_000.0)  # ₹10 lakh

    # ── Risk Defaults ────────────────────────────────────
    max_daily_loss_pct: float = Field(default=3.0)     # stop after 3% loss
    max_trades_per_day: int = Field(default=10)
    min_ai_confidence: float = Field(default=70.0)     # ignore < 70% confidence

    # ── Derived helpers ──────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def trading_mode_label(self) -> str:
        return "LIVE" if self.live_trading else "PAPER"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached singleton — import and call this everywhere.

    Usage:
        from config.settings import get_settings
        settings = get_settings()
    """
    return Settings()
