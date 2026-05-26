"""
backend/auth/dependencies.py
============================
FastAPI dependencies for protected routes.

Usage:
    @router.get("/me")
    async def me(current_user: User = Depends(get_current_user)):
        ...
"""

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import decode_access_token
from database.engine import get_db
from database.models import User

log = structlog.get_logger(__name__)
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validates the Bearer JWT and returns the User ORM object.
    Raises 401 on any auth failure — never leaks the reason to the client.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError as e:
        log.warning("jwt.validation_failed", error=str(e))
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    return user


async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Additional guard for admin-only endpoints."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return current_user
