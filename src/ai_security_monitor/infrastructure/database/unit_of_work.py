"""
Unit of Work pattern for transaction management.
Ensures atomic operations across multiple repositories.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyAnalysisRepository,
    SQLAlchemyDigestRepository,
    SQLAlchemyEntryRepository,
    SQLAlchemyFetchLogRepository,
    SQLAlchemySourceRepository,
    SQLAlchemyWatchlistRepository,
)


class UnitOfWork:
    """
    Unit of Work manages transactions and provides repository access.
    All repositories share the same session for atomic operations.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._owns_session = session is None

        # Repositories (lazy initialized)
        self._entries: SQLAlchemyEntryRepository | None = None
        self._analysis: SQLAlchemyAnalysisRepository | None = None
        self._sources: SQLAlchemySourceRepository | None = None
        self._fetch_logs: SQLAlchemyFetchLogRepository | None = None
        self._digests: SQLAlchemyDigestRepository | None = None
        self._watchlist: SQLAlchemyWatchlistRepository | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork not started. Use async with or call __aenter__")
        return self._session

    @property
    def entries(self) -> SQLAlchemyEntryRepository:
        if self._entries is None:
            self._entries = SQLAlchemyEntryRepository(self.session)
        return self._entries

    @property
    def analysis(self) -> SQLAlchemyAnalysisRepository:
        if self._analysis is None:
            self._analysis = SQLAlchemyAnalysisRepository(self.session)
        return self._analysis

    @property
    def analyses(self) -> SQLAlchemyAnalysisRepository:
        return self.analysis

    @property
    def sources(self) -> SQLAlchemySourceRepository:
        if self._sources is None:
            self._sources = SQLAlchemySourceRepository(self.session)
        return self._sources

    @property
    def fetch_logs(self) -> SQLAlchemyFetchLogRepository:
        if self._fetch_logs is None:
            self._fetch_logs = SQLAlchemyFetchLogRepository(self.session)
        return self._fetch_logs

    @property
    def digests(self) -> SQLAlchemyDigestRepository:
        if self._digests is None:
            self._digests = SQLAlchemyDigestRepository(self.session)
        return self._digests

    @property
    def watchlist(self) -> SQLAlchemyWatchlistRepository:
        if self._watchlist is None:
            self._watchlist = SQLAlchemyWatchlistRepository(self.session)
        return self._watchlist

    async def __aenter__(self) -> "UnitOfWork":
        if self._owns_session:
            self._session = db_manager.session_factory()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        """Commit the transaction."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Rollback the transaction."""
        await self.session.rollback()

    async def flush(self) -> None:
        """Flush pending changes without committing."""
        await self.session.flush()


@asynccontextmanager
async def unit_of_work() -> AsyncGenerator[UnitOfWork, None]:
    """Context manager for UnitOfWork - use in services."""
    uow = UnitOfWork()
    async with uow:
        yield uow


async def get_unit_of_work() -> AsyncGenerator[UnitOfWork, None]:
    """FastAPI dependency for UnitOfWork."""
    async with unit_of_work() as uow:
        yield uow


SqlAlchemyUnitOfWork = UnitOfWork
