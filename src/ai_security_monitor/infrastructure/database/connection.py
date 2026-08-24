"""
Database connection and session management.
Async SQLAlchemy with SQLite (aiosqlite) for zero-cost deployment.
"""

from contextlib import asynccontextmanager
from typing import Optional
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy import event, text

from ai_security_monitor.config.settings import settings


class DatabaseManager:
    """Manages database engine and sessions."""

    def __init__(self, url: Optional[str] = None, echo: Optional[bool] = None):
        self._url = url or settings.database.url
        self._echo = echo if echo is not None else settings.database.echo
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._session_factory

    def _create_engine(self) -> AsyncEngine:
        """Create async engine with appropriate configuration."""
        # For SQLite, use NullPool to avoid connection issues
        if self._url.startswith("sqlite"):
            engine = create_async_engine(
                self._url,
                echo=self._echo,
                poolclass=NullPool,
                connect_args={"check_same_thread": False},
            )
        else:
            engine = create_async_engine(
                self._url,
                echo=self._echo,
                pool_size=settings.database.pool_size,
                max_overflow=settings.database.max_overflow,
            )

        # Enable WAL mode for SQLite
        if self._url.startswith("sqlite"):
            @event.listens_for(engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        return engine

    @asynccontextmanager
    async def session(self) -> AsyncSession:
        """Get a database session with automatic transaction management."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def transaction(self) -> AsyncSession:
        """Explicit transaction context manager."""
        async with self.session() as session:
            async with session.begin():
                yield session

    async def close(self) -> None:
        """Close the engine and all connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def init_db(self) -> None:
        """Initialize database - create tables if they don't exist."""
        from ai_security_monitor.infrastructure.database.models import Base
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


# Global database manager instance
db_manager = DatabaseManager()


async def get_db_session() -> AsyncSession:
    """FastAPI dependency for getting a database session."""
    async with db_manager.session() as session:
        yield session