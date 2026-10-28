"""Unit tests for the batch analysis endpoint."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.routers.analysis import analysis_router

app = FastAPI()
app.include_router(analysis_router, prefix="/api")


@pytest.fixture(autouse=True)
async def init_test_db():
    await db_manager.init_db()
    yield
    await db_manager.close()


@pytest.mark.asyncio
async def test_run_batch_analysis_processes_unanalyzed_entries():
    """Verify that /api/analysis/run-batch analyzes unanalyzed entries and persists results."""
    src_id = uuid.uuid4()
    entry_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    async with SqlAlchemyUnitOfWork() as uow:
        src = Source(
            id=src_id,
            name=f"Batch Analysis Test Source {src_id}",
            url=f"https://test.batch.org/feed-{src_id}",
            type=SourceType.RSS,
            category=Category.AI_RESEARCH,
        )
        await uow.sources.add(src)

        for i, eid in enumerate(entry_ids):
            entry = Entry(
                id=eid,
                source_id=src_id,
                title=f"Unanalyzed Test Paper #{i}: Scaling Laws with vLLM",
                url=f"https://test.batch.org/paper-{eid}",
                content_hash=f"hash_batch_{eid}",
                summary=f"Summary of test breakthrough {i} evaluating inference speed and memory scaling.",
                category=Category.AI_RESEARCH,
                published_at=datetime.now(UTC),
            )
            await uow.entries.add(entry)
        await uow.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # First call: should analyze all 3 entries
        res1 = await ac.post("/api/analysis/run-batch?limit=10")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "success"
        assert data1["analyzed_count"] >= 3

        # Verify analyses now exist in DB
        async with SqlAlchemyUnitOfWork() as uow:
            for eid in entry_ids:
                analysis = await uow.analyses.get(eid)
                assert analysis is not None
                assert analysis.entry_id == eid
                assert analysis.severity_index >= 0
                assert analysis.threat_velocity >= 0

        # Subsequent call with limit=3 succeeds
        res2 = await ac.post("/api/analysis/run-batch?limit=3")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "success"
        assert isinstance(data2["analyzed_count"], int)
