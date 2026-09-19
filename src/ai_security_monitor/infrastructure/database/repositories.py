"""
Repository implementations using SQLAlchemy async.
Implements the domain repository interfaces.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Digest,
    Entry,
    FetchLog,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.domain.exceptions import (
    DuplicateEntryError,
    EntityNotFoundError,
)
from ai_security_monitor.domain.repositories import (
    AnalysisRepository,
    DigestRepository,
    EntryFilters,
    EntryRepository,
    FetchLogRepository,
    PaginationParams,
    SourceRepository,
)
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.infrastructure.database.models import (
    AnalysisModel as AnalysisModelDB,
)
from ai_security_monitor.infrastructure.database.models import (
    DigestModel,
    EntryModel,
    FetchLogModel,
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
        await self._session.flush()
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
        stmt = select(EntryModel.content_hash).where(EntryModel.content_hash.in_(hashes))
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

    async def delete(self, entry_id: UUID) -> bool:
        stmt = select(EntryModel).where(EntryModel.id == _uuid_to_str(entry_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return False

        await self._session.delete(model)
        return True

    async def get_unanalyzed(
        self,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[Entry]:
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
    ) -> int:
        """Purge entries older than retention window.

        - If older_than_days == 0: targets all active entries up to current time.
        - If include_vaulted == False: entries marked as important/saved/pinned are preserved.
        - If include_vaulted == True: all entries matching the time window (including vault) are purged.
        - If hard_delete == True: records and their analyses are permanently deleted from database disk.
        - If hard_delete == False: records are marked soft-deleted (is_purged=True, purged_at=now).

        Returns the number of rows purged.
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import not_
        from sqlalchemy import update as sa_update

        # Time condition
        if older_than_days == 0:
            time_cond = True
        else:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            time_cond = or_(
                EntryModel.fetched_at < cutoff,
                and_(
                    EntryModel.published_at.is_not(None),
                    EntryModel.published_at < cutoff,
                ),
            )

        conds = [EntryModel.is_purged.is_(False)]
        if time_cond is not True:
            conds.append(time_cond)

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
            return del_result.rowcount or 0

        soft_del_result = await self._session.execute(
            sa_update(EntryModel)
            .where(expired_cond)
            .values(is_purged=True, purged_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return soft_del_result.rowcount or 0

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
        return del_result.rowcount or 0

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
        return result.rowcount or 0

    async def get_retention_counts(
        self,
        older_than_days: int = 7,
        include_vaulted: bool = False,
    ) -> dict[str, int]:
        """Get counts of active entries, candidate entries older than X days, and soft-purged entries."""
        active_stmt = select(func.count(EntryModel.id)).where(
            EntryModel.is_purged.is_(False)
        )
        active_res = await self._session.execute(active_stmt)
        active_count = active_res.scalar() or 0

        purged_stmt = select(func.count(EntryModel.id)).where(
            EntryModel.is_purged.is_(True)
        )
        purged_res = await self._session.execute(purged_stmt)
        purged_count = purged_res.scalar() or 0

        from sqlalchemy import not_

        if older_than_days == 0:
            time_cond = True
        else:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            time_cond = or_(
                EntryModel.fetched_at < cutoff,
                and_(
                    EntryModel.published_at.is_not(None),
                    EntryModel.published_at < cutoff,
                ),
            )

        conds = [EntryModel.is_purged.is_(False)]
        if time_cond is not True:
            conds.append(time_cond)

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
    ) -> list[Entry]:
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
        # Exclude soft-deleted entries by default
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
                stmt = stmt.where(
                    SourceModel.config.like(f'%"region": "{filters.region}"%')
                )

        if filters.country and filters.country != "all":
            if not source_joined:
                stmt = stmt.join(SourceModel, EntryModel.source_id == SourceModel.id)
                source_joined = True
            c_code = filters.country.upper()
            stmt = stmt.where(SourceModel.config.like(f'%"country": "{c_code}"%'))

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
                created_at=model.analysis.created_at,
                updated_at=model.analysis.updated_at,
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
            category=Category(model.category),
            tags=model.tags or [],
            metadata=model.extra_metadata or {},
            created_at=model.created_at,
            updated_at=model.updated_at,
            analysis=analysis,
            is_purged=bool(getattr(model, "is_purged", False)),
            purged_at=getattr(model, "purged_at", None),
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
            model=AnalysisModel(model.model),
            confidence=model.confidence,
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
        stmt = select(SourceModel).where(SourceModel.name == name)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
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

    def _model_to_entity(self, model: SourceModel) -> Source:
        return Source(
            id=_str_to_uuid(model.id),
            name=model.name,
            category=Category(model.category),
            type=SourceType(model.type),
            url=model.url,
            query=model.query,
            rate_limit_seconds=model.rate_limit_seconds,
            enabled=model.enabled,
            last_fetched_at=model.last_fetched_at,
            last_status=FetchStatus(model.last_status) if model.last_status else None,
            last_entries_new=model.last_entries_new,
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
        return del_res.rowcount or 0

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
        return del_res.rowcount or 0

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
