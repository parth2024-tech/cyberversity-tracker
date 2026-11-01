"""
Unit tests for Native Document Ingestion and Entity Linking Service.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ai_security_monitor.application.services.native_document_ingestion_service import (
    NativeDocumentIngestionService,
    native_document_ingestion_service,
)
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.database.models import (
    CanonicalEntityModel,
    DocumentViewModel,
    EntityAliasModel,
    EntryEntityModel,
    EntryModel,
    MentionModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork


def test_extract_mentions_english():
    service = NativeDocumentIngestionService()
    text = "DeepSeek-V3 and Qwen2.5 demonstrate strong reasoning benchmarks on GSM8K using vLLM."
    mentions = service.extract_mentions(text)

    # Check extracted canonical entities
    canonical_ids = [m[2] for m in mentions]
    assert "model:deepseek_v3" in canonical_ids
    assert "model:qwen_2_5" in canonical_ids

    # Check span character offsets match the text
    for start, end, cid, conf in mentions:
        snippet = text[start:end]
        assert len(snippet) > 0


def test_extract_mentions_chinese_without_word_boundaries():
    service = NativeDocumentIngestionService()
    text = "深度求索团队正式发布DeepSeek-R1推理模型，同时阿里通义千问也开源了Qwen2.5-Coder。"
    mentions = service.extract_mentions(text)

    canonical_ids = [m[2] for m in mentions]
    assert "lab:deepseek" in canonical_ids  # 深度求索
    assert "model:deepseek_r1" in canonical_ids  # DeepSeek-R1
    assert "lab:qwen" in canonical_ids  # 通义千问


def test_extract_mentions_longest_span_suppression():
    service = NativeDocumentIngestionService()
    # "DeepSeek-V3" should take precedence over "DeepSeek"
    text = "DeepSeek-V3 is an open-weight foundation model by DeepSeek."
    mentions = service.extract_mentions(text)

    # First occurrence should be model:deepseek_v3, second should be lab:deepseek
    matched_ids = [m[2] for m in mentions]
    assert matched_ids[0] == "model:deepseek_v3"
    assert matched_ids[1] == "lab:deepseek"


@pytest.mark.asyncio
async def test_seed_canonical_entities(test_uow: UnitOfWork):
    session = test_uow.session
    service = NativeDocumentIngestionService()

    count = await service.seed_canonical_entities(session)
    assert count >= 15

    # Verify entities are in the database
    stmt = select(CanonicalEntityModel).where(
        CanonicalEntityModel.canonical_id == "lab:deepseek"
    )
    deepseek = (await session.execute(stmt)).scalar_one_or_none()
    assert deepseek is not None
    assert deepseek.canonical_name == "DeepSeek"

    # Verify aliases are in the database
    alias_stmt = select(EntityAliasModel).where(
        EntityAliasModel.entity_id == "lab:deepseek"
    )
    aliases = (await session.execute(alias_stmt)).scalars().all()
    alias_texts = {a.alias for a in aliases}
    assert "深度求索" in alias_texts
    assert "deepseek-ai" in alias_texts

    # Re-seeding should be idempotent (0 new entities)
    re_count = await service.seed_canonical_entities(session)
    assert re_count == 0


@pytest.mark.asyncio
async def test_ingest_entry_creates_document_and_mentions(test_uow: UnitOfWork):
    session = test_uow.session
    now = datetime.now(UTC)

    # 1. Seed entities first
    await native_document_ingestion_service.seed_canonical_entities(session)

    # 2. Create source and entry
    src = SourceModel(
        id=str(uuid4()),
        name="Test Lab Ingest Source",
        category="ai_models",
        type="rss",
        url="https://example.com/rss",
        rate_limit_seconds=3600,
        enabled=True,
    )
    session.add(src)
    await session.flush()

    e = EntryModel(
        id=str(uuid4()),
        source_id=src.id,
        title="深度求索发布全新推理模型 DeepSeek-R1",
        url="https://example.com/deepseek-r1-launch",
        content_hash="hash_native_doc_test",
        summary="深度求索团队通过纯强化学习训练了具备自我反思与验证能力的推理大模型。",
        published_at=now - timedelta(hours=3),
        fetched_at=now,
        category="ai_models",
    )
    session.add(e)
    await session.flush()

    # 3. Ingest entry
    doc = await native_document_ingestion_service.ingest_entry(
        session, entry=e, source_id=src.id
    )
    await session.commit()

    assert doc.id is not None
    assert doc.lang == "zh"
    assert doc.script == "Hans"
    assert doc.entry_id == e.id

    # 4. Verify original view was created
    view_stmt = select(DocumentViewModel).where(DocumentViewModel.doc_id == doc.id)
    views = (await session.execute(view_stmt)).scalars().all()
    assert len(views) == 1
    assert views[0].view_type == "original"
    assert views[0].producer == "ingest_raw"

    # 5. Verify mentions were extracted and linked
    mention_stmt = select(MentionModel).where(MentionModel.doc_id == doc.id)
    mentions = (await session.execute(mention_stmt)).scalars().all()
    mention_ids = {m.entity_id for m in mentions}
    assert "lab:deepseek" in mention_ids
    assert "model:deepseek_r1" in mention_ids

    # 6. Verify entry_entities table was also populated for backward compatibility
    ent_stmt = select(EntryEntityModel).where(EntryEntityModel.entry_id == e.id)
    entry_entities = (await session.execute(ent_stmt)).scalars().all()
    assert len(entry_entities) >= 2


@pytest.mark.asyncio
async def test_ingest_entry_deduplication(test_uow: UnitOfWork):
    session = test_uow.session
    src_id = str(uuid4())

    entry = Entry(
        id=uuid4(),
        source_id=UUID(src_id),
        title="Claude 3.5 Sonnet Artifacts and Coding Architecture",
        url="https://example.com/claude-35",
        content_hash="hash_dedup_test",
        summary="Anthropic details safety evals and reasoning improvements.",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )

    doc1 = await native_document_ingestion_service.ingest_entry(
        session, entry=entry, source_id=src_id
    )
    await session.commit()

    # Ingesting same entry again should return existing doc without duplicating
    doc2 = await native_document_ingestion_service.ingest_entry(
        session, entry=entry, source_id=src_id
    )
    assert doc1.id == doc2.id
