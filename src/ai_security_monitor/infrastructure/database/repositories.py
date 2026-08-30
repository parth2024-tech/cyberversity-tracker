"""
Repository implementations using SQLAlchemy async.
Implements the domain repository interfaces.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, func, or_, select
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
from ai_security_monitor.domain.watchlist import WatchlistRule
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
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, entry_id: UUID) -> Entry | None:
        stmt = select(EntryModel).where(EntryModel.id == _uuid_to_str(entry_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_content_hash(self, content_hash: str) -> Entry | None:
        stmt = select(EntryModel).where(EntryModel.content_hash == content_hash)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def list(
        self,
        filters: EntryFilters | None = None,
        pagination: PaginationParams | None = None,
    ) -> list[Entry]:
        stmt = select(EntryModel).options(selectinload(EntryModel.analysis))

        if filters:
            stmt = self._apply_filters(stmt, filters)

        if filters and filters.sort_by == "velocity":
            stmt = stmt.outerjoin(AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id).order_by(
                desc(AnalysisModelDB.threat_velocity),
                desc(EntryModel.published_at)
            )
        elif filters and filters.sort_by == "blast":
            stmt = stmt.outerjoin(AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id).order_by(
                desc(AnalysisModelDB.blast_radius_score),
                desc(EntryModel.published_at)
            )
        elif filters and filters.sort_by == "severity":
            stmt = stmt.outerjoin(AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id).order_by(
                desc(AnalysisModelDB.severity_index),
                desc(EntryModel.published_at)
            )
        else:
            stmt = stmt.order_by(desc(EntryModel.published_at))

        if pagination:
            stmt = stmt.limit(pagination.limit).offset(pagination.offset)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def count(self, filters: EntryFilters | None = None) -> int:
        stmt = select(func.count(EntryModel.id))

        if filters:
            stmt = self._apply_filters(stmt, filters)

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
        model.updated_at = datetime.utcnow()

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
        )

        if since:
            stmt = stmt.where(EntryModel.published_at >= since)

        stmt = stmt.order_by(desc(EntryModel.published_at)).limit(limit)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    async def purge_old_entries(self, older_than_days: int = 30) -> int:
        """Delete entries (and their cascaded analyses) older than `older_than_days` days.

        Returns the number of rows purged.
        """
        from sqlalchemy import delete as sa_delete

        cutoff = datetime.utcnow() - timedelta(days=older_than_days)

        # Fetch IDs to purge first (so cascade to analyses works via ORM delete)
        stmt = select(EntryModel.id).where(EntryModel.published_at < cutoff)
        result = await self._session.execute(stmt)
        old_ids = [row[0] for row in result.fetchall()]

        if not old_ids:
            return 0

        # Delete associated analyses first (avoid FK constraint errors if no cascade)
        await self._session.execute(
            sa_delete(AnalysisModelDB).where(AnalysisModelDB.entry_id.in_(old_ids))
        )
        # Delete the entries themselves
        del_result = await self._session.execute(
            sa_delete(EntryModel).where(EntryModel.id.in_(old_ids))
        )
        return del_result.rowcount or len(old_ids)

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
        )

        if since:
            stmt = stmt.where(EntryModel.published_at >= since)

        stmt = stmt.order_by(desc(EntryModel.published_at)).limit(limit)

        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._model_to_entity(m) for m in models]

    def _apply_filters(self, stmt, filters: EntryFilters):
        if filters.category:
            stmt = stmt.where(EntryModel.category == filters.category.value)

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

        if filters.pre_cve_only:
            stmt = stmt.join(AnalysisModelDB).where(AnalysisModelDB.is_pre_cve_warning.is_(True))

        if filters.high_velocity_only:
            stmt = stmt.join(AnalysisModelDB).where(AnalysisModelDB.threat_velocity >= 70)

        if filters.analyzed_only:
            stmt = stmt.join(AnalysisModelDB).where(AnalysisModelDB.entry_id.is_not(None))

        if filters.unanalyzed_only:
            stmt = stmt.outerjoin(AnalysisModelDB).where(AnalysisModelDB.entry_id.is_(None))

        if filters.region and filters.region != "all":
            if filters.region.lower() in ("china", "cn"):
                stmt = stmt.join(SourceModel, EntryModel.source_id == SourceModel.id).where(
                    or_(
                        SourceModel.config.like('%"region": "china"%'),
                        SourceModel.config.like('%"country": "CN"%'),
                        SourceModel.config.like('%"country": "HK"%'),
                    )
                )
            else:
                stmt = stmt.join(SourceModel, EntryModel.source_id == SourceModel.id).where(
                    SourceModel.config.like(f'%"region": "{filters.region}"%')
                )

        return stmt

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
                model=AnalysisModel(model.analysis.model) if model.analysis.model in [m.value for m in AnalysisModel] else AnalysisModel.HEURISTIC,
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
            weaponization_potential=analysis.weaponization_potential,
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
        stmt = select(AnalysisModelDB).where(AnalysisModelDB.entry_id == _uuid_to_str(entry_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def get_by_entry(self, entry_id: UUID) -> Analysis | None:
        return await self.get(entry_id)

    async def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        stmt = select(AnalysisModelDB).where(AnalysisModelDB.id == _uuid_to_str(analysis_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._model_to_entity(model) if model else None

    async def update(self, analysis: Analysis) -> Analysis:
        stmt = select(AnalysisModelDB).where(AnalysisModelDB.id == _uuid_to_str(analysis.id))
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
        model.weaponization_potential = analysis.weaponization_potential
        model.mitre_attack_id = analysis.mitre_attack_id
        model.mitre_technique = analysis.mitre_technique
        model.model = analysis.model.value
        model.confidence = analysis.confidence
        model.updated_at = datetime.utcnow()

        await self._session.flush()
        return self._model_to_entity(model)

    async def delete(self, entry_id: UUID) -> bool:
        stmt = select(AnalysisModelDB).where(AnalysisModelDB.entry_id == _uuid_to_str(entry_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return False

        await self._session.delete(model)
        return True

    async def count_high_velocity(self, threshold: int = 70) -> int:
        stmt = select(func.count(AnalysisModelDB.id)).where(AnalysisModelDB.threat_velocity >= threshold)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def count_pre_cve_warnings(self) -> int:
        stmt = select(func.count(AnalysisModelDB.id)).where(AnalysisModelDB.is_pre_cve_warning.is_(True))
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
        model.updated_at = datetime.utcnow()

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
        since = datetime.utcnow() - timedelta(hours=hours)
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
            categories=[c.value if hasattr(c, "value") else str(c) for c in rule.categories],
            min_threat_velocity=rule.min_threat_velocity,
            enabled=rule.enabled,
            created_at=rule.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._model_to_entity(model)

    async def get(self, rule_id: UUID) -> WatchlistRule | None:
        stmt = select(WatchlistRuleModel).where(WatchlistRuleModel.id == _uuid_to_str(rule_id))
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
        stmt = select(WatchlistRuleModel).where(WatchlistRuleModel.id == _uuid_to_str(rule_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def toggle(self, rule_id: UUID, enabled: bool) -> WatchlistRule:
        stmt = select(WatchlistRuleModel).where(WatchlistRuleModel.id == _uuid_to_str(rule_id))
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
            categories=[Category(c) for c in (model.categories or []) if c in [cat.value for cat in Category]],
            min_threat_velocity=model.min_threat_velocity or 0,
            enabled=model.enabled,
            created_at=model.created_at,
        )

