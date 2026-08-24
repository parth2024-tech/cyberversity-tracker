"""
Pytest configuration and global fixtures.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork


@pytest_asyncio.fixture
async def test_db_engine():
    """Create in-memory SQLite engine for fast testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_uow(test_db_engine):
    """Provide isolated UnitOfWork for unit tests."""
    session_factory = async_sessionmaker(test_db_engine, class_=AsyncSession, expire_on_commit=False)
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
        enabled=True
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
        published_at=datetime.utcnow(),
        category=Category.AI_RESEARCH,
        tags=["jailbreak", "llm", "adversarial"]
    )
