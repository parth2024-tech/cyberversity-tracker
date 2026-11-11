"""Unit tests for Intent-Weighted RRF Hybrid Search, BEFORE DELETE Cascades, and Global JSON Exception Boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.database.connection import DatabaseManager
from ai_security_monitor.infrastructure.database.models import (
    AnalysisEvidenceModel,
    AnalysisOutcomeModel,
    CouncilReviewModel,
    DocumentModel,
    EntryEntityModel,
    ReceiptModel,
)
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyAnalysisRepository,
    SQLAlchemyEntryRepository,
    SQLAlchemySourceRepository,
)
from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_search_hybrid_technical_lexical_floor_boost(tmp_path):
    """Test Intent-Weighted RRF: Exact technical tokens (e.g. vLLM v0.6.3, llama.cpp) rank top via FTS lexical floor boost."""
    test_db = tmp_path / "test_hybrid_tech.db"
    db_url = f"sqlite+aiosqlite:///{test_db}"
    mgr = DatabaseManager(url=db_url)
    await mgr.init_db()

    source = Source(
        name="Tech Feed",
        category=Category.AI_MODELS,
        type=SourceType.RSS,
    )
    async with mgr.session() as session:
        src_repo = SQLAlchemySourceRepository(session)
        await src_repo.add(source)
        await session.commit()

        entry_repo = SQLAlchemyEntryRepository(session)

        # Entry A: Technical match with exact version tag
        entry_a = Entry(
            source_id=source.id,
            title="vLLM v0.6.3 Engine Optimization",
            url="https://github.com/vllm/releases/tag/v0.6.3",
            summary="New chunked prefill engine with llama.cpp runtime optimizations.",
            content_hash="tech_hash_001",
            category=Category.AI_MODELS,
            published_at=datetime.now(UTC) - timedelta(days=1),
        )
        # Entry B: Broad conceptual entry
        entry_b = Entry(
            source_id=source.id,
            title="Future of Foundation Models and Inference Scaling",
            url="https://example.com/future-inference",
            summary="Discussion of scaling inference and system throughput for AI.",
            content_hash="tech_hash_002",
            category=Category.AI_MODELS,
            published_at=datetime.now(UTC) - timedelta(days=2),
        )
        # Entry C: Stale entry (> 14 days old)
        entry_c = Entry(
            source_id=source.id,
            title="vLLM v0.6.3 Historical Archive",
            url="https://example.com/stale-vllm",
            summary="Archived note on vLLM v0.6.3 published last month.",
            content_hash="tech_hash_003",
            category=Category.AI_MODELS,
            published_at=datetime.now(UTC) - timedelta(days=20),
        )

        await entry_repo.add(entry_a)
        await entry_repo.add(entry_b)
        await entry_repo.add(entry_c)
        await session.commit()

        # 1. Search technical query: "vLLM v0.6.3"
        results = await entry_repo.search_hybrid("vLLM v0.6.3", limit=10)
        assert len(results) >= 1
        assert results[0].id == entry_a.id
        # Entry C is > 14 days old and must be excluded by the 14-day freshness window
        assert all(r.id != entry_c.id for r in results)

        # 2. Search by category filter
        cat_results = await entry_repo.search_hybrid(
            "vLLM", limit=10, category=Category.AI_RESEARCH
        )
        assert len(cat_results) == 0  # Entry A is AI_MODELS

        cat_match = await entry_repo.search_hybrid(
            "vLLM", limit=10, category=Category.AI_MODELS
        )
        assert len(cat_match) >= 1
        assert cat_match[0].id == entry_a.id

    await mgr.close()


@pytest.mark.asyncio
async def test_before_delete_and_subquery_cascade_purge(tmp_path):
    """Test BEFORE DELETE triggers and zero-param subquery cascade purge without foreign key errors."""
    test_db = tmp_path / "test_cascade_purge.db"
    db_url = f"sqlite+aiosqlite:///{test_db}"
    mgr = DatabaseManager(url=db_url)
    await mgr.init_db()

    source = Source(
        name="Cascade Source",
        category=Category.AI_MODELS,
        type=SourceType.RSS,
    )
    async with mgr.session() as session:
        src_repo = SQLAlchemySourceRepository(session)
        await src_repo.add(source)
        await session.commit()

        entry_repo = SQLAlchemyEntryRepository(session)
        analysis_repo = SQLAlchemyAnalysisRepository(session)

        # Add 3 entries
        entries = []
        for i in range(3):
            e = Entry(
                source_id=source.id,
                title=f"Scalable Kernel Runtime {i}",
                url=f"https://example.com/kernel-{i}",
                summary=f"Kernel design notes {i}",
                content_hash=f"kernel_hash_{i}",
                category=Category.AI_MODELS,
                published_at=datetime.now(UTC) - timedelta(days=i),
            )
            created_e = await entry_repo.add(e)
            entries.append(created_e)
        await session.commit()

        # Attach child dependencies to entry 0
        target_entry = entries[0]
        analysis = Analysis(
            entry_id=target_entry.id,
            attack_vector="Inference Optimization",
            risk_assessment="High throughput scaling",
            mitigation="Upgrade runtime",
            threat_velocity=50,
            severity_index=20,
            model=AnalysisModel.HEURISTIC,
            confidence=0.95,
        )
        saved_an = await analysis_repo.add(analysis)
        await session.commit()

        # Add related records directly across child tables
        e_str = str(target_entry.id)
        an_str = str(saved_an.id)
        session.add(
            AnalysisEvidenceModel(
                analysis_id=an_str,
                claim_type="fact",
                claim_target="kernel_throughput",
                claim_value="2.5x speedup",
                method="heuristic",
                confidence=0.9,
            )
        )
        session.add(
            AnalysisOutcomeModel(
                analysis_id=an_str,
                outcome_type="confirmed",
                outcome_value="Runtime verified",
            )
        )
        session.add(
            EntryEntityModel(
                entry_id=e_str,
                entity_type="framework",
                name="vllm",
                display_name="vLLM",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            CouncilReviewModel(
                entry_id=e_str,
                status="approved",
                consensus_verdict="APPROVED",
                consensus_score=0.95,
                consensus_summary="Consensus reached",
                persona_evaluations={},
            )
        )
        session.add(
            ReceiptModel(
                id=str(uuid.uuid4()),
                logical_key="test_logical_key_001",
                entry_id=e_str,
                provider="local",
                model="qwen2.5-coder",
                prompt_version="v1",
            )
        )
        session.add(
            DocumentModel(
                source_id=str(source.id),
                entry_id=e_str,
                original_text="Whitepaper text",
                lang="en",
                published_at=datetime.now(UTC),
                content_hash="doc_hash_001",
            )
        )
        await session.commit()

        # Perform zero-parameter subquery hard purge
        purged_count = await entry_repo.purge_old_entries(
            older_than_days=0, hard_delete=True
        )
        assert purged_count == 3
        await session.commit()

        # Verify parent entries and all child rows are completely removed or unlinked
        e_count = (await session.execute(text("SELECT count(*) FROM entries"))).scalar()
        an_count = (
            await session.execute(text("SELECT count(*) FROM entry_analysis"))
        ).scalar()
        ev_count = (
            await session.execute(text("SELECT count(*) FROM analysis_evidence"))
        ).scalar()
        out_count = (
            await session.execute(text("SELECT count(*) FROM analysis_outcome"))
        ).scalar()
        fts_count = (
            await session.execute(text("SELECT count(*) FROM entries_fts"))
        ).scalar()
        doc_linked = (
            await session.execute(
                text("SELECT count(*) FROM documents WHERE entry_id IS NOT NULL")
            )
        ).scalar()

        assert e_count == 0
        assert an_count == 0
        assert ev_count == 0
        assert out_count == 0
        assert fts_count == 0
        assert doc_linked == 0

    await mgr.close()


def test_global_json_500_exception_handler():
    """Verify unhandled 500 exceptions return structured JSON rather than raw text/plain."""
    from unittest.mock import patch

    app = create_app()

    with patch("ai_security_monitor.presentation.api.routers.entries.SqlAlchemyUnitOfWork") as mock_uow:
        mock_uow.side_effect = RuntimeError("Synthetic test explosion for fault boundary verification")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/entries")

        assert resp.status_code == 500
        assert resp.headers.get("content-type", "").startswith("application/json")
        data = resp.json()
        assert data["ok"] is False
        assert data["type"] == "RuntimeError"
        assert "correlation_id" in data
        assert "detail" in data
        assert resp.headers.get("X-Correlation-ID") == data["correlation_id"]


@pytest.mark.asyncio
async def test_delete_entries_by_ids_chunking(tmp_path):
    """Verify delete_entries_by_ids safely batches in chunks of 500 without hitting SQLite variable limits."""
    test_db = tmp_path / "test_chunk_delete.db"
    db_url = f"sqlite+aiosqlite:///{test_db}"
    mgr = DatabaseManager(url=db_url)
    await mgr.init_db()

    source = Source(
        name="Chunk Source",
        category=Category.AI_MODELS,
        type=SourceType.RSS,
    )
    async with mgr.session() as session:
        src_repo = SQLAlchemySourceRepository(session)
        await src_repo.add(source)
        await session.commit()

        entry_repo = SQLAlchemyEntryRepository(session)
        entry_ids = []
        for i in range(550):
            e = Entry(
                source_id=source.id,
                title=f"Chunk Entry {i}",
                url=f"https://example.com/chunk-{i}",
                summary="Chunking verification",
                content_hash=f"chunk_hash_{i:04d}",
                category=Category.AI_MODELS,
                published_at=datetime.now(UTC),
            )
            created = await entry_repo.add(e)
            entry_ids.append(created.id)
        await session.commit()

        # Delete all 550 entries (crosses the 500-chunk threshold)
        deleted_count = await entry_repo.delete_entries_by_ids(entry_ids, hard_delete=True)
        assert deleted_count == 550
        await session.commit()

        remaining = (await session.execute(text("SELECT count(*) FROM entries"))).scalar()
        assert remaining == 0

    await mgr.close()


@pytest.mark.asyncio
async def test_mcp_worldwide_ai_news_search_hybrid(tmp_path):
    """Verify MCP get_worldwide_ai_news tool handles hybrid search parameter."""
    import json
    from unittest.mock import AsyncMock, patch

    from ai_security_monitor.presentation.mcp.server import MCPServer

    mock_entry = Entry(
        source_id=uuid.uuid4(),
        title="vLLM v0.6.3 Engine Release",
        url="https://github.com/vllm/releases/tag/v0.6.3",
        summary="High performance inference engine.",
        content_hash="mock_hash_001",
        category=Category.AI_MODELS,
        published_at=datetime.now(UTC),
    )

    with patch("ai_security_monitor.infrastructure.database.unit_of_work.SqlAlchemyUnitOfWork") as mock_uow_cls:
        mock_uow = AsyncMock()
        mock_uow.entries.search_hybrid.return_value = [mock_entry]
        mock_uow.__aenter__.return_value = mock_uow
        mock_uow.__aexit__.return_value = None
        mock_uow_cls.return_value = mock_uow

        server = MCPServer()
        res_json = await server._execute_tool(
            "get_worldwide_ai_news",
            {"query": "vLLM", "limit": 5, "category": "frontier_models"},
        )
        parsed = json.loads(res_json)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "vLLM v0.6.3 Engine Release"
        assert parsed[0]["category"] == "ai_models"
