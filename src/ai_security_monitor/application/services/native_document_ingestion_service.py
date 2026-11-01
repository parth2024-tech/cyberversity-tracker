"""
Native Document Ingestion and Entity Linking Service.

Adheres to the core Multilingual Event-Intelligence Architecture:
1. Ingests content in its native language directly into `documents`.
2. Identifies language code and script (Simplified vs Traditional Chinese) without translation.
3. Creates initial immutable `original` view in `document_views`.
4. Resolves language-independent entity mentions across scripts into canonical IDs.
5. Populates ground-truth character offset spans in `mentions`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.application.services.language_detection_service import (
    language_detector,
)
from ai_security_monitor.config.entity_taxonomy import (
    CANONICAL_ENTITIES_SEED,
)
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.infrastructure.database.models import (
    CanonicalEntityModel,
    DocumentModel,
    DocumentViewModel,
    EntityAliasModel,
    EntryEntityModel,
    EntryModel,
    MentionModel,
)

logger = structlog.get_logger(__name__)


class NativeDocumentIngestionService:
    """Ingests native-language intelligence documents, resolves entities, and tracks mentions."""

    def __init__(self) -> None:
        self._compiled_matchers: list[tuple[re.Pattern, str, float]] | None = None

    def _get_matchers(self) -> list[tuple[re.Pattern, str, float]]:
        """Compile regex matchers for canonical entity aliases with script-aware boundary handling."""
        if self._compiled_matchers is not None:
            return self._compiled_matchers

        matchers: list[tuple[re.Pattern, str, float]] = []
        for entity_spec in CANONICAL_ENTITIES_SEED:
            for alias_spec in entity_spec.aliases:
                alias = alias_spec.alias.strip()
                if not alias:
                    continue

                # Check if alias contains CJK characters
                has_cjk = bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", alias))
                escaped = re.escape(alias)

                if has_cjk:
                    # Chinese does not use whitespace word boundaries
                    pat = re.compile(escaped, re.IGNORECASE)
                else:
                    # Use ASCII boundary lookaround instead of Unicode \b
                    # so that Chinese characters adjacent to Latin words (e.g. 发布DeepSeek模型) are recognized
                    pat = re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)

                matchers.append((pat, entity_spec.canonical_id, alias_spec.confidence))

        # Sort matchers by pattern length descending to prefer longest matches
        matchers.sort(key=lambda x: len(x[0].pattern), reverse=True)
        self._compiled_matchers = matchers
        return self._compiled_matchers

    async def seed_canonical_entities(self, session: AsyncSession) -> int:
        """Idempotently seed the entities and entity_aliases tables from CANONICAL_ENTITIES_SEED."""
        seeded_count = 0
        now = datetime.now(UTC)

        for entity_spec in CANONICAL_ENTITIES_SEED:
            stmt = select(CanonicalEntityModel).where(
                CanonicalEntityModel.canonical_id == entity_spec.canonical_id
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if not existing:
                entity_model = CanonicalEntityModel(
                    canonical_id=entity_spec.canonical_id,
                    type=entity_spec.type,
                    canonical_name=entity_spec.canonical_name,
                    status=entity_spec.status,
                    created_at=now,
                )
                session.add(entity_model)
                seeded_count += 1

            for alias_spec in entity_spec.aliases:
                alias_stmt = select(EntityAliasModel).where(
                    EntityAliasModel.entity_id == entity_spec.canonical_id,
                    EntityAliasModel.alias == alias_spec.alias,
                )
                existing_alias = (await session.execute(alias_stmt)).scalar_one_or_none()

                if not existing_alias:
                    alias_model = EntityAliasModel(
                        id=str(uuid4()),
                        entity_id=entity_spec.canonical_id,
                        alias=alias_spec.alias,
                        lang=alias_spec.lang,
                        script=alias_spec.script,
                        source=alias_spec.source,
                        confidence=alias_spec.confidence,
                    )
                    session.add(alias_model)

        await session.flush()
        return seeded_count

    def extract_mentions(
        self, text: str
    ) -> list[tuple[int, int, str, float]]:
        """
        Scan native text for canonical entity aliases and return non-overlapping spans.
        Returns list of (span_start, span_end, canonical_id, confidence).
        """
        if not text:
            return []

        matchers = self._get_matchers()
        raw_spans: list[tuple[int, int, str, float]] = []

        for pat, canonical_id, confidence in matchers:
            for m in pat.finditer(text):
                raw_spans.append((m.start(), m.end(), canonical_id, confidence))

        # Sort spans by length descending, then start index ascending
        raw_spans.sort(key=lambda s: (s[1] - s[0]), reverse=True)

        accepted_spans: list[tuple[int, int, str, float]] = []
        occupied: list[tuple[int, int]] = []

        for start, end, cid, conf in raw_spans:
            # Check overlap with already accepted longer spans
            overlaps = any(
                not (end <= occ_start or start >= occ_end)
                for occ_start, occ_end in occupied
            )
            if not overlaps:
                accepted_spans.append((start, end, cid, conf))
                occupied.append((start, end))

        # Sort by character offset
        accepted_spans.sort(key=lambda s: s[0])
        return accepted_spans

    async def ingest_entry(
        self,
        session: AsyncSession,
        entry: EntryModel | Entry,
        source_id: str | UUID | None = None,
    ) -> DocumentModel:
        """
        Ingest an entry into native documents table, create original view,
        and link canonical entity mentions.
        """
        entry_id_str = str(entry.id)
        sid_str = str(source_id or entry.source_id)

        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        raw_text = f"{title}\n\n{summary}".strip() if summary else title.strip()

        pub_at = getattr(entry, "published_at", None) or datetime.now(UTC)
        if pub_at.tzinfo is None:
            pub_at = pub_at.replace(tzinfo=UTC)

        fet_at = getattr(entry, "fetched_at", None) or datetime.now(UTC)
        if fet_at.tzinfo is None:
            fet_at = fet_at.replace(tzinfo=UTC)

        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        # Check if document already exists
        doc_stmt = select(DocumentModel).where(DocumentModel.content_hash == content_hash)
        existing_doc = (await session.execute(doc_stmt)).scalar_one_or_none()
        if existing_doc:
            if existing_doc.entry_id is None:
                existing_doc.entry_id = entry_id_str
            return existing_doc

        # Deterministic language and script detection
        lang_res = language_detector.detect(raw_text)

        doc = DocumentModel(
            id=str(uuid4()),
            source_id=sid_str,
            entry_id=entry_id_str,
            original_text=raw_text,
            lang=lang_res.lang,
            lang_confidence=lang_res.confidence,
            script=lang_res.script,
            published_at=pub_at,
            fetched_at=fet_at,
            content_hash=content_hash,
            raw_blob_ref=None,
        )
        session.add(doc)

        # 1. Create immutable original view
        original_view = DocumentViewModel(
            id=str(uuid4()),
            doc_id=doc.id,
            view_type="original",
            text=raw_text,
            producer="ingest_raw",
            quality_score=1.0,
            created_at=fet_at,
        )
        session.add(original_view)

        # 2. Extract and link canonical entity mentions
        spans = self.extract_mentions(raw_text)
        for span_start, span_end, canonical_id, confidence in spans:
            mention = MentionModel(
                id=str(uuid4()),
                doc_id=doc.id,
                entity_id=canonical_id,
                span_start=span_start,
                span_end=span_end,
                linker_version="v1.0",
                confidence=confidence,
            )
            session.add(mention)

            # Sync to backward-compatible entry_entities knowledge graph table
            entity_type = canonical_id.split(":")[0] if ":" in canonical_id else "organization"
            clean_name = canonical_id.split(":", 1)[1] if ":" in canonical_id else canonical_id
            display_name = raw_text[span_start:span_end]

            entry_ent = EntryEntityModel(
                id=str(uuid4()),
                entry_id=entry_id_str,
                entity_type=entity_type,
                name=clean_name,
                display_name=display_name,
                metric_value=None,
                context=raw_text[max(0, span_start - 30) : min(len(raw_text), span_end + 30)],
                confidence=confidence,
                created_at=fet_at,
            )
            session.add(entry_ent)

        await session.flush()
        return doc

    async def backfill_recent_entries(
        self, session: AsyncSession, limit: int = 200
    ) -> int:
        """Backfill existing entries into native documents table."""
        # Find entries that have no matching document
        stmt = (
            select(EntryModel)
            .outerjoin(DocumentModel, EntryModel.id == DocumentModel.entry_id)
            .where(
                DocumentModel.id.is_(None),
                EntryModel.is_purged.is_(False),
            )
            .order_by(EntryModel.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        entries = result.scalars().all()

        backfilled = 0
        for e in entries:
            try:
                await self.ingest_entry(session, e)
                backfilled += 1
            except Exception as err:
                logger.debug(f"Failed to backfill entry {e.id}: {err}")

        await session.commit()
        return backfilled


native_document_ingestion_service = NativeDocumentIngestionService()
