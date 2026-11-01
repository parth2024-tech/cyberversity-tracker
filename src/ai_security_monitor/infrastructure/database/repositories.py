"""
Repository implementations using SQLAlchemy async.
Implements the domain repository interfaces.
"""

from __future__ import annotations

import builtins
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, false, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_security_monitor.domain.entities import (
    AIEntity,
    Analysis,
    AnalysisModel,
    Category,
    Digest,
    EntityType,
    Entry,
    FetchLog,
    FetchStatus,
    LLMReceipt,
    Source,
    SourceType,
)
from ai_security_monitor.domain.exceptions import (
    DuplicateEntryError,
    EntityNotFoundError,
)
from ai_security_monitor.domain.repositories import (
    AIEntityRepository,
    AnalysisRepository,
    DigestRepository,
    EntryFilters,
    EntryRepository,
    FetchLogRepository,
    LLMReceiptRepository,
    PaginationParams,
    SourceRepository,
)
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.infrastructure.database.models import (
    AnalysisModel as AnalysisModelDB,
)
from ai_security_monitor.infrastructure.database.models import (
    DigestModel,
    EntryEntityModel,
    EntryModel,
    FetchLogModel,
    ReceiptModel,
    SourceModel,
    WatchlistRuleModel,
)


def _uuid_to_str(uuid_val: UUID) -> str:
    return str(uuid_val)


def _str_to_uuid(str_val: str) -> UUID:
    return UUID(str_val)


class SQLAlchemyEntryRepository(EntryRepository):
    """SQLAlchemy implementation of EntryRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, entry: Entry) -> Entry:
        # Check for duplicate content hash
        existing = await self.get_by_content_hash(entry.content_hash)
        if existing:
            raise DuplicateEntryError(entry.content_hash)

        model = EntryModel(
            id=_uuid_to_str(entry.id),
            source_id=_uuid_to_str(entry.source_id),
            title=entry.title,
            url=entry.url,
            content_hash=entry.content_hash,
            summary=entry.summary,
            published_at=entry.published_at,
            fetched_at=entry.fetched_at,
            category=entry.category.value,
            tags=entry.tags,
            extra_metadata=entry.metadata,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            is_purged=entry.is_purged,
            purged_at=entry.purged_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateEntryError(entry.content_hash) from exc
        return self._model_to_entity(model)

    async def get(self, entry_id: UUID, include_purged: bool = False) -> Entry | None:
        stmt = (
            select(EntryModel)
            .options(selectinload(EntryModel.analysis))
            .where(EntryModel.id == _uuid_to_str(entry_id))
        )
        if not include_purged:
            stmt = stmt.where(EntryModel.is_purged.is_(False))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_content_hash(self, content_hash: str) -> Entry | None:
        stmt = select(EntryModel).where(EntryModel.content_hash == content_hash)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_existing_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        stmt = select(EntryModel.content_hash).where(
            EntryModel.content_hash.in_(hashes)
        )
        result = await self._session.execute(stmt)
        return set(result.scalars().all())

    async def list(
        self,
        filters: EntryFilters | None = None,
        pagination: PaginationParams | None = None,
    ) -> list[Entry]:
        stmt = select(EntryModel).options(selectinload(EntryModel.analysis))

        analysis_joined = False
        if filters:
            stmt, analysis_joined = self._apply_filters(stmt, filters)
        else:
            stmt = stmt.where(EntryModel.is_purged.is_(False))

        if filters and filters.sort_by == "velocity":
            if not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
            stmt = stmt.order_by(
                desc(AnalysisModelDB.threat_velocity),
                desc(EntryModel.published_at),
                desc(EntryModel.fetched_at),
            )
        elif filters and filters.sort_by == "top":
            # Top news blends recency and impact: newest dispatches lead, ranked by velocity/stars
            if not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
            stmt = stmt.order_by(
                desc(EntryModel.published_at),
                desc(AnalysisModelDB.threat_velocity),
                desc(EntryModel.fetched_at),
            )
        elif filters and filters.sort_by == "blast":
            if not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
            stmt = stmt.order_by(
                desc(AnalysisModelDB.blast_radius_score),
                desc(EntryModel.published_at),
                desc(EntryModel.fetched_at),
            )
        elif filters and filters.sort_by == "severity":
            if not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
            stmt = stmt.order_by(
                desc(AnalysisModelDB.severity_index),
                desc(EntryModel.published_at),
                desc(EntryModel.fetched_at),
            )
        elif filters and filters.sort_by == "published":
            stmt = stmt.order_by(
                desc(EntryModel.published_at), desc(EntryModel.fetched_at)
            )
        else:
            # Default "newest": order by published_at DESC so the latest research, models, and intelligence lead the feed
            stmt = stmt.order_by(
                desc(EntryModel.published_at), desc(EntryModel.fetched_at)
            )

        if pagination:
            stmt = stmt.limit(pagination.limit).offset(pagination.offset)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def count(self, filters: EntryFilters | None = None) -> int:
        stmt = select(func.count(EntryModel.id))

        if filters:
            stmt, _ = self._apply_filters(stmt, filters)
        else:
            stmt = stmt.where(EntryModel.is_purged.is_(False))

        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def count_by_source(self, source_id: UUID | str) -> int:
        """Count active (non-purged) entries stored for a specific source."""
        s_id = str(source_id)
        stmt = select(func.count(EntryModel.id)).where(
            and_(EntryModel.source_id == s_id, EntryModel.is_purged.is_(False))
        )
        res = await self._session.execute(stmt)
        return int(res.scalar() or 0)

    async def search_fts(self, query: str, limit: int = 50) -> builtins.list[Entry]:
        """Sub-millisecond BM25 full-text search using SQLite FTS5 table."""
        import re

        tokens = re.findall(r"\w+", query)
        if not tokens:
            return []
        safe_q = " ".join(f'"{t}"' for t in tokens)

        try:
            sql = text(
                "SELECT entry_id, bm25(entries_fts) as rank "
                "FROM entries_fts WHERE entries_fts MATCH :query "
                "ORDER BY rank ASC LIMIT :limit"
            )
            result = await self._session.execute(sql, {"query": safe_q, "limit": limit})
            rows = result.fetchall()
            if not rows:
                return []

            entry_ids = [r[0] for r in rows]
            stmt = select(EntryModel).where(
                EntryModel.id.in_(entry_ids),
                EntryModel.is_purged.is_(False),
            )
            models_result = await self._session.execute(stmt)
            models_by_id = {m.id: m for m in models_result.scalars().all()}
            ordered = [models_by_id[eid] for eid in entry_ids if eid in models_by_id]
            return [self._model_to_entity(m) for m in ordered]
        except Exception:
            # Fallback to ILIKE if FTS5 table is uninitialized
            raw_fallback = " ".join(tokens)
            stmt = (
                select(EntryModel)
                .where(
                    or_(
                        EntryModel.title.ilike(f"%{raw_fallback}%"),
                        EntryModel.summary.ilike(f"%{raw_fallback}%"),
                    ),
                    EntryModel.is_purged.is_(False),
                )
                .order_by(desc(EntryModel.published_at))
                .limit(limit)
            )
            models_res = await self._session.execute(stmt)
            return [self._model_to_entity(m) for m in models_res.scalars().all()]

    async def update(self, entry: Entry) -> Entry:
        stmt = select(EntryModel).where(EntryModel.id == _uuid_to_str(entry.id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            raise EntityNotFoundError("Entry", str(entry.id))

        model.title = entry.title
        model.url = entry.url
        model.summary = entry.summary
        model.tags = entry.tags
        model.extra_metadata = entry.metadata
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return self._model_to_entity(model)

    async def delete(self, entry_id: UUID, hard_delete: bool = True) -> bool:
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import update as sa_update

        entry_id_str = _uuid_to_str(entry_id)
        stmt = select(EntryModel).where(EntryModel.id == entry_id_str)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return False

        if hard_delete:
            await self._session.execute(
                sa_delete(AnalysisModelDB)
                .where(AnalysisModelDB.entry_id == entry_id_str)
                .execution_options(synchronize_session=False)
            )
            await self._session.delete(model)
        else:
            await self._session.execute(
                sa_update(EntryModel)
                .where(EntryModel.id == entry_id_str)
                .values(is_purged=True, purged_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
        self._session.expire_all()
        return True

    async def delete_entries_by_ids(
        self, entry_ids: builtins.list[UUID], hard_delete: bool = True
    ) -> int:
        if not entry_ids:
            return 0
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import update as sa_update

        id_strs = [_uuid_to_str(eid) for eid in entry_ids]
        if hard_delete:
            await self._session.execute(
                sa_delete(AnalysisModelDB)
                .where(AnalysisModelDB.entry_id.in_(id_strs))
                .execution_options(synchronize_session=False)
            )
            del_result = await self._session.execute(
                sa_delete(EntryModel)
                .where(EntryModel.id.in_(id_strs))
                .execution_options(synchronize_session=False)
            )
            self._session.expire_all()
            return getattr(del_result, "rowcount", 0) or 0
        else:
            upd_result = await self._session.execute(
                sa_update(EntryModel)
                .where(EntryModel.id.in_(id_strs))
                .values(is_purged=True, purged_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
            self._session.expire_all()
            return getattr(upd_result, "rowcount", 0) or 0

    async def get_unanalyzed(
        self,
        since: datetime | None = None,
        limit: int = 50,
    ) -> builtins.list[Entry]:
        stmt = (
            select(EntryModel)
            .outerjoin(AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id)
            .where(AnalysisModelDB.entry_id.is_(None))
            .where(EntryModel.is_purged.is_(False))
        )

        if since:
            stmt = stmt.where(EntryModel.published_at >= since)

        stmt = stmt.order_by(desc(EntryModel.published_at)).limit(limit)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def purge_old_entries(
        self,
        older_than_days: int = 7,
        hard_delete: bool = False,
        include_vaulted: bool = False,
        categories: builtins.list[str] | None = None,
    ) -> int:
        """Purge entries older than retention window.

        - If older_than_days == 0: targets ALL active entries immediately.
        - If include_vaulted == False: entries marked as important/saved/pinned are preserved.
        - If include_vaulted == True: all entries matching the time window (including vault) are purged.
        - If hard_delete == True: records and their analyses are permanently deleted from database disk.
        - If hard_delete == False: records are marked soft-deleted (is_purged=True, purged_at=now).
        - If categories is provided: only purges entries belonging to the specified categories.

        Returns the number of rows purged.
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import not_
        from sqlalchemy import update as sa_update

        # Time condition:
        # If older_than_days == 0: targets ALL active entries immediately.
        # Otherwise: an entry is matched if published_at < cutoff OR fetched_at < cutoff.
        # This guarantees that stale articles are always pruned, whether by publish date or ingest date.
        time_cond: Any
        if older_than_days == 0:
            time_cond = True
        else:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            cutoff_naive = cutoff.replace(tzinfo=None)
            time_cond = or_(
                EntryModel.published_at < cutoff,
                EntryModel.published_at < cutoff_naive,
                EntryModel.fetched_at < cutoff,
                EntryModel.fetched_at < cutoff_naive,
            )

        conds: list[Any] = [EntryModel.is_purged.is_(False)]
        if time_cond is not True:
            conds.append(time_cond)

        if categories:
            conds.append(EntryModel.category.in_(categories))

        if not include_vaulted:
            not_vaulted_cond = or_(
                EntryModel.extra_metadata.is_(None),
                and_(
                    not_(EntryModel.extra_metadata.like('%"is_important": true%')),
                    not_(EntryModel.extra_metadata.like('%"is_saved": true%')),
                    not_(EntryModel.extra_metadata.like('%"is_pinned": true%')),
                ),
            )
            conds.append(not_vaulted_cond)

        expired_cond = and_(*conds)

        if hard_delete:
            subquery = select(EntryModel.id).where(expired_cond)
            await self._session.execute(
                sa_delete(AnalysisModelDB)
                .where(AnalysisModelDB.entry_id.in_(subquery))
                .execution_options(synchronize_session=False)
            )
            del_result = await self._session.execute(
                sa_delete(EntryModel)
                .where(expired_cond)
                .execution_options(synchronize_session=False)
            )
            self._session.expire_all()
            return getattr(del_result, "rowcount", 0) or 0

        soft_del_result = await self._session.execute(
            sa_update(EntryModel)
            .where(expired_cond)
            .values(is_purged=True, purged_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return getattr(soft_del_result, "rowcount", 0) or 0

    async def hard_delete_purged(self, grace_days: int = 30) -> int:
        """Permanently remove entries that were soft-deleted beyond the grace window (default 30 days)."""
        from sqlalchemy import delete as sa_delete

        cutoff = datetime.now(UTC) - timedelta(days=grace_days)
        cutoff_naive = cutoff.replace(tzinfo=None)
        hard_cond = and_(
            EntryModel.is_purged.is_(True),
            EntryModel.purged_at.is_not(None),
            or_(
                EntryModel.purged_at < cutoff,
                EntryModel.purged_at < cutoff_naive,
            ),
        )
        subquery = select(EntryModel.id).where(hard_cond)
        await self._session.execute(
            sa_delete(AnalysisModelDB)
            .where(AnalysisModelDB.entry_id.in_(subquery))
            .execution_options(synchronize_session=False)
        )
        del_result = await self._session.execute(
            sa_delete(EntryModel)
            .where(hard_cond)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return getattr(del_result, "rowcount", 0) or 0

    async def restore_entry(self, entry_id: UUID) -> bool:
        """Restore a single soft-purged entry back to active visibility."""
        from sqlalchemy import update as sa_update

        result = await self._session.execute(
            sa_update(EntryModel)
            .where(EntryModel.id == _uuid_to_str(entry_id))
            .values(is_purged=False, purged_at=None)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def restore_purged_entries(self) -> int:
        """Restore all soft-purged entries back to active visibility (mark is_purged=False).

        Returns the number of rows restored.
        """
        from sqlalchemy import update as sa_update

        result = await self._session.execute(
            sa_update(EntryModel)
            .where(EntryModel.is_purged.is_(True))
            .values(is_purged=False, purged_at=None)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return getattr(result, "rowcount", 0) or 0

    async def get_retention_counts(
        self,
        older_than_days: int = 7,
        include_vaulted: bool = False,
        categories: builtins.list[str] | None = None,
    ) -> dict[str, int]:
        """Get counts of active entries, candidate entries older than X days, and soft-purged entries."""
        active_stmt = select(func.count(EntryModel.id)).where(
            EntryModel.is_purged.is_(False)
        )
        if categories:
            active_stmt = active_stmt.where(EntryModel.category.in_(categories))
        active_res = await self._session.execute(active_stmt)
        active_count = active_res.scalar() or 0

        purged_stmt = select(func.count(EntryModel.id)).where(
            EntryModel.is_purged.is_(True)
        )
        if categories:
            purged_stmt = purged_stmt.where(EntryModel.category.in_(categories))
        purged_res = await self._session.execute(purged_stmt)
        purged_count = purged_res.scalar() or 0

        from sqlalchemy import not_

        time_cond: Any
        if older_than_days == 0:
            time_cond = True
        else:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            cutoff_naive = cutoff.replace(tzinfo=None)
            time_cond = or_(
                EntryModel.published_at < cutoff,
                EntryModel.published_at < cutoff_naive,
                EntryModel.fetched_at < cutoff,
                EntryModel.fetched_at < cutoff_naive,
            )

        conds: list[Any] = [EntryModel.is_purged.is_(False)]
        if time_cond is not True:
            conds.append(time_cond)

        if categories:
            conds.append(EntryModel.category.in_(categories))

        if not include_vaulted:
            not_vaulted_cond = or_(
                EntryModel.extra_metadata.is_(None),
                and_(
                    not_(EntryModel.extra_metadata.like('%"is_important": true%')),
                    not_(EntryModel.extra_metadata.like('%"is_saved": true%')),
                    not_(EntryModel.extra_metadata.like('%"is_pinned": true%')),
                ),
            )
            conds.append(not_vaulted_cond)

        candidates_stmt = select(func.count(EntryModel.id)).where(and_(*conds))
        candidates_res = await self._session.execute(candidates_stmt)
        candidates_count = candidates_res.scalar() or 0

        # Vaulted count
        vaulted_stmt = select(func.count(EntryModel.id)).where(
            and_(
                EntryModel.is_purged.is_(False),
                or_(
                    EntryModel.extra_metadata.like('%"is_important": true%'),
                    EntryModel.extra_metadata.like('%"is_saved": true%'),
                    EntryModel.extra_metadata.like('%"is_pinned": true%'),
                ),
            )
        )
        vaulted_res = await self._session.execute(vaulted_stmt)
        vaulted_count = vaulted_res.scalar() or 0

        return {
            "active_count": active_count,
            "purged_count": purged_count,
            "candidates_count": candidates_count,
            "vaulted_count": vaulted_count,
            "older_than_days": older_than_days,
            "include_vaulted": include_vaulted,
        }

    async def toggle_importance(
        self,
        entry_id: UUID,
        is_important: bool | None = None,
        reason: str | None = None,
    ) -> Entry:
        """Toggle or explicitly set an entry's vault/importance status with metadata persistence."""
        stmt = (
            select(EntryModel)
            .options(selectinload(EntryModel.analysis))
            .where(EntryModel.id == _uuid_to_str(entry_id))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("Entry", str(entry_id))

        meta = dict(model.extra_metadata or {})
        current_state = bool(
            meta.get("is_important", False) or meta.get("is_saved", False)
        )
        new_state = (not current_state) if is_important is None else bool(is_important)

        meta["is_important"] = new_state
        meta["is_saved"] = new_state
        meta["is_pinned"] = new_state
        if new_state:
            meta["saved_at"] = datetime.now(UTC).isoformat()
            if reason:
                meta["importance_reason"] = reason
            elif not meta.get("importance_reason"):
                meta["importance_reason"] = "Saved to Vault for In-Depth Analysis"
        else:
            meta.pop("saved_at", None)

        model.extra_metadata = meta
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._model_to_entity(model)

    async def save_user_notes(self, entry_id: UUID, notes: str) -> Entry:
        """Attach user research, annotations, and analysis notes to an entry."""
        stmt = (
            select(EntryModel)
            .options(selectinload(EntryModel.analysis))
            .where(EntryModel.id == _uuid_to_str(entry_id))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("Entry", str(entry_id))

        meta = dict(model.extra_metadata or {})
        meta["user_notes"] = notes.strip()
        meta["notes_updated_at"] = datetime.now(UTC).isoformat()
        if not meta.get("is_important"):
            meta["is_important"] = True
            meta["is_saved"] = True
            meta["saved_at"] = datetime.now(UTC).isoformat()
            if not meta.get("importance_reason"):
                meta["importance_reason"] = "User Technical Analysis Attached"

        model.extra_metadata = meta
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get_by_category(
        self,
        category: Category,
        since: datetime | None = None,
        limit: int = 50,
    ) -> builtins.list[Entry]:
        stmt = (
            select(EntryModel)
            .options(selectinload(EntryModel.analysis))
            .where(EntryModel.category == category.value)
            .where(EntryModel.is_purged.is_(False))
        )

        if since:
            stmt = stmt.where(EntryModel.published_at >= since)

        stmt = stmt.order_by(desc(EntryModel.published_at)).limit(limit)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    def _apply_filters(self, stmt, filters: EntryFilters):
        # Exclude soft-deleted entries by default unless purged_only requested
        if getattr(filters, "purged_only", False):
            stmt = stmt.where(EntryModel.is_purged.is_(True))
        else:
            stmt = stmt.where(EntryModel.is_purged.is_(False))

        if filters.category:
            stmt = stmt.where(EntryModel.category == filters.category.value)
        elif filters.categories:
            stmt = stmt.where(
                EntryModel.category.in_(
                    [
                        c.value if hasattr(c, "value") else str(c)
                        for c in filters.categories
                    ]
                )
            )

        if filters.source_id:
            stmt = stmt.where(EntryModel.source_id == _uuid_to_str(filters.source_id))

        if filters.since:
            stmt = stmt.where(EntryModel.published_at >= filters.since)

        if filters.until:
            stmt = stmt.where(EntryModel.published_at <= filters.until)

        if filters.search:
            search_term = f"%{filters.search}%"
            stmt = stmt.where(
                or_(
                    EntryModel.title.ilike(search_term),
                    EntryModel.summary.ilike(search_term),
                )
            )

        if filters.keywords:
            kw_conditions = []
            for kw in filters.keywords:
                kw_clean = kw.strip()
                if kw_clean:
                    pattern = f"%{kw_clean}%"
                    kw_conditions.append(EntryModel.title.ilike(pattern))
                    kw_conditions.append(EntryModel.summary.ilike(pattern))
            if kw_conditions:
                stmt = stmt.where(or_(*kw_conditions))

        analysis_joined = False

        watchlist_rules = filters.watchlist_rules
        if watchlist_rules:
            rule_clauses = []
            needs_analysis = any(
                getattr(r, "min_threat_velocity", 0) > 0 for r in watchlist_rules
            )
            if needs_analysis and not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
                analysis_joined = True

            for rule in watchlist_rules:
                if not getattr(rule, "enabled", True):
                    continue
                rule_subclauses = []

                # 1. Keywords
                kw_conditions = []
                for kw in rule.keywords:
                    kw_clean = kw.strip()
                    if kw_clean:
                        pat = f"%{kw_clean}%"
                        kw_conditions.append(EntryModel.title.ilike(pat))
                        kw_conditions.append(EntryModel.summary.ilike(pat))
                        kw_conditions.append(EntryModel.tags.like(f"%{kw_clean}%"))
                if kw_conditions:
                    rule_subclauses.append(or_(*kw_conditions))

                # 2. Categories
                if rule.categories:
                    cat_vals = [
                        c.value if hasattr(c, "value") else str(c)
                        for c in rule.categories
                    ]
                    rule_subclauses.append(EntryModel.category.in_(cat_vals))

                # 3. Minimum velocity threshold
                if getattr(rule, "min_threat_velocity", 0) > 0:
                    rule_subclauses.append(
                        AnalysisModelDB.threat_velocity >= rule.min_threat_velocity
                    )

                if rule_subclauses:
                    rule_clauses.append(and_(*rule_subclauses))

            if rule_clauses:
                stmt = stmt.where(or_(*rule_clauses))
            else:
                stmt = stmt.where(false())

        if filters.pre_cve_only:
            if not analysis_joined:
                stmt = stmt.join(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
                analysis_joined = True
            stmt = stmt.where(AnalysisModelDB.is_pre_cve_warning.is_(True))

        if filters.high_velocity_only:
            if not analysis_joined:
                stmt = stmt.join(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
                analysis_joined = True
            stmt = stmt.where(AnalysisModelDB.threat_velocity >= 70)

        if filters.analyzed_only:
            if not analysis_joined:
                stmt = stmt.join(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
                analysis_joined = True
            stmt = stmt.where(AnalysisModelDB.entry_id.is_not(None))

        if filters.unanalyzed_only:
            if not analysis_joined:
                stmt = stmt.outerjoin(
                    AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id
                )
                analysis_joined = True
            stmt = stmt.where(AnalysisModelDB.entry_id.is_(None))

        if getattr(filters, "important_only", False):
            stmt = stmt.where(
                or_(
                    EntryModel.extra_metadata.like('%"is_important": true%'),
                    EntryModel.extra_metadata.like('%"is_saved": true%'),
                    EntryModel.extra_metadata.like('%"is_pinned": true%'),
                )
            )

        source_joined = False

        if filters.region and filters.region != "all":
            reg = filters.region.lower()
            if not source_joined:
                stmt = stmt.join(SourceModel, EntryModel.source_id == SourceModel.id)
                source_joined = True

            if reg in ("china", "cn"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "china"%'),
                        SourceModel.config.like('%"country": "CN"%'),
                        SourceModel.config.like('%"country": "HK"%'),
                        EntryModel.extra_metadata.like('%"region": "china"%'),
                        EntryModel.extra_metadata.like('%"country": "CN"%'),
                        EntryModel.extra_metadata.like('%"country": "HK"%'),
                    )
                )
            elif reg in ("india", "south_asia", "in"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "south_asia"%'),
                        SourceModel.config.like('%"country": "IN"%'),
                    )
                )
            elif reg in ("middle_east", "me", "il", "ae"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "middle_east"%'),
                        SourceModel.config.like('%"country": "IL"%'),
                        SourceModel.config.like('%"country": "AE"%'),
                    )
                )
            elif reg in ("nordic", "fi", "se"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "nordic"%'),
                        SourceModel.config.like('%"country": "FI"%'),
                        SourceModel.config.like('%"country": "SE"%'),
                    )
                )
            elif reg in ("europe", "eu"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "europe"%'),
                        SourceModel.config.like('%"country": "EU"%'),
                        SourceModel.config.like('%"country": "GB"%'),
                        SourceModel.config.like('%"country": "DE"%'),
                        SourceModel.config.like('%"country": "FR"%'),
                        SourceModel.config.like('%"country": "NL"%'),
                        SourceModel.config.like('%"country": "CH"%'),
                    )
                )
            elif reg in ("north_america", "na", "us", "ca"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "north_america"%'),
                        SourceModel.config.like('%"country": "US"%'),
                        SourceModel.config.like('%"country": "CA"%'),
                    )
                )
            elif reg in ("apac", "asia_pacific"):
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like('%"region": "apac"%'),
                        SourceModel.config.like('%"country": "JP"%'),
                        SourceModel.config.like('%"country": "KR"%'),
                        SourceModel.config.like('%"country": "TW"%'),
                        SourceModel.config.like('%"country": "SG"%'),
                        SourceModel.config.like('%"country": "AU"%'),
                    )
                )
            else:
                clean_reg = re.sub(r"[^a-zA-Z0-9_\-]", "", filters.region.lower())
                if clean_reg:
                    stmt = stmt.where(
                        or_(
                            SourceModel.config.like(f'%"region": "{clean_reg}"%'),
                            EntryModel.extra_metadata.like(
                                f'%"region": "{clean_reg}"%'
                            ),
                        )
                    )

        if filters.country and filters.country != "all":
            clean_country = re.sub(r"[^a-zA-Z0-9_\-]", "", filters.country.upper())
            if clean_country:
                if not source_joined:
                    stmt = stmt.join(
                        SourceModel, EntryModel.source_id == SourceModel.id
                    )
                    source_joined = True
                stmt = stmt.where(
                    or_(
                        SourceModel.config.like(f'%"country": "{clean_country}"%'),
                        EntryModel.extra_metadata.like(
                            f'%"country": "{clean_country}"%'
                        ),
                    )
                )

        return stmt, analysis_joined

    def _model_to_entity(self, model: EntryModel) -> Entry:
        analysis = None
        if "analysis" in model.__dict__ and model.analysis is not None:
            analysis = Analysis(
                id=_str_to_uuid(model.analysis.id),
                entry_id=_str_to_uuid(model.analysis.entry_id),
                attack_vector=model.analysis.attack_vector,
                risk_assessment=model.analysis.risk_assessment,
                mitigation=model.analysis.mitigation,
                threat_velocity=model.analysis.threat_velocity,
                severity_index=model.analysis.severity_index,
                blast_radius_score=model.analysis.blast_radius_score,
                affected_ecosystem=model.analysis.affected_ecosystem or [],
                is_pre_cve_warning=model.analysis.is_pre_cve_warning,
                attack_archetype=model.analysis.attack_archetype,
                weaponization_potential=model.analysis.weaponization_potential,
                mitre_attack_id=getattr(model.analysis, "mitre_attack_id", None),
                mitre_technique=getattr(model.analysis, "mitre_technique", None),
                model=AnalysisModel(model.analysis.model)
                if model.analysis.model in [m.value for m in AnalysisModel]
                else AnalysisModel.HEURISTIC,
                confidence=model.analysis.confidence,
                decision_brief=getattr(model.analysis, "decision_brief", None),
                created_at=model.analysis.created_at,
                updated_at=model.analysis.updated_at,
            )

        try:
            category_enum = Category(model.category)
        except ValueError:
            category_enum = Category.AI_TECH

        entities_list: list[AIEntity] = []
        if "entities" in model.__dict__ and model.entities:
            for ent_m in model.entities:
                try:
                    e_type = EntityType(ent_m.entity_type)
                except ValueError:
                    e_type = EntityType.MODEL
                entities_list.append(
                    AIEntity(
                        id=_str_to_uuid(ent_m.id),
                        entry_id=_str_to_uuid(ent_m.entry_id),
                        entity_type=e_type,
                        name=ent_m.name,
                        display_name=ent_m.display_name,
                        metric_value=ent_m.metric_value,
                        context=ent_m.context,
                        confidence=ent_m.confidence,
                        created_at=ent_m.created_at,
                    )
                )

        return Entry(
            id=_str_to_uuid(model.id),
            source_id=_str_to_uuid(model.source_id),
            title=model.title,
            url=model.url,
            content_hash=model.content_hash,
            summary=model.summary,
            published_at=model.published_at,
            fetched_at=model.fetched_at,
            category=category_enum,
            tags=model.tags or [],
            metadata=model.extra_metadata or {},
            created_at=model.created_at,
            updated_at=model.updated_at,
            analysis=analysis,
            is_purged=bool(getattr(model, "is_purged", False)),
            purged_at=getattr(model, "purged_at", None),
            entities=entities_list,
        )


class SQLAlchemyAnalysisRepository(AnalysisRepository):
    """SQLAlchemy implementation of AnalysisRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, analysis: Analysis) -> Analysis:
        model = AnalysisModelDB(
            id=_uuid_to_str(analysis.id),
            entry_id=_uuid_to_str(analysis.entry_id),
            attack_vector=analysis.attack_vector,
            risk_assessment=analysis.risk_assessment,
            mitigation=analysis.mitigation,
            threat_velocity=analysis.threat_velocity,
            severity_index=analysis.severity_index,
            blast_radius_score=analysis.blast_radius_score,
            affected_ecosystem=analysis.affected_ecosystem,
            is_pre_cve_warning=analysis.is_pre_cve_warning,
            attack_archetype=analysis.attack_archetype,
            weaponization_potential=analysis.weaponization_potential
            or "Production Ready",
            mitre_attack_id=analysis.mitre_attack_id,
            mitre_technique=analysis.mitre_technique,
            model=analysis.model.value,
            confidence=analysis.confidence,
            decision_brief=analysis.decision_brief,
            created_at=analysis.created_at,
            updated_at=analysis.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, entry_id: UUID) -> Analysis | None:
        stmt = select(AnalysisModelDB).where(
            AnalysisModelDB.entry_id == _uuid_to_str(entry_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_entry(self, entry_id: UUID) -> Analysis | None:
        return await self.get(entry_id)

    async def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        stmt = select(AnalysisModelDB).where(
            AnalysisModelDB.id == _uuid_to_str(analysis_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def update(self, analysis: Analysis) -> Analysis:
        stmt = select(AnalysisModelDB).where(
            AnalysisModelDB.id == _uuid_to_str(analysis.id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            raise EntityNotFoundError("Analysis", str(analysis.id))

        model.attack_vector = analysis.attack_vector
        model.risk_assessment = analysis.risk_assessment
        model.mitigation = analysis.mitigation
        model.threat_velocity = analysis.threat_velocity
        model.severity_index = analysis.severity_index
        model.blast_radius_score = analysis.blast_radius_score
        model.affected_ecosystem = analysis.affected_ecosystem
        model.is_pre_cve_warning = analysis.is_pre_cve_warning
        model.attack_archetype = analysis.attack_archetype
        model.weaponization_potential = (
            analysis.weaponization_potential or "Production Ready"
        )
        model.mitre_attack_id = analysis.mitre_attack_id
        model.mitre_technique = analysis.mitre_technique
        model.model = analysis.model.value
        model.confidence = analysis.confidence
        model.decision_brief = analysis.decision_brief
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return self._model_to_entity(model)

    async def delete(self, entry_id: UUID) -> bool:
        stmt = select(AnalysisModelDB).where(
            AnalysisModelDB.entry_id == _uuid_to_str(entry_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return False

        await self._session.delete(model)
        return True

    async def count_high_velocity(self, threshold: int = 70) -> int:
        stmt = select(func.count(AnalysisModelDB.id)).where(
            AnalysisModelDB.threat_velocity >= threshold
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def count_pre_cve_warnings(self) -> int:
        stmt = select(func.count(AnalysisModelDB.id)).where(
            AnalysisModelDB.is_pre_cve_warning.is_(True)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    def _model_to_entity(self, model: AnalysisModelDB) -> Analysis:
        return Analysis(
            id=_str_to_uuid(model.id),
            entry_id=_str_to_uuid(model.entry_id),
            attack_vector=model.attack_vector,
            risk_assessment=model.risk_assessment,
            mitigation=model.mitigation,
            threat_velocity=model.threat_velocity,
            severity_index=model.severity_index,
            blast_radius_score=model.blast_radius_score,
            affected_ecosystem=model.affected_ecosystem,
            is_pre_cve_warning=model.is_pre_cve_warning,
            attack_archetype=model.attack_archetype,
            weaponization_potential=model.weaponization_potential,
            mitre_attack_id=getattr(model, "mitre_attack_id", None),
            mitre_technique=getattr(model, "mitre_technique", None),
            model=AnalysisModel(model.model)
            if model.model in [m.value for m in AnalysisModel]
            else AnalysisModel.HEURISTIC,
            confidence=model.confidence,
            decision_brief=getattr(model, "decision_brief", None),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SQLAlchemySourceRepository(SourceRepository):
    """SQLAlchemy implementation of SourceRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, source: Source) -> Source:
        model = SourceModel(
            id=_uuid_to_str(source.id),
            name=source.name,
            category=source.category.value,
            type=source.type.value,
            url=source.url,
            query=source.query,
            rate_limit_seconds=source.rate_limit_seconds,
            enabled=source.enabled,
            is_quarantined=source.is_quarantined,
            consecutive_failures=source.consecutive_failures,
            quarantined_at=source.quarantined_at,
            quarantine_reason=source.quarantine_reason,
            last_fetched_at=source.last_fetched_at,
            last_status=source.last_status.value if source.last_status else None,
            last_entries_new=source.last_entries_new,
            config=source.config,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, source_id: UUID) -> Source | None:
        stmt = select(SourceModel).where(SourceModel.id == _uuid_to_str(source_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_name(self, name: str) -> Source | None:
        if not name or not name.strip():
            return None
        stmt = select(SourceModel).where(SourceModel.name == name.strip()).limit(1)
        result = await self._session.execute(stmt)
        model = result.scalars().first()
        return self._model_to_entity(model) if model else None

    async def get_by_url(self, url: str) -> Source | None:
        if not url or not url.strip():
            return None
        stmt = select(SourceModel).where(SourceModel.url == url.strip()).limit(1)
        result = await self._session.execute(stmt)
        model = result.scalars().first()
        return self._model_to_entity(model) if model else None

    async def list(self, enabled_only: bool = False) -> list[Source]:
        stmt = select(SourceModel)
        if enabled_only:
            stmt = stmt.where(SourceModel.enabled.is_(True))
        stmt = stmt.order_by(SourceModel.category, SourceModel.name)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def update(self, source: Source) -> Source:
        stmt = select(SourceModel).where(SourceModel.id == _uuid_to_str(source.id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            raise EntityNotFoundError("Source", str(source.id))

        model.name = source.name
        model.category = source.category.value
        model.type = source.type.value
        model.url = source.url
        model.query = source.query
        model.rate_limit_seconds = source.rate_limit_seconds
        model.enabled = source.enabled
        model.is_quarantined = source.is_quarantined
        model.consecutive_failures = source.consecutive_failures
        model.quarantined_at = source.quarantined_at
        model.quarantine_reason = source.quarantine_reason
        model.last_fetched_at = source.last_fetched_at
        model.last_status = source.last_status.value if source.last_status else None
        model.last_entries_new = source.last_entries_new
        model.config = source.config
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return self._model_to_entity(model)

    async def delete(self, source_id: UUID) -> bool:
        stmt = select(SourceModel).where(SourceModel.id == _uuid_to_str(source_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return False

        await self._session.delete(model)
        return True

    async def toggle_enabled(self, source_id_or_name: str, enabled: bool) -> bool:
        """Enable or disable a source by UUID or name slug."""
        from sqlalchemy import update as sa_update

        # Try by UUID if valid
        try:
            uid_str = _uuid_to_str(UUID(source_id_or_name))
            cond = SourceModel.id == uid_str
        except ValueError:
            cond = or_(
                SourceModel.name == source_id_or_name,
                SourceModel.id.like(f"{source_id_or_name}%"),
            )

        result = await self._session.execute(
            sa_update(SourceModel)
            .where(cond)
            .values(enabled=enabled, updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return bool(getattr(result, "rowcount", 0) > 0)

    def _model_to_entity(self, model: SourceModel) -> Source:
        try:
            cat_enum = Category(model.category)
        except ValueError:
            cat_enum = Category.AI_TECH

        try:
            type_enum = SourceType(model.type)
        except ValueError:
            type_enum = SourceType.RSS

        return Source(
            id=_str_to_uuid(model.id),
            name=model.name,
            category=cat_enum,
            type=type_enum,
            url=model.url or "",
            query=model.query,
            rate_limit_seconds=model.rate_limit_seconds,
            enabled=model.enabled,
            is_quarantined=getattr(model, "is_quarantined", False) or False,
            consecutive_failures=getattr(model, "consecutive_failures", 0) or 0,
            quarantined_at=getattr(model, "quarantined_at", None),
            quarantine_reason=getattr(model, "quarantine_reason", None),
            last_fetched_at=model.last_fetched_at,
            last_status=FetchStatus(model.last_status) if model.last_status else None,
            last_entries_new=model.last_entries_new,
            tier=float((model.config or {}).get("tier", 2.0)),
            config=model.config or {},
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SQLAlchemyFetchLogRepository(FetchLogRepository):
    """SQLAlchemy implementation of FetchLogRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, log: FetchLog) -> FetchLog:
        model = FetchLogModel(
            id=_uuid_to_str(log.id),
            source_id=_uuid_to_str(log.source_id),
            source_name=log.source_name,
            status=log.status.value,
            entries_new=log.entries_new,
            entries_total=log.entries_total,
            error_message=log.error_message,
            duration_ms=log.duration_ms,
            fetched_at=log.fetched_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get_recent(self, hours: int = 24, limit: int = 100) -> list[FetchLog]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(FetchLogModel)
            .where(FetchLogModel.fetched_at >= since)
            .order_by(desc(FetchLogModel.fetched_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def get_by_source(self, source_id: UUID, limit: int = 10) -> list[FetchLog]:
        stmt = (
            select(FetchLogModel)
            .where(FetchLogModel.source_id == _uuid_to_str(source_id))
            .order_by(desc(FetchLogModel.fetched_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def purge_old_logs(self, older_than_days: int = 7) -> int:
        """Delete fetch logs older than retention window."""
        from sqlalchemy import delete as sa_delete

        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        del_res = await self._session.execute(
            sa_delete(FetchLogModel).where(FetchLogModel.fetched_at < cutoff)
        )
        return getattr(del_res, "rowcount", 0) or 0

    def _model_to_entity(self, model: FetchLogModel) -> FetchLog:
        return FetchLog(
            id=_str_to_uuid(model.id),
            source_id=_str_to_uuid(model.source_id),
            source_name=model.source_name,
            status=FetchStatus(model.status),
            entries_new=model.entries_new,
            entries_total=model.entries_total,
            error_message=model.error_message,
            duration_ms=model.duration_ms,
            fetched_at=model.fetched_at,
        )


class SQLAlchemyDigestRepository(DigestRepository):
    """SQLAlchemy implementation of DigestRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, digest: Digest) -> Digest:
        model = DigestModel(
            id=_uuid_to_str(digest.id),
            schedule=digest.schedule,
            entries_by_category=digest.entries_by_category,
            total_entries=digest.total_entries,
            period_start=digest.period_start,
            period_end=digest.period_end,
            delivered=digest.delivered,
            delivery_channels=digest.delivery_channels,
            created_at=digest.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, digest_id: UUID) -> Digest | None:
        stmt = select(DigestModel).where(DigestModel.id == _uuid_to_str(digest_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_latest(self, schedule: str) -> Digest | None:
        stmt = (
            select(DigestModel)
            .where(DigestModel.schedule == schedule)
            .order_by(desc(DigestModel.created_at))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def list(self, limit: int = 10) -> list[Digest]:
        stmt = select(DigestModel).order_by(desc(DigestModel.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def update(self, digest: Digest) -> Digest:
        stmt = select(DigestModel).where(DigestModel.id == _uuid_to_str(digest.id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            raise EntityNotFoundError("Digest", str(digest.id))

        model.entries_by_category = digest.entries_by_category
        model.total_entries = digest.total_entries
        model.delivered = digest.delivered
        model.delivery_channels = digest.delivery_channels

        await self._session.flush()
        return self._model_to_entity(model)

    async def purge_old_digests(self, older_than_days: int = 7) -> int:
        """Delete temporary generated digests older than retention window."""
        from sqlalchemy import delete as sa_delete

        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        del_res = await self._session.execute(
            sa_delete(DigestModel).where(DigestModel.created_at < cutoff)
        )
        return getattr(del_res, "rowcount", 0) or 0

    def _model_to_entity(self, model: DigestModel) -> Digest:
        return Digest(
            id=_str_to_uuid(model.id),
            schedule=model.schedule,
            entries_by_category=model.entries_by_category or {},
            total_entries=model.total_entries,
            period_start=model.period_start,
            period_end=model.period_end,
            delivered=model.delivered,
            delivery_channels=model.delivery_channels or [],
            created_at=model.created_at,
        )


class SQLAlchemyWatchlistRepository:
    """SQLAlchemy implementation of Watchlist rules repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, rule: WatchlistRule) -> WatchlistRule:
        model = WatchlistRuleModel(
            id=_uuid_to_str(rule.id),
            name=rule.name,
            keywords=rule.keywords,
            categories=[
                c.value if hasattr(c, "value") else str(c) for c in rule.categories
            ],
            min_threat_velocity=rule.min_threat_velocity,
            enabled=rule.enabled,
            created_at=rule.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, rule_id: UUID) -> WatchlistRule | None:
        stmt = select(WatchlistRuleModel).where(
            WatchlistRuleModel.id == _uuid_to_str(rule_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def list(self, enabled_only: bool = False) -> list[WatchlistRule]:
        stmt = select(WatchlistRuleModel).order_by(desc(WatchlistRuleModel.created_at))
        if enabled_only:
            stmt = stmt.where(WatchlistRuleModel.enabled.is_(True))
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def delete(self, rule_id: UUID) -> bool:
        stmt = select(WatchlistRuleModel).where(
            WatchlistRuleModel.id == _uuid_to_str(rule_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def toggle(self, rule_id: UUID, enabled: bool) -> WatchlistRule:
        stmt = select(WatchlistRuleModel).where(
            WatchlistRuleModel.id == _uuid_to_str(rule_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("WatchlistRule", str(rule_id))
        model.enabled = enabled
        await self._session.flush()
        return self._model_to_entity(model)

    def _model_to_entity(self, model: WatchlistRuleModel) -> WatchlistRule:
        return WatchlistRule(
            id=_str_to_uuid(model.id),
            name=model.name,
            keywords=model.keywords or [],
            categories=[
                Category(c)
                for c in (model.categories or [])
                if c in [cat.value for cat in Category]
            ],
            min_threat_velocity=model.min_threat_velocity or 0,
            enabled=model.enabled,
            created_at=model.created_at,
        )


class SQLAlchemyReceiptRepository(LLMReceiptRepository):
    """SQLAlchemy implementation of LLMReceiptRepository for idempotent model calls."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _model_to_entity(self, model: ReceiptModel) -> LLMReceipt:
        return LLMReceipt(
            id=_str_to_uuid(model.id),
            logical_key=model.logical_key,
            entry_id=_str_to_uuid(model.entry_id) if model.entry_id else None,
            provider=model.provider,
            model=model.model,
            prompt_version=model.prompt_version,
            status=model.status,
            attempts=model.attempts,
            max_attempts=model.max_attempts,
            response_json=model.response_json,
            error_message=model.error_message,
            execution_tier=getattr(model, "execution_tier", None),
            cache_read_input_tokens=getattr(model, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(model, "cache_creation_input_tokens", 0)
            or 0,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def get_by_key(self, logical_key: str) -> LLMReceipt | None:
        stmt = select(ReceiptModel).where(ReceiptModel.logical_key == logical_key)
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_entry(self, entry_id: UUID) -> list[LLMReceipt]:
        stmt = (
            select(ReceiptModel)
            .where(ReceiptModel.entry_id == _uuid_to_str(entry_id))
            .order_by(desc(ReceiptModel.created_at))
        )
        res = await self._session.execute(stmt)
        return [self._model_to_entity(m) for m in res.scalars()]

    async def record_attempt(
        self,
        logical_key: str,
        provider: str,
        model: str,
        prompt_version: str,
        entry_id: UUID | None = None,
        max_attempts: int = 3,
    ) -> tuple[LLMReceipt, bool]:
        """Record an attempt. Returns (receipt, should_execute)."""
        stmt = select(ReceiptModel).where(ReceiptModel.logical_key == logical_key)
        res = await self._session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing is None:
            new_model = ReceiptModel(
                logical_key=logical_key,
                entry_id=_uuid_to_str(entry_id) if entry_id else None,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                status="pending",
                attempts=1,
                max_attempts=max_attempts,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._session.add(new_model)
            await self._session.flush()
            return self._model_to_entity(new_model), True

        # Existing receipt: if succeeded, do not re-execute
        if existing.status == "succeeded":
            return self._model_to_entity(existing), False

        # If failed and retry limit reached: poison entry, do not re-execute
        if existing.status == "failed" and existing.attempts >= existing.max_attempts:
            return self._model_to_entity(existing), False

        # Otherwise increment attempt count and set pending
        existing.attempts += 1
        existing.status = "pending"
        existing.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._model_to_entity(existing), True

    async def record_success(
        self,
        logical_key: str,
        response_json: dict[str, Any],
        execution_tier: str | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> LLMReceipt:
        stmt = select(ReceiptModel).where(ReceiptModel.logical_key == logical_key)
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("ReceiptModel", logical_key)

        model.status = "succeeded"
        model.response_json = response_json
        model.error_message = None
        if execution_tier is not None:
            model.execution_tier = execution_tier
        if cache_read_input_tokens:
            model.cache_read_input_tokens = cache_read_input_tokens
        if cache_creation_input_tokens:
            model.cache_creation_input_tokens = cache_creation_input_tokens
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._model_to_entity(model)

    async def record_failure(
        self,
        logical_key: str,
        error_message: str,
    ) -> LLMReceipt:
        stmt = select(ReceiptModel).where(ReceiptModel.logical_key == logical_key)
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("ReceiptModel", logical_key)

        model.status = "failed"
        model.error_message = error_message[:2000] if error_message else None
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get_tier_stats(self) -> dict[str, Any]:
        """Aggregate counts and token savings across SLM and prompt caching tiers."""
        stmt = select(
            ReceiptModel.execution_tier,
            func.count(ReceiptModel.id),
            func.sum(ReceiptModel.cache_read_input_tokens),
            func.sum(ReceiptModel.cache_creation_input_tokens),
        ).group_by(ReceiptModel.execution_tier)
        res = await self._session.execute(stmt)

        tier_counts: dict[str, int] = {}
        total_cache_read = 0
        total_cache_creation = 0

        for tier, count, cache_read, cache_create in res.all():
            t_key = tier or "unspecified"
            tier_counts[t_key] = count
            total_cache_read += int(cache_read or 0)
            total_cache_creation += int(cache_create or 0)

        return {
            "tier_counts": tier_counts,
            "local_slm_count": tier_counts.get("local_slm", 0),
            "cloud_cached_count": tier_counts.get("cloud_cached", 0),
            "cloud_uncached_count": tier_counts.get("cloud_uncached", 0),
            "total_cache_read_tokens": total_cache_read,
            "total_cache_creation_tokens": total_cache_creation,
        }


class SQLAlchemyEntityRepository(AIEntityRepository):
    """SQLAlchemy implementation of AIEntityRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _model_to_entity(self, model: EntryEntityModel) -> AIEntity:
        try:
            e_type = EntityType(model.entity_type)
        except ValueError:
            e_type = EntityType.MODEL
        return AIEntity(
            id=_str_to_uuid(model.id),
            entry_id=_str_to_uuid(model.entry_id),
            entity_type=e_type,
            name=model.name,
            display_name=model.display_name,
            metric_value=model.metric_value,
            context=model.context,
            confidence=model.confidence,
            created_at=model.created_at,
        )

    async def add_all(self, entities: list[AIEntity]) -> list[AIEntity]:
        """Persist a list of extracted entities, updating duplicates idempotently."""
        if not entities:
            return []

        models: list[EntryEntityModel] = []
        for ent in entities:
            type_str = (
                ent.entity_type.value
                if hasattr(ent.entity_type, "value")
                else str(ent.entity_type)
            )
            stmt = select(EntryEntityModel).where(
                EntryEntityModel.entry_id == _uuid_to_str(ent.entry_id),
                EntryEntityModel.entity_type == type_str,
                EntryEntityModel.name == ent.name,
            )
            res = await self._session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                if ent.metric_value:
                    existing.metric_value = ent.metric_value
                if ent.context:
                    existing.context = ent.context
                models.append(existing)
            else:
                new_m = EntryEntityModel(
                    id=_uuid_to_str(ent.id),
                    entry_id=_uuid_to_str(ent.entry_id),
                    entity_type=type_str,
                    name=ent.name,
                    display_name=ent.display_name,
                    metric_value=ent.metric_value,
                    context=ent.context,
                    confidence=ent.confidence,
                    created_at=ent.created_at or datetime.now(UTC),
                )
                self._session.add(new_m)
                models.append(new_m)

        await self._session.flush()
        return [self._model_to_entity(m) for m in models]

    async def get_by_entry(self, entry_id: UUID) -> list[AIEntity]:
        """Retrieve all entities for a specific entry."""
        stmt = (
            select(EntryEntityModel)
            .where(EntryEntityModel.entry_id == _uuid_to_str(entry_id))
            .order_by(EntryEntityModel.created_at.asc())
        )
        res = await self._session.execute(stmt)
        return [self._model_to_entity(m) for m in res.scalars()]

    async def query_timeline(
        self,
        name: str | None = None,
        entity_type: EntityType | str | None = None,
        days: int = 14,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query chronological timeline of mentions across the freshness window (max 14 days)."""
        safe_days = min(max(1, days), 14)
        since_date = datetime.now(UTC) - timedelta(days=safe_days)

        stmt = (
            select(EntryEntityModel, EntryModel)
            .join(EntryModel, EntryEntityModel.entry_id == EntryModel.id)
            .where(EntryModel.published_at >= since_date)
            .order_by(EntryModel.published_at.desc())
            .limit(min(limit, 100))
        )

        if name:
            clean_name = name.strip().lower()
            stmt = stmt.where(
                or_(
                    EntryEntityModel.name == clean_name,
                    EntryEntityModel.name.contains(clean_name),
                    EntryEntityModel.display_name.contains(name.strip()),
                )
            )

        if entity_type:
            type_val = (
                entity_type.value if hasattr(entity_type, "value") else str(entity_type)
            )
            stmt = stmt.where(EntryEntityModel.entity_type == type_val)

        res = await self._session.execute(stmt)
        timeline: list[dict[str, Any]] = []
        for ent_m, entry_m in res.all():
            timeline.append(
                {
                    "entity_id": ent_m.id,
                    "entry_id": entry_m.id,
                    "entity_type": ent_m.entity_type,
                    "name": ent_m.name,
                    "display_name": ent_m.display_name,
                    "metric_value": ent_m.metric_value,
                    "context": ent_m.context,
                    "confidence": ent_m.confidence,
                    "entry_title": entry_m.title,
                    "entry_url": entry_m.url,
                    "category": entry_m.category,
                    "published_at": entry_m.published_at.isoformat()
                    if entry_m.published_at
                    else None,
                }
            )
        return timeline

    async def get_top_entities(
        self,
        entity_type: EntityType | str | None = None,
        days: int = 14,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve top referenced entities grouped by name within the freshness window."""
        safe_days = min(max(1, days), 14)
        since_date = datetime.now(UTC) - timedelta(days=safe_days)

        stmt = (
            select(
                EntryEntityModel.name,
                EntryEntityModel.display_name,
                EntryEntityModel.entity_type,
                func.count(EntryEntityModel.id).label("mention_count"),
                func.max(EntryEntityModel.created_at).label("latest_mention_at"),
            )
            .join(EntryModel, EntryEntityModel.entry_id == EntryModel.id)
            .where(EntryModel.published_at >= since_date)
            .group_by(
                EntryEntityModel.name,
                EntryEntityModel.display_name,
                EntryEntityModel.entity_type,
            )
            .order_by(desc("mention_count"))
            .limit(min(limit, 50))
        )

        if entity_type:
            type_val = (
                entity_type.value if hasattr(entity_type, "value") else str(entity_type)
            )
            stmt = stmt.where(EntryEntityModel.entity_type == type_val)

        res = await self._session.execute(stmt)
        top_list: list[dict[str, Any]] = []
        for row in res.all():
            top_list.append(
                {
                    "name": row[0],
                    "display_name": row[1],
                    "entity_type": row[2],
                    "mention_count": int(row[3]),
                    "latest_mention_at": row[4].isoformat() if row[4] else None,
                }
            )
        return top_list
