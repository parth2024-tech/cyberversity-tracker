"""
Unit tests for DerivedViewService and translate-last event endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.cross_lingual_event_service import (
    CrossLingualEventService,
)
from ai_security_monitor.application.services.derived_view_service import (
    DerivedViewService,
)
from ai_security_monitor.infrastructure.database.models import (
    ClaimModel,
    DocumentModel,
    MentionModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork
from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_generate_event_summary(test_uow: UnitOfWork) -> None:
    session = test_uow.session
    event_service = CrossLingualEventService(time_window_hours=72)
    view_service = DerivedViewService()
    now = datetime.now(UTC)

    # 1. Primary Chinese document
    src_zh = SourceModel(
        id=str(uuid4()),
        name=f"DeepSeek Lab HF {uuid4().hex[:6]}",
        category="ai_research",
        type="huggingface_china",
        enabled=True,
    )
    session.add(src_zh)
    await session.flush()

    doc_zh = DocumentModel(
        id=str(uuid4()),
        source_id=src_zh.id,
        original_text="深度求索正式开源DeepSeek-V3模型，拥有6710亿参数与128k长文本窗口，采用MIT协议。",
        lang="zh",
        script="Hans",
        published_at=now - timedelta(hours=3),
        fetched_at=now - timedelta(hours=2),
        content_hash=uuid4().hex,
    )
    session.add(doc_zh)
    await session.flush()

    m_zh = MentionModel(
        id=str(uuid4()),
        doc_id=doc_zh.id,
        entity_id="model:deepseek_v3",
        span_start=6,
        span_end=17,
        linker_version="v1.0",
    )
    session.add(m_zh)
    await session.flush()

    event = await event_service.cluster_document(session, doc_zh, source=src_zh)
    await session.flush()

    # Add benchmark claim
    b_claim = ClaimModel(
        id=str(uuid4()),
        event_id=event.id,
        doc_id=doc_zh.id,
        field="benchmark_score",
        normalized_value="SWE-bench: 49.2%",
        unit="%",
        evidence_span_start=0,
        evidence_span_end=15,
        evidence_text="SWE-bench: 49.2%",
        confidence=0.95,
        created_at=now,
    )
    session.add(b_claim)
    await session.flush()

    # 2. Test English summary synthesis
    en_summary = await view_service.generate_event_summary(session, event.id, lang="en")
    assert en_summary is not None
    assert en_summary["event_id"] == event.id
    assert en_summary["language"] == "en"
    assert "deepseek-v3" in en_summary["title"].lower()
    assert len(en_summary["key_specifications"]) >= 1
    assert any("671B" in s for s in en_summary["key_specifications"])
    assert len(en_summary["benchmarks"]) == 1
    assert en_summary["benchmarks"][0]["score"] == "49.2%"

    # 3. Test Chinese summary synthesis
    zh_summary = await view_service.generate_event_summary(session, event.id, lang="zh")
    assert zh_summary is not None
    assert zh_summary["language"] == "zh"
    assert "deepseek-v3" in zh_summary["summary_text"].lower()


@pytest.mark.asyncio
async def test_lazy_document_translation_and_caching(test_uow: UnitOfWork) -> None:
    session = test_uow.session
    view_service = DerivedViewService()
    now = datetime.now(UTC)

    src = SourceModel(
        id=str(uuid4()),
        name=f"Zhipu AI HF {uuid4().hex[:6]}",
        category="ai_research",
        type="huggingface_china",
        enabled=True,
    )
    session.add(src)
    await session.flush()

    doc = DocumentModel(
        id=str(uuid4()),
        source_id=src.id,
        original_text="智谱AI发布新一代开源大模型GLM-4。",
        lang="zh",
        script="Hans",
        published_at=now,
        fetched_at=now,
        content_hash=uuid4().hex,
    )
    session.add(doc)
    await session.flush()

    # 1. On-demand translation to English
    view1 = await view_service.get_or_create_document_translation(
        session, doc.id, target_lang="en"
    )
    assert view1 is not None
    assert view1.doc_id == doc.id
    assert view1.view_type == "mt_en"
    assert len(view1.text) > 0

    # 2. Second call must return identical cached view
    view2 = await view_service.get_or_create_document_translation(
        session, doc.id, target_lang="en"
    )
    assert view2 is not None
    assert view2.id == view1.id

    # 3. Target language identical to source returns identity view
    id_view = await view_service.get_or_create_document_translation(
        session, doc.id, target_lang="zh"
    )
    assert id_view is not None
    assert id_view.producer == "identity"
    assert id_view.text == doc.original_text


@pytest.mark.asyncio
async def test_events_summary_and_translation_api_endpoints() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fetch an existing event
        res = await client.get("/api/v1/events?limit=1")
        assert res.status_code == 200
        events = res.json()["events"]
        if events:
            event_id = events[0]["id"]
            # Test GET /api/v1/events/{id}/summary
            sum_res = await client.get(f"/api/v1/events/{event_id}/summary?lang=en")
            assert sum_res.status_code == 200
            sum_data = sum_res.json()
            assert sum_data["event_id"] == event_id
            assert "summary_text" in sum_data
