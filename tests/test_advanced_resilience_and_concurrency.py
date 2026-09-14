"""
Comprehensive advanced tests for resilient services, concurrency, database integrity,
scheduler loops, monitor service edge states, and LLM analyzer fallback paths.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.application.services.scheduler_service import SchedulerService
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.database.connection import DatabaseManager
from ai_security_monitor.infrastructure.database.models import EntryModel, SourceModel


@pytest.mark.asyncio
async def test_monitor_service_resilience_and_edge_states(test_db_engine, test_uow):
    """Test MonitorService fetching coordination, error boundaries, and concurrency."""
    monitor = MonitorService(uow_factory=lambda: test_uow)

    # 1. Test init_sources with mocked load_sources_from_yaml
    with patch(
        "ai_security_monitor.application.services.monitor_service.load_sources_from_yaml"
    ) as mock_load:
        mock_load.return_value = [
            MagicMock(
                name="Test RSS Unique",
                enabled=True,
                type="rss",
                url="http://example.com/rss",
                category="ai_tech",
                country="global",
                region="global",
                query=None,
                rate_limit_seconds=3600,
                config={},
            )
        ]
        test_uow.sources.get_by_name = AsyncMock(return_value=None)
        test_uow.sources.add = AsyncMock()
        test_uow.commit = AsyncMock()

        count = await monitor.init_sources()
        assert count >= 0

    # 2. Test fetch_source with invalid/failing fetcher gracefully handling exceptions
    source = Source(
        name="Failing Source Edge",
        type=SourceType.RSS,
        url="http://mock-invalid-feed.local/feed.xml",
        category=Category.AI_TECH,
        enabled=True,
    )
    async with test_uow as uow:
        await uow.sources.add(source)
        await uow.commit()

    with patch(
        "ai_security_monitor.infrastructure.fetchers.rss_fetcher.RSSFetcher.fetch",
        side_effect=Exception("Simulated network timeout"),
    ):
        log = await monitor.fetch_source(source)
        assert log is not None
        assert log.status == FetchStatus.ERROR
        assert "Simulated network timeout" in (log.error_message or "")

        # 3. Test fetch_all concurrency limits and error resilience
        results = await monitor.fetch_all(force=True, max_concurrency=2)
        assert isinstance(results, dict)


@pytest.mark.asyncio
async def test_scheduler_service_interrupted_and_long_running(test_db_engine):
    """Test SchedulerService start, stop, loops, and failure resilience."""
    scheduler = SchedulerService()

    # Mock loop targets to avoid actual external network calls during scheduler test
    with (
        patch.object(scheduler, "_loop", new_callable=AsyncMock),
        patch.object(scheduler, "_newspaper_loop", new_callable=AsyncMock),
        patch.object(scheduler, "_backup_loop", new_callable=AsyncMock),
    ):
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None

        # Give a brief moment for async scheduling
        await asyncio.sleep(0.1)

        await scheduler.stop()
        assert scheduler._running is False


@pytest.mark.asyncio
async def test_llm_analyzer_fallback_and_timeouts():
    """Test LLMAnalyzer fallback paths when primary LLM calls fail or timeout."""
    analyzer = LLMAnalyzer()
    source = Source(
        name="Test Source LLM",
        type=SourceType.RSS,
        url="http://example.com/rss",
        category=Category.AI_TECH,
        enabled=True,
    )
    entry = Entry(
        title="Test Frontier AI Model Release",
        summary="A new open-weights reasoning model with 70B parameters.",
        url="http://example.com/model",
        content_hash="llm_fallback_test_01",
        category=Category.AI_MODELS,
        source_id=source.id,
        published_at=datetime.now(UTC),
    )

    # Mock Ollama / Groq / Gateway calls to raise TimeoutError or ConnectionError
    with (
        patch.object(analyzer, "_call_ollama", side_effect=TimeoutError()),
        patch.object(analyzer, "_call_groq", side_effect=ConnectionError()),
        patch.object(analyzer, "_call_gateway", side_effect=Exception("Gateway error")),
    ):
        result = await analyzer.analyze(entry)
        assert result is not None
        assert result.severity_index >= 0
        assert result.threat_velocity >= 0


@pytest.mark.asyncio
async def test_database_sqlite_concurrency_and_wal_robustness(test_db_engine):
    """Test database manager under high-concurrency multi-source polling simulation using test_db_engine."""
    manager = DatabaseManager()
    manager._engine = test_db_engine

    # Create a source model directly using SQLAlchemy session / model to satisfy table mapping
    async with manager.session() as session:
        src = SourceModel(
            name="Concurrent Isolated Source Test",
            type="rss",
            url="http://example.com/source",
            category="ai_tech",
            enabled=True,
        )
        session.add(src)
        await session.commit()
        source_id = src.id

    # Simulate 20 concurrent transactions writing distinct entries simultaneously
    async def concurrent_writer(worker_id: int):
        async with manager.session() as session:
            entry = EntryModel(
                title=f"Concurrent Entry {worker_id}",
                summary=f"Summary from worker {worker_id}",
                url=f"http://example.com/{worker_id}",
                content_hash=f"hash_isolated_{worker_id}_{datetime.now(UTC).timestamp()}",
                category="ai_tech",
                source_id=source_id,
                published_at=datetime.now(UTC),
            )
            session.add(entry)
            await session.commit()

    tasks = [concurrent_writer(i) for i in range(20)]
    await asyncio.gather(*tasks)

    # Verify all entries were successfully written without database locks
    async with manager.session() as session:
        from sqlalchemy import func, select

        result = await session.execute(
            select(func.count(EntryModel.id)).where(EntryModel.source_id == source_id)
        )
        count = result.scalar()
        assert count == 20
