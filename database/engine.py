"""
backend/database/engine.py
==========================
Async SQLAlchemy engine, session factory, and base model.
All DB interaction goes through get_db() dependency.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from config.settings import get_settings
import structlog

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Engine ────────────────────────────────────────────────────────────────────
# pool_size / max_overflow tuned for a single VPS; scale up for multi-worker
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,                  # logs every SQL query in debug mode
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,                   # reconnect on stale connections
    pool_recycle=3600,                    # recycle connections every hour
)

# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,               # keep objects usable after commit
    autocommit=False,
    autoflush=False,
)


# ── Declarative base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    Yields an async DB session per request.

    Usage in route:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Startup / shutdown helpers ────────────────────────────────────────────────
async def init_db() -> None:
    """Create all tables. Called at app startup."""
    async with engine.begin() as conn:
        # Import all models so Base knows about them before create_all
        from database import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    log.info("database.initialized")


async def close_db() -> None:
    """Dispose the connection pool. Called at app shutdown."""
    await engine.dispose()
    log.info("database.closed")
