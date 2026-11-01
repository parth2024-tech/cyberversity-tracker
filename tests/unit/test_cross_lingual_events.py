"""
Unit tests for CrossLingualEventService and /api/v1/events endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.cross_lingual_event_service import (
    CrossLingualEventService,
    determine_evidentiary_role,
)
from ai_security_monitor.infrastructure.database.models import (
    DocumentModel,
    MentionModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork
from ai_security_monitor.presentation.api.main import create_app


def test_determine_evidentiary_role() -> None:
    assert (
        determine_evidentiary_role(
            "huggingface_china",
            "Hugging Face China Labs",
            "https://huggingface.co/deepseek-ai",
        )
        == "primary"
    )
    assert (
        determine_evidentiary_role(
            "github_releases",
            "DeepSeek-V3 Official",
            "https://github.com/deepseek-ai/DeepSeek-V3",
        )
        == "primary"
    )
    assert (
        determine_evidentiary_role(
            "rss", "South China Morning Post AI", "https://scmp.com/tech"
        )
        == "corroborating"
    )
    assert (
        determine_evidentiary_role(
            "rss", "Reddit Machine Learning", "https://reddit.com/r/MachineLearning"
        )
        == "derivative"
    )


@pytest.mark.asyncio
async def test_cross_lingual_event_clustering(test_uow: UnitOfWork) -> None:
    service = CrossLingualEventService(time_window_hours=72)
    session = test_uow.session
    now = datetime.now(UTC)

    # 1. Create primary Chinese source & document
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
        original_text="深度求索正式开源DeepSeek-V3模型，拥有6710亿参数，采用MIT协议。",
        lang="zh",
        script="Hans",
        published_at=now - timedelta(hours=5),
        fetched_at=now - timedelta(hours=4),
        content_hash=uuid4().hex,
    )
    session.add(doc_zh)
    await session.flush()

    # Link canonical mention
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

    # Cluster doc_zh -> creates new event
    event = await service.cluster_document(session, doc_zh, source=src_zh)
    await session.flush()

    assert event is not None
    assert "model:deepseek_v3" in event.canonical_entity_ids
    assert event.first_seen_lang == "zh"

    # 2. Create corroborating English tech media document (published 4 hours later)
    src_en = SourceModel(
        id=str(uuid4()),
        name=f"Pandaily Tech {uuid4().hex[:6]}",
        category="tech_media",
        type="rss",
        enabled=True,
    )
    session.add(src_en)
    await session.flush()

    doc_en = DocumentModel(
        id=str(uuid4()),
        source_id=src_en.id,
        original_text="DeepSeek announces DeepSeek-V3 open weights with 671B parameters.",
        lang="en",
        script=None,
        published_at=now - timedelta(hours=1),
        fetched_at=now,
        content_hash=uuid4().hex,
    )
    session.add(doc_en)
    await session.flush()

    m_en = MentionModel(
        id=str(uuid4()),
        doc_id=doc_en.id,
        entity_id="model:deepseek_v3",
        span_start=19,
        span_end=30,
        linker_version="v1.0",
    )
    session.add(m_en)
    await session.flush()

    # Cluster doc_en -> links to SAME event!
    linked_event = await service.cluster_document(session, doc_en, source=src_en)
    await session.flush()

    assert linked_event.id == event.id

    # 3. Verify event dossier
    dossier = await service.get_event_dossier(session, event.id)
    assert dossier is not None
    assert dossier["documents_count"] == 2
    assert set(dossier["languages_covered"]) == {"zh", "en"}
    assert dossier["cross_lingual_parity"]["bilingual"] is True
    assert dossier["cross_lingual_parity"]["leader_lang"] == "zh"
    assert dossier["cross_lingual_parity"]["latency_delta_hours"] == 4.0

    assert len(dossier["documents_by_role"]["primary"]) == 1
    assert len(dossier["documents_by_role"]["corroborating"]) == 1

    # Verify extracted claims
    claim_fields = [c["field"] for c in dossier["claims"]]
    assert "params" in claim_fields
    param_vals = [
        c["normalized_value"] for c in dossier["claims"] if c["field"] == "params"
    ]
    assert "671B" in param_vals


@pytest.mark.asyncio
async def test_events_api_endpoints() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /api/v1/events
        res = await client.get("/api/v1/events?limit=10")
        assert res.status_code == 200
        data = res.json()
        assert "events" in data
        assert "total" in data

        # POST /api/v1/events/cluster
        cluster_res = await client.post("/api/v1/events/cluster?limit=10")
        assert cluster_res.status_code == 200
        assert cluster_res.json()["status"] == "success"
