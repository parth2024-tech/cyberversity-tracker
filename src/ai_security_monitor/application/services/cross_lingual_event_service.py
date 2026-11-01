"""
Cross-Lingual Event Clustering and Dossier Service.

Core implementation of the Multilingual Event-Intelligence Architecture:
1. Clusters incoming native documents (Chinese & English) into language-independent canonical events.
2. Resolves evidentiary hierarchy: primary (lab repos, HF/ModelScope orgs),
   corroborating (tech media), derivative (social).
3. Extracts and anchors deterministic claims with original character spans.
4. Governs language parity at the event level (bilingual coverage, cross-lingual discovery latency).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_security_monitor.application.services.claim_extraction_service import (
    claim_extractor,
)
from ai_security_monitor.infrastructure.database.models import (
    ClaimModel,
    DocumentModel,
    EventDocumentModel,
    EventModel,
    MentionModel,
    SourceModel,
)

logger = structlog.get_logger(__name__)


def determine_evidentiary_role(
    source_type: str | None, source_name: str | None, url: str | None
) -> str:
    """Classifies source into primary, corroborating, or derivative role."""
    s_name = (source_name or "").lower()
    s_type = (source_type or "").lower()
    s_url = (url or "").lower()

    # Primary: Official lab repos, HF/ModelScope orgs, arXiv preprints, official github
    if (
        "huggingface" in s_type
        or "github" in s_type
        or "arxiv" in s_type
        or "modelscope" in s_name
        or "hugging face" in s_name
        or "official" in s_name
        or "deepseek" in s_name
        or "qwen" in s_name
        or "fudan" in s_name
    ):
        return "primary"

    # Derivative: Reddit, Twitter, community social
    if (
        "reddit" in s_name
        or "reddit" in s_url
        or "twitter" in s_name
        or "x.com" in s_url
        or "social" in s_name
    ):
        return "derivative"

    # Corroborating: Tech media (SCMP, Pandaily, TechNode, HackerNews, QbitAI, etc.)
    return "corroborating"


class CrossLingualEventService:
    """Orchestrates cross-lingual event clustering, claims extraction, and dossier generation."""

    def __init__(self, time_window_hours: int = 72) -> None:
        self.time_window = timedelta(hours=time_window_hours)

    def _extract_version_tag(self, text: str) -> str | None:
        """Extract model or framework version tag from text."""
        # e.g. V3, R1, 2.5, 3.5, 70B, etc.
        m = re.search(
            r"(?<![A-Za-z0-9_])(V\d+(?:\.\d+)?|R\d+|v\d+(?:\.\d+)?|r\d+|\d+\.\d+)(?![A-Za-z0-9_])",
            text,
        )
        if m:
            return m.group(1).upper()
        return None

    def _determine_event_type(self, text: str, entity_ids: list[str]) -> str:
        """Determine canonical event type."""
        t_lower = text.lower()
        if any(
            b in t_lower
            for b in ("benchmark", "aime", "swe-bench", "gsm8k", "mmlu", "基准", "评测")
        ):
            return "benchmark_result"
        if any(
            f in t_lower
            for f in ("framework", "runtime", "vllm", "sglang", "ollama", "llama.cpp")
        ):
            return "framework_update"
        if any("model:" in eid for eid in entity_ids) or any(
            w in t_lower
            for w in ("release", "weights", "checkpoint", "开源", "发布", "模型")
        ):
            return "model_release"
        return "general_intelligence"

    def _synthesize_canonical_title(
        self,
        entity_ids: list[str],
        version_tag: str | None,
        event_type: str,
        fallback_text: str,
    ) -> str:
        """Synthesize a language-independent title for the canonical event."""
        # Prefer model or lab entity
        models = [
            eid.split(":", 1)[1].replace("_", "-").title()
            for eid in entity_ids
            if eid.startswith("model:")
        ]
        labs = [
            eid.split(":", 1)[1].replace("_", "-").title()
            for eid in entity_ids
            if eid.startswith("lab:")
        ]

        subject = ""
        if models:
            subject = models[0]
        elif labs:
            subject = labs[0]
            if version_tag:
                subject = f"{subject}-{version_tag}"
        else:
            # Fallback to first line or snippet of text
            first_line = fallback_text.strip().split("\n")[0][:60].strip()
            return first_line if first_line else "AI Intelligence Event"

        type_map = {
            "model_release": "Model Release",
            "benchmark_result": "Benchmark Evaluation",
            "framework_update": "Framework Update",
            "general_intelligence": "Intelligence Brief",
        }
        suffix = type_map.get(event_type, "Event")
        return f"{subject} {suffix}"

    async def cluster_document(
        self,
        session: AsyncSession,
        doc: DocumentModel,
        source: SourceModel | None = None,
    ) -> EventModel:
        """
        Cluster a native document into an existing canonical event or create a new event.
        Also extracts factual claims with exact evidence spans.
        """
        loaded_mentions = doc.__dict__.get("mentions")
        if loaded_mentions is not None:
            doc_mentions = loaded_mentions
        else:
            mentions_stmt = select(MentionModel).where(MentionModel.doc_id == doc.id)
            doc_mentions = (await session.execute(mentions_stmt)).scalars().all()

        doc_entity_ids = list({m.entity_id for m in doc_mentions})
        version_tag = self._extract_version_tag(doc.original_text)
        event_type = self._determine_event_type(doc.original_text, doc_entity_ids)

        # Evidentiary role determination
        role = "corroborating"
        if source:
            role = determine_evidentiary_role(source.type, source.name, source.url)
        elif doc.source_id:
            s_stmt = select(SourceModel).where(SourceModel.id == doc.source_id)
            fetched_source = (await session.execute(s_stmt)).scalar_one_or_none()
            if fetched_source:
                role = determine_evidentiary_role(
                    fetched_source.type, fetched_source.name, fetched_source.url
                )

        # Look for matching active event within time window that shares canonical entities
        window_start = doc.published_at - self.time_window
        window_end = doc.published_at + self.time_window

        events_stmt = (
            select(EventModel)
            .where(
                EventModel.status == "active",
                EventModel.first_seen_at >= window_start,
                EventModel.first_seen_at <= window_end,
            )
            .order_by(EventModel.first_seen_at.asc())
        )
        candidate_events = (await session.execute(events_stmt)).scalars().all()

        target_event: EventModel | None = None

        if doc_entity_ids:
            for cand in candidate_events:
                # Check entity intersection
                shared = set(cand.canonical_entity_ids) & set(doc_entity_ids)
                if shared:
                    # If version_tag is specified on both, require it to match
                    if (
                        version_tag
                        and cand.version_tag
                        and version_tag != cand.version_tag
                    ):
                        continue
                    target_event = cand
                    break

        now = datetime.now(UTC)

        # If no event matched, create a new canonical event
        if not target_event:
            title = self._synthesize_canonical_title(
                doc_entity_ids, version_tag, event_type, doc.original_text
            )
            target_event = EventModel(
                id=str(uuid4()),
                type=event_type,
                title=title,
                canonical_entity_ids=doc_entity_ids,
                version_tag=version_tag,
                first_seen_at=doc.published_at,
                first_seen_lang=doc.lang,
                first_source_id=doc.source_id,
                status="active",
                created_at=now,
            )
            session.add(target_event)
            await session.flush()
        else:
            # Update existing event if this doc arrived earlier or has higher authority
            if role == "primary" and doc.published_at < target_event.first_seen_at:
                target_event.first_seen_at = doc.published_at
                target_event.first_seen_lang = doc.lang
                target_event.first_source_id = doc.source_id

            # Union canonical entities
            updated_entities = list(
                set(target_event.canonical_entity_ids) | set(doc_entity_ids)
            )
            target_event.canonical_entity_ids = updated_entities

        # Link document to event if not already linked
        link_stmt = select(EventDocumentModel).where(
            EventDocumentModel.event_id == target_event.id,
            EventDocumentModel.doc_id == doc.id,
        )
        existing_link = (await session.execute(link_stmt)).scalar_one_or_none()
        if not existing_link:
            event_doc = EventDocumentModel(
                id=str(uuid4()),
                event_id=target_event.id,
                doc_id=doc.id,
                role=role,
                linked_at=now,
            )
            session.add(event_doc)

        # Extract and persist factual claims
        extracted = claim_extractor.extract_claims(doc.original_text)
        for ext in extracted:
            # Check if this exact claim already exists for this event
            claim_stmt = select(ClaimModel).where(
                ClaimModel.event_id == target_event.id,
                ClaimModel.field == ext.field,
                ClaimModel.normalized_value == ext.normalized_value,
            )
            existing_claim = (await session.execute(claim_stmt)).scalar_one_or_none()
            if not existing_claim:
                claim = ClaimModel(
                    id=str(uuid4()),
                    event_id=target_event.id,
                    doc_id=doc.id,
                    field=ext.field,
                    normalized_value=ext.normalized_value,
                    unit=ext.unit,
                    evidence_span_start=ext.evidence_span_start,
                    evidence_span_end=ext.evidence_span_end,
                    evidence_text=ext.evidence_text,
                    confidence=ext.confidence,
                    created_at=now,
                )
                session.add(claim)

        return target_event

    async def cluster_unclustered_documents(
        self, session: AsyncSession, limit: int = 300
    ) -> int:
        """Find unclustered documents and cluster them into canonical events."""
        # Find documents that have no event_documents link
        subquery = select(EventDocumentModel.doc_id)
        stmt = (
            select(DocumentModel)
            .where(DocumentModel.id.not_in(subquery))
            .order_by(DocumentModel.published_at.asc())
            .limit(limit)
        )
        docs = (await session.execute(stmt)).scalars().all()
        count = 0
        for doc in docs:
            await self.cluster_document(session, doc)
            count += 1
        return count

    async def get_event_dossier(
        self, session: AsyncSession, event_id: str
    ) -> dict | None:
        """
        Produce a full cross-lingual event dossier:
        - Language-independent canonical metadata
        - Grouped documents by evidentiary role (primary, corroborating, derivative)
        - Extracted claims with exact original character spans
        - Language parity & cross-lingual reporting latency
        """
        event_stmt = select(EventModel).where(EventModel.id == event_id)
        event = (await session.execute(event_stmt)).scalar_one_or_none()
        if not event:
            return None

        # Fetch event documents explicitly
        docs_stmt = (
            select(EventDocumentModel)
            .where(EventDocumentModel.event_id == event_id)
            .options(selectinload(EventDocumentModel.document))
        )
        event_docs = (await session.execute(docs_stmt)).scalars().all()

        # Fetch event claims explicitly
        claims_stmt = (
            select(ClaimModel)
            .where(ClaimModel.event_id == event_id)
            .order_by(ClaimModel.created_at.asc())
        )
        claims = (await session.execute(claims_stmt)).scalars().all()

        # Categorize documents
        docs_by_role: dict[str, list[dict]] = {
            "primary": [],
            "corroborating": [],
            "derivative": [],
        }
        langs_seen: set[str] = set()
        first_zh_at: datetime | None = None
        first_en_at: datetime | None = None

        for ed in event_docs:
            d = ed.document
            if not d:
                continue
            langs_seen.add(d.lang)
            if d.lang == "zh" and (first_zh_at is None or d.published_at < first_zh_at):
                first_zh_at = d.published_at
            elif d.lang == "en" and (
                first_en_at is None or d.published_at < first_en_at
            ):
                first_en_at = d.published_at

            snippet = d.original_text[:200] + (
                "..." if len(d.original_text) > 200 else ""
            )
            doc_info = {
                "doc_id": d.id,
                "role": ed.role,
                "lang": d.lang,
                "script": d.script,
                "published_at": d.published_at.isoformat(),
                "snippet": snippet,
                "length": len(d.original_text),
            }
            docs_by_role.setdefault(ed.role, []).append(doc_info)

        # Calculate cross-lingual reporting latency delta
        latency_delta_hours: float | None = None
        leader_lang: str | None = None
        if first_zh_at and first_en_at:
            delta = (first_en_at - first_zh_at).total_seconds() / 3600.0
            latency_delta_hours = round(abs(delta), 2)
            leader_lang = "zh" if first_zh_at <= first_en_at else "en"

        claims_list = [
            {
                "claim_id": c.id,
                "field": c.field,
                "normalized_value": c.normalized_value,
                "unit": c.unit,
                "evidence_span": [c.evidence_span_start, c.evidence_span_end],
                "evidence_text": c.evidence_text,
                "confidence": c.confidence,
                "doc_id": c.doc_id,
            }
            for c in claims
        ]

        return {
            "event_id": event.id,
            "title": event.title,
            "type": event.type,
            "version_tag": event.version_tag,
            "canonical_entity_ids": event.canonical_entity_ids,
            "status": event.status,
            "first_seen_at": event.first_seen_at.isoformat(),
            "first_seen_lang": event.first_seen_lang,
            "languages_covered": list(langs_seen),
            "cross_lingual_parity": {
                "bilingual": len(langs_seen) > 1,
                "leader_lang": leader_lang,
                "latency_delta_hours": latency_delta_hours,
            },
            "documents_count": len(event_docs),
            "documents_by_role": docs_by_role,
            "claims": claims_list,
        }


event_service = CrossLingualEventService()
