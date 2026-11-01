"""
Derived View Service (Translate-Last Presentation Layer).

Implements on-demand, lazy machine translation and event-level executive summaries:
1. Translates ONLY when explicitly requested for human display, never on ingestion.
2. Caches versioned views in `document_views` (immutable original remains untouched).
3. Synthesizes cross-lingual event executive summaries directly from grounded claims and multi-source timelines.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from deep_translator import GoogleTranslator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_security_monitor.infrastructure.database.models import (
    ClaimModel,
    DocumentModel,
    DocumentViewModel,
    EventDocumentModel,
    EventModel,
)

logger = structlog.get_logger(__name__)


class DerivedViewService:
    """Manages versioned, on-demand document translations and event summaries."""

    async def get_or_create_document_translation(
        self,
        session: AsyncSession,
        doc_id: str,
        target_lang: str = "en",
    ) -> DocumentViewModel | None:
        """
        Lazily translate a document's original text into target_lang on-demand.
        Returns cached view from `document_views` if already translated.
        """
        view_type = f"mt_{target_lang}"

        # 1. Check existing view cache
        stmt = select(DocumentViewModel).where(
            DocumentViewModel.doc_id == doc_id,
            DocumentViewModel.view_type == view_type,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        # 2. Fetch original document
        doc_stmt = select(DocumentModel).where(DocumentModel.id == doc_id)
        doc = (await session.execute(doc_stmt)).scalar_one_or_none()
        if not doc:
            return None

        # If source language matches target, view is identical
        if doc.lang == target_lang:
            view = DocumentViewModel(
                id=str(uuid4()),
                doc_id=doc.id,
                view_type=view_type,
                text=doc.original_text,
                producer="identity",
                quality_score=1.0,
                created_at=datetime.now(UTC),
            )
            session.add(view)
            await session.flush()
            return view

        # 3. On-demand translation with rate-limit protection
        translated_text: str
        producer = f"google_mt:{target_lang}:v1"
        try:
            # Run deep_translator in thread pool to avoid blocking async event loop
            loop = asyncio.get_running_loop()
            trans = GoogleTranslator(source="auto", target=target_lang)
            # Truncate to 4500 chars to respect free translator block limits
            chunk = doc.original_text[:4500]
            translated_text = await loop.run_in_executor(None, trans.translate, chunk)
            quality_score = 0.90
        except Exception as err:
            logger.warning(
                f"On-demand translation failed for doc {doc_id}: {err}. Using original fallback."
            )
            translated_text = f"[Translation unavailable] {doc.original_text}"
            producer = "fallback:original"
            quality_score = 0.50

        view = DocumentViewModel(
            id=str(uuid4()),
            doc_id=doc.id,
            view_type=view_type,
            text=translated_text,
            producer=producer,
            quality_score=quality_score,
            created_at=datetime.now(UTC),
        )
        session.add(view)
        await session.flush()
        return view

    async def generate_event_summary(
        self,
        session: AsyncSession,
        event_id: str,
        lang: str = "en",
    ) -> dict[str, Any] | None:
        """
        Synthesize a factual, grounded executive summary across all event documents
        and claims without AI slop or unverified claims.
        """
        # Fetch event
        event_stmt = (
            select(EventModel)
            .where(EventModel.id == event_id)
            .options(
                selectinload(EventModel.documents).selectinload(
                    EventDocumentModel.document
                ),
                selectinload(EventModel.claims),
            )
        )
        event = (await session.execute(event_stmt)).scalar_one_or_none()
        if not event:
            return None

        # Fetch explicitly to avoid session identity issues
        docs_stmt = (
            select(EventDocumentModel)
            .where(EventDocumentModel.event_id == event_id)
            .options(selectinload(EventDocumentModel.document))
        )
        event_docs = (await session.execute(docs_stmt)).scalars().all()

        claims_stmt = (
            select(ClaimModel)
            .where(ClaimModel.event_id == event_id)
            .order_by(ClaimModel.confidence.desc())
        )
        claims = (await session.execute(claims_stmt)).scalars().all()

        # Group claims by field
        claims_by_field: dict[str, list[ClaimModel]] = {}
        for c in claims:
            claims_by_field.setdefault(c.field, []).append(c)

        # Categorize documents by language and role
        primary_docs = [
            ed.document for ed in event_docs if ed.role == "primary" and ed.document
        ]
        corrob_docs = [
            ed.document
            for ed in event_docs
            if ed.role == "corroborating" and ed.document
        ]

        langs = list({ed.document.lang for ed in event_docs if ed.document})
        total_docs = len(event_docs)

        # Extract timeline lead/lag
        zh_docs = [
            ed.document for ed in event_docs if ed.document and ed.document.lang == "zh"
        ]
        en_docs = [
            ed.document for ed in event_docs if ed.document and ed.document.lang == "en"
        ]

        timing_lead = ""
        if zh_docs and en_docs:
            first_zh = min(d.published_at for d in zh_docs)
            first_en = min(d.published_at for d in en_docs)
            delta_h = (first_en - first_zh).total_seconds() / 3600.0
            if delta_h > 0.1:
                timing_lead = f"Chinese primary sources broke the news {delta_h:.1f} hours before Western coverage."
            elif delta_h < -0.1:
                timing_lead = f"English sources broke the news {abs(delta_h):.1f} hours before Chinese coverage."
            else:
                timing_lead = "Concurrent simultaneous cross-lingual release."

        # Synthesize brief text
        lead_claims: list[str] = []
        if "params" in claims_by_field:
            p = claims_by_field["params"][0].normalized_value
            lead_claims.append(f"{p} parameters")
        if "context_window" in claims_by_field:
            ctx = claims_by_field["context_window"][0].normalized_value
            lead_claims.append(f"{ctx} context window")
        if "license" in claims_by_field:
            lic = claims_by_field["license"][0].normalized_value
            lead_claims.append(f"open-source license: {lic}")

        specs_str = f" featuring {', '.join(lead_claims)}" if lead_claims else ""

        if lang == "zh":
            summary_text = (
                f"【{event.title}】由{len(primary_docs)}个官方源与{len(corrob_docs)}个验证媒体联合确认。"
                f"{specs_str}。覆盖语言：{', '.join(langs)}。"
            )
            if timing_lead:
                summary_text += f" 时间线：{timing_lead}"
        else:
            summary_text = (
                f"{event.title} confirmed by {len(primary_docs)} primary source(s) and {len(corrob_docs)} "
                f"corroborating reports across {total_docs} document(s){specs_str}. "
                f"Covered across: {', '.join(langs).upper()}."
            )
            if timing_lead:
                summary_text += f" {timing_lead}"

        bench_table = [
            {
                "benchmark": c.normalized_value.split(":", 1)[0].strip()
                if ":" in c.normalized_value
                else c.field,
                "score": c.normalized_value.split(":", 1)[1].strip()
                if ":" in c.normalized_value
                else c.normalized_value,
                "evidence_text": c.evidence_text,
                "evidence_span": [c.evidence_span_start, c.evidence_span_end],
            }
            for c in claims_by_field.get("benchmark_score", [])
        ]

        return {
            "event_id": event.id,
            "title": event.title,
            "type": event.type,
            "version_tag": event.version_tag,
            "language": lang,
            "summary_text": summary_text,
            "key_specifications": lead_claims,
            "timing_lead": timing_lead,
            "benchmarks": bench_table,
            "total_documents": total_docs,
            "primary_documents_count": len(primary_docs),
            "corroborating_documents_count": len(corrob_docs),
            "canonical_entity_ids": event.canonical_entity_ids,
            "first_seen_at": event.first_seen_at.isoformat(),
        }


derived_view_service = DerivedViewService()
