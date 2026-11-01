"""
Unit tests for Language Parity SLO Service and API endpoints.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    EventDocumentModel,
    EventModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork
from ai_security_monitor.presentation.api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.parity_report import run_report


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


@pytest.mark.asyncio
async def test_compute_event_parity_and_slo(test_uow: UnitOfWork):
    session = test_uow.session
    now = datetime.now(UTC)
    service = LanguageParityService()

    # Create dummy source
    src = SourceModel(
        id=str(uuid4()),
        name="Test Lab Source",
        category="frontier_models",
        type="hf_org",
        url="https://example.com/org",
        rate_limit_seconds=3600,
        enabled=True,
    )
    session.add(src)
    await session.flush()

    # Create native ZH doc published earlier (2h lead)
    doc_zh = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="深度求索正式发布DeepSeek-V3大模型，671B参数性能卓越。",
        lang="zh",
        lang_confidence=0.98,
        script="Hans",
        published_at=now - timedelta(hours=5),
        fetched_at=now - timedelta(hours=4),
        content_hash="event_test_hash_zh",
    )
    # Create English doc published later
    doc_en = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="DeepSeek releases DeepSeek-V3 open weights model architecture.",
        lang="en",
        lang_confidence=0.99,
        script="Latn",
        published_at=now - timedelta(hours=3),
        fetched_at=now - timedelta(hours=2),
        content_hash="event_test_hash_en",
    )
    session.add_all([doc_zh, doc_en])
    await session.flush()

    # Create EventModel
    ev = EventModel(
        id=str(uuid4()),
        type="model_release",
        title="DeepSeek-V3 Model Release",
        canonical_entity_ids=["lab:deepseek", "model:deepseek-v3"],
        first_seen_at=now - timedelta(hours=5),
        first_seen_lang="zh",
        first_source_id=src.id,
        status="active",
    )
    session.add(ev)
    await session.flush()

    # Link event documents
    ed_zh = EventDocumentModel(
        id=str(uuid4()),
        event_id=ev.id,
        doc_id=doc_zh.id,
        role="primary",
        linked_at=now - timedelta(hours=5),
    )
    ed_en = EventDocumentModel(
        id=str(uuid4()),
        event_id=ev.id,
        doc_id=doc_en.id,
        role="corroborating",
        linked_at=now - timedelta(hours=3),
    )
    session.add_all([ed_zh, ed_en])
    await session.commit()

    # Compute event parity
    cutoff = now - timedelta(days=7)
    ep = await service.compute_event_parity(session, cutoff)
    assert ep is not None
    assert ep.total_events == 1
    assert ep.bilingual_events_count == 1
    assert ep.zh_origin_events_count == 1
    assert ep.zh_lead_count == 1
    assert ep.en_lead_count == 0
    assert ep.median_cross_lingual_lead_h == 2.0
    assert ep.frontier_lab_events_count == 1
    assert ep.frontier_lab_zh_capture_pct == 100.0

    # Test full parity metrics integration
    metrics = await service.compute_parity_metrics(session, days=7)
    assert metrics.event_parity is not None
    assert metrics.event_parity.bilingual_events_count == 1

    # Test markdown report generation
    report = service.format_markdown_report(metrics)
    assert "Cross-Lingual Event Parity & Discovery Lead" in report
    assert "Canonical Events (14d)" in report
    assert "ZH led: 1" in report

    # Test CLI check-slo execution
    code = await run_report(
        days=7, save_snapshot=False, output_json=False, check_slo=True, uow=test_uow
    )
    assert code == 0


@pytest.mark.asyncio
async def test_cli_slo_check_violation(test_uow: UnitOfWork):
    session = test_uow.session
    now = datetime.now(UTC)

    # Insert only English entry / document
    src = SourceModel(
        id=str(uuid4()),
        name="Only English Source",
        category="general",
        type="rss",
        url="https://example.com/en_rss",
        rate_limit_seconds=3600,
        enabled=True,
    )
    session.add(src)
    await session.flush()

    doc_en = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="Only english content here.",
        lang="en",
        lang_confidence=0.99,
        script="Latn",
        published_at=now - timedelta(hours=1),
        fetched_at=now,
        content_hash="en_only_hash",
    )
    session.add(doc_en)
    await session.commit()

    code = await run_report(
        days=7, save_snapshot=False, output_json=False, check_slo=True, uow=test_uow
    )
    assert code == 1
