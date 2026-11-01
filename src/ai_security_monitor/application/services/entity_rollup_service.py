"""
Entity Rollup and Momentum Service (Workstream B1).

Aggregates daily mention counts for structured AI ecosystem entities into
`entity_daily_counts` and computes 3-day vs 28-day momentum z-scores with
14-day trajectory sparklines.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from ai_security_monitor.application.services.ai_entity_extractor import (
    AIEntityExtractor,
)
from ai_security_monitor.domain.entities import EntityType
from ai_security_monitor.infrastructure.database.models import (
    EntityDailyCountModel,
    EntryEntityModel,
    EntryModel,
    generate_uuid,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = logging.getLogger(__name__)

# Exclude CVEs in accordance with the pure AI Ecosystem directive
DEFAULT_ALLOWED_TYPES = {
    EntityType.MODEL.value,
    EntityType.REPOSITORY.value,
    EntityType.BENCHMARK.value,
    EntityType.ORGANIZATION.value,
    EntityType.HARDWARE.value,
    EntityType.ARXIV.value,
}


class EntityRollupService:
    """Service for managing daily entity rollups and momentum z-score analytics."""

    def __init__(
        self, uow_factory: type[SqlAlchemyUnitOfWork] = SqlAlchemyUnitOfWork
    ) -> None:
        self._uow_factory = uow_factory

    async def backfill_entities_if_empty(self, days: int = 30) -> int:
        """
        Backfill entry_entities table from unpurged entries across the past N days
        if entry_entities currently contains no records.
        """
        async with self._uow_factory() as uow:
            count_stmt = select(func.count(EntryEntityModel.id))
            existing_count = (await uow.session.execute(count_stmt)).scalar() or 0
            if existing_count > 0:
                return 0

            cutoff = datetime.now(UTC) - timedelta(days=days)
            entries_stmt = (
                select(EntryModel)
                .where(EntryModel.is_purged.is_(False))
                .where(
                    or_(
                        EntryModel.published_at >= cutoff,
                        EntryModel.fetched_at >= cutoff,
                    )
                )
                .order_by(EntryModel.published_at.desc())
            )
            res = await uow.session.execute(entries_stmt)
            entries = res.scalars().all()

            extracted_total = 0
            for entry in entries:
                text = f"{entry.title}\n{entry.summary or ''}"
                extracted = AIEntityExtractor.extract_from_text(text, UUID(entry.id))
                # Only keep AI ecosystem entities (no CVEs)
                filtered = [
                    e
                    for e in extracted
                    if (
                        e.entity_type.value
                        if hasattr(e.entity_type, "value")
                        else str(e.entity_type)
                    )
                    in DEFAULT_ALLOWED_TYPES
                ]
                if filtered:
                    await uow.entities.add_all(filtered)
                    extracted_total += len(filtered)

            logger.info(
                f"Backfilled {extracted_total} AI knowledge graph entities across {len(entries)} entries."
            )
            return extracted_total

    async def aggregate_daily_counts(self, days: int = 30) -> int:
        """
        Aggregate entry_entities joined with entries into daily mention buckets
        and upsert into entity_daily_counts.
        """
        # Ensure base entities exist if starting fresh
        await self.backfill_entities_if_empty(days=days)

        cutoff_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

        async with self._uow_factory() as uow:
            # Bucket date derived from published_at, fetched_at, or created_at
            bucket_expr = func.substr(
                func.coalesce(
                    EntryModel.published_at,
                    EntryModel.fetched_at,
                    EntryEntityModel.created_at,
                ),
                1,
                10,
            )

            stmt = (
                select(
                    EntryEntityModel.name,
                    EntryEntityModel.entity_type,
                    EntryEntityModel.display_name,
                    bucket_expr.label("bucket_date"),
                    func.count(EntryEntityModel.id).label("mention_count"),
                )
                .join(EntryModel, EntryEntityModel.entry_id == EntryModel.id)
                .where(EntryEntityModel.entity_type.in_(DEFAULT_ALLOWED_TYPES))
                .where(bucket_expr >= cutoff_date)
                .group_by(
                    EntryEntityModel.name,
                    EntryEntityModel.entity_type,
                    EntryEntityModel.display_name,
                    bucket_expr,
                )
            )

            res = await uow.session.execute(stmt)
            rows = res.all()

            upserted_count = 0
            now = datetime.now(UTC)

            for name, e_type, display_name, b_date, count in rows:
                if not b_date or len(b_date) != 10:
                    continue

                existing_stmt = select(EntityDailyCountModel).where(
                    EntityDailyCountModel.entity_name == name,
                    EntityDailyCountModel.entity_type == e_type,
                    EntityDailyCountModel.bucket_date == b_date,
                )
                existing_res = await uow.session.execute(existing_stmt)
                existing = existing_res.scalar_one_or_none()

                if existing:
                    existing.mention_count = int(count)
                    existing.display_name = display_name
                    existing.updated_at = now
                else:
                    new_count = EntityDailyCountModel(
                        id=generate_uuid(),
                        entity_name=name,
                        entity_type=e_type,
                        display_name=display_name,
                        bucket_date=b_date,
                        mention_count=int(count),
                        created_at=now,
                        updated_at=now,
                    )
                    uow.session.add(new_count)

                upserted_count += 1

            await uow.commit()
            logger.info(
                f"Aggregated {upserted_count} daily entity count buckets for past {days} days."
            )
            return upserted_count

    async def calculate_momentum_z_scores(
        self,
        entity_type: str | None = None,
        limit: int = 20,
        min_3d_mentions: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Compute momentum z-scores comparing 3-day recent volume against a 28-day baseline.

        Returns ranked entities with 14-day sparklines and momentum trajectory classifications:
        - surging: z >= 2.0
        - rising:  1.0 <= z < 2.0
        - cooling: z <= -1.0
        - steady:  -1.0 < z < 1.0
        """
        today = datetime.now(UTC).date()
        date_list_28 = [
            (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(27, -1, -1)
        ]
        start_date_28d = date_list_28[0]
        date_list_14 = date_list_28[-14:]
        date_set_3d = set(date_list_28[-3:])

        async with self._uow_factory() as uow:
            # Check if any daily counts exist
            check_stmt = select(func.count(EntityDailyCountModel.id))
            total_records = (await uow.session.execute(check_stmt)).scalar() or 0

        if total_records == 0:
            await self.aggregate_daily_counts(days=30)

        async with self._uow_factory() as uow:
            stmt = select(EntityDailyCountModel).where(
                EntityDailyCountModel.bucket_date >= start_date_28d,
                EntityDailyCountModel.entity_type.in_(DEFAULT_ALLOWED_TYPES),
            )
            if entity_type and entity_type.strip():
                stmt = stmt.where(
                    EntityDailyCountModel.entity_type == entity_type.strip().lower()
                )

            res = await uow.session.execute(stmt)
            records = res.scalars().all()

        # Group counts by (entity_name, entity_type)
        entities_data: dict[tuple[str, str], dict[str, Any]] = {}

        for rec in records:
            key = (rec.entity_name, rec.entity_type)
            if key not in entities_data:
                entities_data[key] = {
                    "display_name": rec.display_name,
                    "counts": {},
                }
            entities_data[key]["counts"][rec.bucket_date] = rec.mention_count

        candidates: list[dict[str, Any]] = []

        for (name, e_type), data in entities_data.items():
            counts_map: dict[str, int] = data["counts"]
            display_name: str = data["display_name"]

            # Construct 28-day series (0 for days without mentions)
            c_28 = [counts_map.get(d, 0) for d in date_list_28]
            count_28d = sum(c_28)

            # Recent 3-day count
            count_3d = sum(counts_map.get(d, 0) for d in date_set_3d)

            if count_3d < min_3d_mentions:
                continue

            # Statistical baseline
            mu_28d = count_28d / 28.0
            var_28d = sum((c - mu_28d) ** 2 for c in c_28) / 28.0
            std_28d = math.sqrt(var_28d)

            # Expected 3-day sum and std deviation
            expected_3d = 3.0 * mu_28d
            std_3d = math.sqrt(3.0) * std_28d

            # Epsilon = 0.1 prevents division by zero while preserving responsiveness
            z_score = (count_3d - expected_3d) / (std_3d + 0.1)

            if z_score >= 2.0:
                label = "surging"
            elif z_score >= 1.0:
                label = "rising"
            elif z_score <= -1.0:
                label = "cooling"
            else:
                label = "steady"

            sparkline_14d = [counts_map.get(d, 0) for d in date_list_14]

            candidates.append(
                {
                    "entity_name": name,
                    "display_name": display_name,
                    "entity_type": e_type,
                    "count_3d": count_3d,
                    "count_28d": count_28d,
                    "mean_daily_28d": round(mu_28d, 2),
                    "std_daily_28d": round(std_28d, 2),
                    "z_score": round(z_score, 2),
                    "momentum_label": label,
                    "sparkline_14d": sparkline_14d,
                }
            )

        # Sort primarily by z_score descending, secondary by count_3d descending
        candidates.sort(key=lambda x: (x["z_score"], x["count_3d"]), reverse=True)
        return candidates[:limit]
