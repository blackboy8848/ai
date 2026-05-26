"""
backend/auth/jwt.py
===================
JWT access + refresh token logic.

Access token  — short-lived (60 min), stateless, sent in Authorization header
Refresh token — long-lived (7 days), hash stored in DB for revocation support
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import structlog
from jose import JWTError, jwt

from config.settings import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Password hashing (bcrypt directly — passlib breaks on bcrypt 5.x) ───────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Token generation ──────────────────────────────────────────────────────────
def create_access_token(user_id: str, email: str) -> str:
    """
    Creates a signed JWT access token.
    Payload includes: sub (user_id), email, exp, iat, jti (unique token id)
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4()),   # unique id — useful for token blocklists
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """
    Creates a refresh token.
    Returns (raw_token, hashed_token).
    Store only the hash in the DB; send the raw token to the client.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
        "jti": jti,
        "type": "refresh",
    }
    raw = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def decode_access_token(token: str) -> dict:
    """
    Decodes and validates an access token.
    Raises JWTError on any validation failure.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise JWTError("Not an access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decodes and validates a refresh token."""
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "refresh":
        raise JWTError("Not a refresh token")
    return payload


def hash_token(raw_token: str) -> str:
    """SHA-256 hash of a token string for DB storage/lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()
