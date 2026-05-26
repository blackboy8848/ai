"""
backend/api/routes/auth.py
==========================
All authentication and user-settings endpoints.

Routes:
  POST /auth/register           — create account
  POST /auth/login              — get access + refresh tokens
  POST /auth/refresh            — rotate tokens
  POST /auth/logout             — revoke refresh token
  GET  /auth/me                 — current user profile
  POST /auth/credentials        — save Angel One API credentials
  GET  /auth/credentials        — get credential status (no secrets returned)
  POST /auth/credentials/verify — test Angel One connection
  GET  /auth/config             — get trading config
  PATCH /auth/config            — update trading config
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from angel_one.registry import angel_registry
from api.schemas.auth import (
    AngelOneCredentialsRequest,
    AngelOneCredentialsResponse,
    AngelOneVerifyResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    TradingConfigResponse,
    TradingConfigUpdate,
    UserProfile,
)
from auth.dependencies import get_current_user
from auth.encryption import encrypt
from auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from config.settings import get_settings
from database.engine import get_db
from database.models import APICredentials, TradingConfig, User, UserSession

log = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])

_CONFIG_FIELDS = {
    "live_trading_enabled",
    "paper_balance",
    "max_daily_loss_pct",
    "max_trades_per_day",
    "min_ai_confidence",
    "max_position_size_pct",
    "ema_crossover_enabled",
    "vwap_breakout_enabled",
    "rsi_momentum_enabled",
    "news_sentiment_weight",
    "email_alerts_enabled",
}


def _trading_config_response(config: TradingConfig) -> TradingConfigResponse:
    return TradingConfigResponse(
        **{k: getattr(config, k) for k in _CONFIG_FIELDS},
        trading_mode="LIVE" if config.live_trading_enabled else "PAPER",
    )


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new platform user."""

    # Check uniqueness
    existing = await db.execute(
        select(User).where(
            (User.email == body.email) | (User.username == body.username)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()   # get user.id before commit

    # Create default trading config for this user
    config = TradingConfig(
        user_id=user.id,
        live_trading_enabled=False,    # always start in paper mode
        paper_balance=settings.paper_trading_balance,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        max_trades_per_day=settings.max_trades_per_day,
        min_ai_confidence=settings.min_ai_confidence,
    )
    db.add(config)
    await db.commit()
    await db.refresh(user)

    log.info("auth.register.success", user_id=str(user.id), email=user.email)
    return user


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT tokens."""

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Constant-time failure — don't reveal whether email exists
    if not user or not verify_password(body.password, user.hashed_password):
        log.warning("auth.login.failed", email=body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    access_token = create_access_token(str(user.id), user.email)
    raw_refresh, refresh_hash = create_refresh_token(str(user.id))

    # Store hashed refresh token
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        device_info=request.headers.get("User-Agent", "")[:255],
        ip_address=request.client.host if request.client else None,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    db.add(session)
    await db.commit()

    log.info("auth.login.success", user_id=str(user.id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


# ── Token Refresh ─────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Issue a new access token using a valid refresh token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )

    try:
        payload = decode_refresh_token(body.refresh_token)
        user_id = payload.get("sub")
    except JWTError:
        raise credentials_exception

    token_hash = hash_token(body.refresh_token)
    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.is_revoked == False,
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise credentials_exception

    # Rotate: revoke old, issue new
    session.is_revoked = True

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception

    new_access = create_access_token(str(user.id), user.email)
    new_raw_refresh, new_refresh_hash = create_refresh_token(str(user.id))

    new_session = UserSession(
        user_id=user.id,
        refresh_token_hash=new_refresh_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    db.add(new_session)
    await db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_raw_refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the given refresh token."""
    token_hash = hash_token(body.refresh_token)
    await db.execute(
        update(UserSession)
        .where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.user_id == current_user.id,
        )
        .values(is_revoked=True)
    )
    await db.commit()
    log.info("auth.logout", user_id=str(current_user.id))


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfile)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user


# ── Angel One Credentials ─────────────────────────────────────────────────────

@router.post("/credentials", response_model=AngelOneCredentialsResponse, status_code=201)
async def save_credentials(
    body: AngelOneCredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save (or replace) Angel One API credentials for the current user.
    All sensitive fields are AES-encrypted before storage.
    """
    # Deactivate any existing credentials
    await db.execute(
        update(APICredentials)
        .where(
            APICredentials.user_id == current_user.id,
            APICredentials.broker == "angel_one",
        )
        .values(is_active=False)
    )

    creds = APICredentials(
        user_id=current_user.id,
        broker="angel_one",
        encrypted_api_key=encrypt(body.api_key),
        encrypted_client_id=encrypt(body.client_id),
        encrypted_password=encrypt(body.password),
        encrypted_totp_secret=encrypt(body.totp_secret),
        is_active=True,
    )
    db.add(creds)
    await db.commit()
    await db.refresh(creds)

    # Remove cached client so it re-initialises with new credentials
    await angel_registry.remove_client(current_user.id)

    log.info("auth.credentials.saved", user_id=str(current_user.id))
    return creds


@router.get("/credentials", response_model=Optional[AngelOneCredentialsResponse])
async def get_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return credential metadata (never the secrets themselves)."""
    result = await db.execute(
        select(APICredentials).where(
            APICredentials.user_id == current_user.id,
            APICredentials.broker == "angel_one",
            APICredentials.is_active == True,
        )
    )
    return result.scalar_one_or_none()


@router.post("/credentials/verify", response_model=AngelOneVerifyResponse)
async def verify_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test the Angel One connection and return the broker profile."""
    try:
        client = await angel_registry.get_client(current_user.id, db)
        profile = await client.get_profile()

        # Mark as verified
        await db.execute(
            update(APICredentials)
            .where(
                APICredentials.user_id == current_user.id,
                APICredentials.broker == "angel_one",
            )
            .values(last_verified_at=datetime.now(timezone.utc))
        )
        await db.commit()

        return AngelOneVerifyResponse(
            success=True,
            profile=profile,
            message="Angel One connection successful",
        )
    except Exception as e:
        log.error("auth.credentials.verify_failed", error=str(e), user_id=str(current_user.id))
        return AngelOneVerifyResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


# ── Trading Config ────────────────────────────────────────────────────────────

@router.get("/config", response_model=TradingConfigResponse)
async def get_trading_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TradingConfig).where(TradingConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Trading config not found")

    return _trading_config_response(config)


@router.patch("/config", response_model=TradingConfigResponse)
async def update_trading_config(
    body: TradingConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update trading configuration.
    Enabling live trading requires active, verified Angel One credentials.
    """
    result = await db.execute(
        select(TradingConfig).where(TradingConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    # Guard: cannot enable live trading without verified credentials
    if body.live_trading_enabled is True:
        creds_result = await db.execute(
            select(APICredentials).where(
                APICredentials.user_id == current_user.id,
                APICredentials.broker == "angel_one",
                APICredentials.is_active == True,
                APICredentials.last_verified_at.isnot(None),
            )
        )
        if not creds_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verify Angel One credentials before enabling live trading",
            )

    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)

    log.info(
        "auth.config.updated",
        user_id=str(current_user.id),
        changes=list(update_data.keys()),
    )
    return _trading_config_response(config)
