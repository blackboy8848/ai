"""
backend/angel_one/registry.py
==============================
Manages per-user AngelOneClient instances.

Why a registry?
- Each user has their own API credentials
- We don't want to re-authenticate on every request
- Clients are cached in memory and reused across requests
- On server restart, clients re-authenticate lazily on first use

Thread-safe via asyncio.Lock per user.
"""

import asyncio
from typing import Dict, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from angel_one.client import AngelOneClient, AngelOneAuthError
from auth.encryption import decrypt
from database.models import APICredentials

log = structlog.get_logger(__name__)


class AngelOneRegistry:
    """
    Singleton registry of authenticated AngelOneClient instances.
    One client per user, lazily initialized and cached.
    """

    def __init__(self):
        self._clients: Dict[str, AngelOneClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(
        self, user_id: UUID, db: AsyncSession
    ) -> AngelOneClient:
        """
        Returns an authenticated client for the given user.
        Creates and caches one if it doesn't exist yet.
        """
        key = str(user_id)

        async with self._lock:
            if key in self._clients:
                client = self._clients[key]
                await client.ensure_authenticated()
                return client

            # Load credentials from DB
            result = await db.execute(
                select(APICredentials).where(
                    APICredentials.user_id == user_id,
                    APICredentials.broker == "angel_one",
                    APICredentials.is_active == True,
                )
            )
            creds = result.scalar_one_or_none()

            if not creds:
                raise AngelOneAuthError(
                    f"No active Angel One credentials for user {user_id}"
                )

            # Decrypt sensitive fields
            client = AngelOneClient(
                api_key=decrypt(creds.encrypted_api_key),
                client_id=decrypt(creds.encrypted_client_id),
                password=decrypt(creds.encrypted_password),
                totp_secret=decrypt(creds.encrypted_totp_secret),
            )

            await client.login()
            self._clients[key] = client
            log.info("angel_one.registry.client_created", user_id=key)
            return client

    async def remove_client(self, user_id: UUID) -> None:
        """Logs out and removes a client (e.g., on credential update)."""
        key = str(user_id)
        async with self._lock:
            client = self._clients.pop(key, None)
            if client:
                await client.logout()
                await client.close()
                log.info("angel_one.registry.client_removed", user_id=key)

    async def shutdown(self) -> None:
        """Close all clients gracefully on app shutdown."""
        async with self._lock:
            for key, client in self._clients.items():
                try:
                    await client.close()
                except Exception as e:
                    log.warning("angel_one.registry.close_error", user_id=key, error=str(e))
            self._clients.clear()
            log.info("angel_one.registry.shutdown")


# Global singleton — imported by FastAPI app and route handlers
angel_registry = AngelOneRegistry()
