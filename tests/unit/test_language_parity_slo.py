"""
Unit tests for Language Parity SLO Service and API endpoints.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.language_parity_service import (
    LanguageParityMetrics,
    LanguageParityService,
    language_parity_service,
)
from ai_security_monitor.infrastructure.database.models import (
    DocumentModel,
    EntryModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork
from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_compute_parity_metrics_baseline_with_entries(
    test_uow: UnitOfWork,
):
    service = LanguageParityService(target_latency_ratio=1.25)
    now = datetime.now(UTC)
    session = test_uow.session

    # Create dummy source
    src = SourceModel(
        id=str(uuid4()),
        name="Test English Source",
        category="ai_tech",
        type="rss",
        url="https://example.com/rss",
        rate_limit_seconds=3600,
        enabled=True,
    )
    session.add(src)
    await session.flush()

    # Add 2 English entries
    e1 = EntryModel(
        id=str(uuid4()),
        source_id=src.id,
        title="New Open Source Agent Framework Released",
        url="https://example.com/1",
        content_hash="hash_en_1",
        summary="Developers release a fast agent runtime with tool use.",
        published_at=now - timedelta(hours=4),
        fetched_at=now - timedelta(hours=2),  # 2 hours latency
        category="ai_tech",
    )
    e2 = EntryModel(
        id=str(uuid4()),
        source_id=src.id,
        title="High-performance Inference Scaling for Reasoning Models",
        url="https://example.com/2",
        content_hash="hash_en_2",
        summary="Inference framework optimizes memory bandwidth for LLM generation.",
        published_at=now - timedelta(hours=6),
        fetched_at=now - timedelta(hours=2),  # 4 hours latency
        category="ai_tech",
    )
    session.add_all([e1, e2])
    await session.commit()

    metrics = await service.compute_parity_metrics(session, days=7)
    assert metrics.en_count >= 2
    assert metrics.data_source == "entries (baseline)"
    assert metrics.en_median_latency_h > 0
    assert metrics.slo_latency_met is False  # ZH count is 0, so not met


@pytest.mark.asyncio
async def test_compute_parity_metrics_with_native_documents(
    test_uow: UnitOfWork,
):
    service = LanguageParityService(target_latency_ratio=1.25)
    now = datetime.now(UTC)
    session = test_uow.session

    src = SourceModel(
        id=str(uuid4()),
        name="Test Native Multilingual Source",
        category="ai_models",
        type="rss",
        url="https://example.com/native_rss",
        rate_limit_seconds=3600,
        enabled=True,
    )
    session.add(src)
    await session.flush()

    # Add 1 native Chinese document and 1 English document
    doc_zh = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="深度求索开源全新推理大模型，显著提高数学与代码推理性能。",
        lang="zh",
        lang_confidence=0.95,
        script="Hans",
        published_at=now - timedelta(hours=2),
        fetched_at=now - timedelta(hours=1),  # 1 hour latency
        content_hash="hash_doc_zh_1",
    )
    doc_en = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="Anthropic publishes research on alignment and mechanistic interpretability.",
        lang="en",
        lang_confidence=0.98,
        script="Latn",
        published_at=now - timedelta(hours=2),
        fetched_at=now - timedelta(hours=1),  # 1 hour latency
        content_hash="hash_doc_en_1",
    )
    session.add_all([doc_zh, doc_en])
    await session.commit()

    metrics = await service.compute_parity_metrics(session, days=7)
    assert metrics.data_source == "documents"
    assert metrics.zh_count >= 1
    assert metrics.en_count >= 1
    assert metrics.slo_capture_active is True
    assert metrics.latency_ratio <= 1.25
    assert metrics.slo_latency_met is True


@pytest.mark.asyncio
async def test_record_snapshot_and_markdown_report(test_uow: UnitOfWork):
    session = test_uow.session
    now = datetime.now(UTC)
    metrics = LanguageParityMetrics(
        timestamp=now,
        period_days=7,
        data_source="documents",
        zh_count=10,
        en_count=20,
        other_count=2,
        total_count=32,
        capture_rate_ratio=0.5,
        zh_share_pct=31.25,
        zh_median_latency_h=1.2,
        zh_p90_latency_h=2.5,
        en_median_latency_h=1.0,
        en_p90_latency_h=2.0,
        latency_ratio=1.2,
        slo_latency_met=True,
        slo_capture_active=True,
        sources=[],
    )

    snapshot = await language_parity_service.record_snapshot(session, metrics)
    assert snapshot.id is not None
    assert snapshot.zh_count_7d == 10
    assert snapshot.en_count_7d == 20
    assert snapshot.capture_rate_ratio == 0.5

    report_md = language_parity_service.format_markdown_report(metrics)
    assert "Multilingual Language-Parity SLO Report" in report_md
    assert "🟢 COMPLIANT" in report_md
    assert "🟢 ACTIVE" in report_md


@pytest.mark.asyncio
async def test_parity_api_endpoints():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /api/parity/metrics
        resp = await client.get("/api/parity/metrics?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "zh_count" in data
        assert "en_count" in data
        assert "latency_ratio" in data
        assert "slo_latency_met" in data

        # GET /api/parity/report
        resp_rep = await client.get("/api/parity/report?days=7")
        assert resp_rep.status_code == 200
        rep_data = resp_rep.json()
        assert "markdown" in rep_data
        assert "period_days" in rep_data
        assert "data_source" in rep_data
