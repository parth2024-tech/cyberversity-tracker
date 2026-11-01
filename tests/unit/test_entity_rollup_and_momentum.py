"""
Unit tests for Entity Rollup & Momentum Radar (Workstream B1).
Verifies:
1. Pre-aggregated daily rollup creation and upsert idempotency.
2. 3-day vs 28-day momentum z-score calculations, labeling (surging/rising/steady/cooling),
   and 14-day sparkline vector integrity.
3. Pure AI ecosystem scope (CVEs excluded).
4. REST API endpoints /api/entities/momentum and /api/entities/rollup/refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from ai_security_monitor.application.services.entity_rollup_service import (
    EntityRollupService,
)
from ai_security_monitor.domain.entities import EntityType
from ai_security_monitor.infrastructure.database.models import (
    EntityDailyCountModel,
    EntryEntityModel,
    EntryModel,
    SourceModel,
    generate_uuid,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app


@pytest.fixture(autouse=True)
async def cleanup_entity_tables():
    """Ensure clean test slate before and after each test."""
    async with SqlAlchemyUnitOfWork() as uow:
        await uow.session.execute(delete(EntityDailyCountModel))
        await uow.session.execute(delete(EntryEntityModel))
        await uow.session.execute(delete(EntryModel))
        await uow.session.execute(delete(SourceModel))
        await uow.commit()
    yield
    async with SqlAlchemyUnitOfWork() as uow:
        await uow.session.execute(delete(EntityDailyCountModel))
        await uow.session.execute(delete(EntryEntityModel))
        await uow.session.execute(delete(EntryModel))
        await uow.session.execute(delete(SourceModel))
        await uow.commit()


@pytest.mark.asyncio
async def test_entity_rollup_aggregation_and_idempotency():
    """Verify daily mention rollups correctly aggregate and update idempotently."""
    rollup_svc = EntityRollupService()

    today = datetime.now(UTC).date()
    date_yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    date_today = today.strftime("%Y-%m-%d")

    async with SqlAlchemyUnitOfWork() as uow:
        # Create a source
        src = SourceModel(
            id=str(uuid4()),
            name="test_src_rollup",
            category="ai_models",
            type="rss",
            rate_limit_seconds=60,
        )
        uow.session.add(src)

        # Create 2 entries for yesterday and 1 entry for today
        e1 = EntryModel(
            id=str(uuid4()),
            source_id=src.id,
            title="DeepSeek-R1 Released",
            url="https://example.com/1",
            content_hash="h1" * 32,
            published_at=datetime.strptime(
                f"{date_yesterday} 10:00:00", "%Y-%m-%d %H:%M:%S"
            ),
            category="ai_models",
        )
        e2 = EntryModel(
            id=str(uuid4()),
            source_id=src.id,
            title="DeepSeek-R1 Architecture Notes",
            url="https://example.com/2",
            content_hash="h2" * 32,
            published_at=datetime.strptime(
                f"{date_yesterday} 14:00:00", "%Y-%m-%d %H:%M:%S"
            ),
            category="ai_models",
        )
        e3 = EntryModel(
            id=str(uuid4()),
            source_id=src.id,
            title="DeepSeek-R1 Benchmarking Today",
            url="https://example.com/3",
            content_hash="h3" * 32,
            published_at=datetime.strptime(
                f"{date_today} 08:00:00", "%Y-%m-%d %H:%M:%S"
            ),
            category="ai_models",
        )
        uow.session.add_all([e1, e2, e3])

        # Link AIEntity mentions for DeepSeek-R1
        ent1 = EntryEntityModel(
            id=str(uuid4()),
            entry_id=e1.id,
            entity_type=EntityType.MODEL.value,
            name="deepseek-r1",
            display_name="DeepSeek-R1",
            confidence=1.0,
        )
        ent2 = EntryEntityModel(
            id=str(uuid4()),
            entry_id=e2.id,
            entity_type=EntityType.MODEL.value,
            name="deepseek-r1",
            display_name="DeepSeek-R1",
            confidence=1.0,
        )
        ent3 = EntryEntityModel(
            id=str(uuid4()),
            entry_id=e3.id,
            entity_type=EntityType.MODEL.value,
            name="deepseek-r1",
            display_name="DeepSeek-R1",
            confidence=1.0,
        )
        # Link a CVE entity (which must be filtered out)
        ent_cve = EntryEntityModel(
            id=str(uuid4()),
            entry_id=e1.id,
            entity_type=EntityType.CVE.value,
            name="cve-2026-9999",
            display_name="CVE-2026-9999",
            confidence=1.0,
        )
        uow.session.add_all([ent1, ent2, ent3, ent_cve])
        await uow.commit()

    # First aggregation pass
    count_pass1 = await rollup_svc.aggregate_daily_counts(days=7)
    assert count_pass1 >= 2  # yesterday + today for deepseek-r1

    async with SqlAlchemyUnitOfWork() as uow:
        rows = (
            (
                await uow.session.execute(
                    select(EntityDailyCountModel).order_by(
                        EntityDailyCountModel.bucket_date
                    )
                )
            )
            .scalars()
            .all()
        )

        # CVE must NOT be in the rollup
        cve_rows = [r for r in rows if r.entity_type == "cve"]
        assert len(cve_rows) == 0

        # Verify DeepSeek counts: 2 for yesterday, 1 for today
        ds_rows = {
            r.bucket_date: r.mention_count
            for r in rows
            if r.entity_name == "deepseek-r1"
        }
        assert ds_rows[date_yesterday] == 2
        assert ds_rows[date_today] == 1

    # Second aggregation pass: must update idempotently without duplicating
    count_pass2 = await rollup_svc.aggregate_daily_counts(days=7)
    assert count_pass2 >= 2

    async with SqlAlchemyUnitOfWork() as uow:
        total_rows = (
            (await uow.session.execute(select(EntityDailyCountModel))).scalars().all()
        )
        # Ensure row count did not double
        assert len(total_rows) == 2


@pytest.mark.asyncio
async def test_momentum_z_score_calculations_and_sparklines():
    """Verify statistical z-score output, surging label, and 14-day sparkline vector."""
    rollup_svc = EntityRollupService()

    today = datetime.now(UTC).date()
    dates_28 = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(27, -1, -1)
    ]

    async with SqlAlchemyUnitOfWork() as uow:
        now = datetime.now(UTC)

        # 1. Surging entity: 0 for 25 days, then 6/day for last 3 days
        for d in dates_28[-3:]:
            uow.session.add(
                EntityDailyCountModel(
                    id=generate_uuid(),
                    entity_name="vllm",
                    entity_type="repository",
                    display_name="vLLM",
                    bucket_date=d,
                    mention_count=6,
                    created_at=now,
                    updated_at=now,
                )
            )

        # 2. Steady entity: constant 2/day for 28 days
        for d in dates_28:
            uow.session.add(
                EntityDailyCountModel(
                    id=generate_uuid(),
                    entity_name="steady-model",
                    entity_type="model",
                    display_name="SteadyModel",
                    bucket_date=d,
                    mention_count=2,
                    created_at=now,
                    updated_at=now,
                )
            )

        await uow.commit()

    # Calculate momentum
    radar = await rollup_svc.calculate_momentum_z_scores(limit=10, min_3d_mentions=1)

    assert len(radar) >= 2

    # Surging entity must be ranked #1
    top_entity = radar[0]
    assert top_entity["entity_name"] == "vllm"
    assert top_entity["momentum_label"] == "surging"
    assert top_entity["z_score"] >= 2.0
    assert top_entity["count_3d"] == 18
    assert top_entity["count_28d"] == 18
    assert len(top_entity["sparkline_14d"]) == 14
    # The last 3 values of sparkline_14d must be 6, 6, 6
    assert top_entity["sparkline_14d"][-3:] == [6, 6, 6]

    # Steady entity
    steady_entity = next(x for x in radar if x["entity_name"] == "steady-model")
    assert steady_entity["momentum_label"] == "steady"
    assert abs(steady_entity["z_score"]) < 1.0
    assert steady_entity["count_3d"] == 6
    assert steady_entity["count_28d"] == 56


@pytest.mark.asyncio
async def test_entity_momentum_api_endpoints():
    """Verify REST API /api/entities/momentum and /api/entities/rollup/refresh."""
    today = datetime.now(UTC).date()
    d_today = today.strftime("%Y-%m-%d")

    async with SqlAlchemyUnitOfWork() as uow:
        now = datetime.now(UTC)
        uow.session.add(
            EntityDailyCountModel(
                id=generate_uuid(),
                entity_name="sglang",
                entity_type="repository",
                display_name="SGLang",
                bucket_date=d_today,
                mention_count=5,
                created_at=now,
                updated_at=now,
            )
        )
        await uow.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/entities/momentum
        res = await client.get("/api/entities/momentum?min_3d_mentions=1")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert data["count"] >= 1
        sglang_item = next(
            (item for item in data["items"] if item["entity_name"] == "sglang"), None
        )
        assert sglang_item is not None
        assert sglang_item["display_name"] == "SGLang"
        assert len(sglang_item["sparkline_14d"]) == 14

        # 2. Filter by entity_type
        res_repos = await client.get("/api/entities/momentum?entity_type=repository")
        assert res_repos.status_code == 200
        assert any(x["entity_name"] == "sglang" for x in res_repos.json()["items"])

        res_models = await client.get("/api/entities/momentum?entity_type=model")
        assert res_models.status_code == 200
        assert not any(x["entity_name"] == "sglang" for x in res_models.json()["items"])

        # 3. POST /api/entities/rollup/refresh
        res_refresh = await client.post("/api/entities/rollup/refresh?days=7")
        assert res_refresh.status_code == 200
        assert res_refresh.json()["status"] == "ok"
