"""
Pytest configuration and global fixtures.
"""

from __future__ import annotations

import os

# Guarantee that automated test sessions use an isolated throwaway SQLite DB
# and never mutate a developer's real local database or production state.
# Hard-assigned (not setdefault) so shell environment cannot override to ./data.
os.environ["DATA_DIR"] = "/tmp/aetherguard_test_data"
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork


def pytest_sessionstart(session: pytest.Session) -> None:
    """Ensure database tables exist and initial sources are seeded before running test session."""
    import asyncio
    import os

    # Wipe stale test database file to guarantee a fresh state on each test session run
    data_dir = os.environ.get("DATA_DIR")
    assert data_dir and (data_dir.startswith("/tmp") or "test" in data_dir), (
        f"CRITICAL SAFETY HAZARD: Test DATA_DIR '{data_dir}' is not isolated in /tmp!"
    )

    # Assert on the actual resolved SQLAlchemy engine URL to guard against .env or DATABASE_URL escapes
    resolved_db_url = str(db_manager.engine.url).lower()
    import pathlib

    dev_db_path = str(
        pathlib.Path(__file__).resolve().parent.parent / "data" / "monitor.db"
    ).lower()
    assert dev_db_path not in resolved_db_url and not resolved_db_url.endswith(
        "/ai-security-monitor/data/monitor.db"
    ), (
        f"CRITICAL SAFETY HAZARD: Test database engine resolved directly to production/dev DB: '{resolved_db_url}'"
    )
    assert "/tmp/" in resolved_db_url or "test" in resolved_db_url, (
        f"CRITICAL SAFETY HAZARD: Test database engine '{resolved_db_url}' is not isolated in /tmp!"
    )

    if os.path.exists(data_dir):
        db_file = os.path.join(data_dir, "monitor.db")
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except OSError:
                pass

    from ai_security_monitor.application.services.monitor_service import MonitorService

    async def _init_clean_db() -> None:
        await db_manager.init_db()
        monitor_service = MonitorService()
        await monitor_service.init_sources()
        await db_manager.close()

    asyncio.run(_init_clean_db())


@pytest_asyncio.fixture
async def test_db_engine():
    """Create in-memory SQLite engine for fast testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_uow(test_db_engine):
    """Provide isolated UnitOfWork for unit tests."""
    session_factory = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    session = session_factory()
    uow = UnitOfWork(session=session)
    yield uow
    await session.close()


@pytest.fixture
def sample_source() -> Source:
    return Source(
        id=uuid4(),
        name="Test arXiv Feed",
        category=Category.AI_RESEARCH,
        type=SourceType.ARXIV,
        url="http://export.arxiv.org/api/query",
        query="cat:cs.CR",
        rate_limit_seconds=10,
        enabled=True,
    )


@pytest.fixture
def sample_entry(sample_source: Source) -> Entry:
    return Entry(
        id=uuid4(),
        source_id=sample_source.id,
        title="Zero-Day Jailbreak Attack on Frontier Vision-Language Models",
        url="https://arxiv.org/abs/2401.00001",
        content_hash="a" * 64,
        summary="Novel adversarial prompt injection and jailbreak vector exploiting multimodal alignment.",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
        tags=["jailbreak", "llm", "adversarial"],
    )
