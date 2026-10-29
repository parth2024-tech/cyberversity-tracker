"""Unit tests for sources reconciliation and orphan soft-deactivation."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.config.sources import SourceConfig
from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


class TestSourcesReconciliation:
    """Test suite verifying safe synchronization between YAML and database."""

    @pytest_asyncio.fixture
    async def test_uow_factory(self, tmp_path):
        db_path = tmp_path / "test_reconciliation.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        def uow_factory():
            session = session_factory()
            return SqlAlchemyUnitOfWork(session=session)

        return uow_factory

    @pytest.mark.asyncio
    async def test_reconciliation_soft_deactivates_orphaned_sources(self, test_uow_factory, monkeypatch):
        """Verify that orphaned YAML-managed sources are soft-deactivated (enabled=False)."""
        uow_factory = test_uow_factory

        # Pre-seed DB with 60 sources (so we exceed the 50 threshold)
        async with uow_factory() as uow:
            # Seed 55 persistent sources
            for i in range(55):
                src = Source(
                    name=f"Persistent Lab {i}",
                    category=Category.AI_MODELS,
                    type=SourceType.RSS,
                    url=f"https://lab{i}.ai/feed",
                    enabled=True,
                    config={"origin": "yaml"},
                )
                await uow.sources.add(src)

            # Seed 2 orphaned sources that will be missing from YAML
            orphan1 = Source(
                name="Orphaned Threat Feed",
                category=Category.CYBERSECURITY,
                type=SourceType.RSS,
                url="https://threats.org/rss",
                enabled=True,
                config={"origin": "yaml"},
            )
            orphan2 = Source(
                name="Orphaned Academic Feed",
                category=Category.AI_RESEARCH,
                type=SourceType.RSS,
                url="https://academic.org/rss",
                enabled=True,
                config={"origin": "yaml"},
            )
            # Seed 1 user-created source that is missing from YAML
            user_src = Source(
                name="User Custom Feed",
                category=Category.AI_TECH,
                type=SourceType.RSS,
                url="https://mycustom.org/rss",
                enabled=True,
                config={"origin": "user"},
            )
            await uow.sources.add(orphan1)
            await uow.sources.add(orphan2)
            await uow.sources.add(user_src)
            await uow.commit()

        # Mock YAML to return only the 55 persistent sources (total 55 >= 50)
        mock_yaml_sources = [
            SourceConfig(
                name=f"Persistent Lab {i}",
                category="ai_models",
                type="rss",
                url=f"https://lab{i}.ai/feed",
                enabled=True,
                tier=1.0,
            )
            for i in range(55)
        ]

        monkeypatch.setattr(
            "ai_security_monitor.application.services.monitor_service.load_sources_from_yaml",
            lambda *args, **kwargs: mock_yaml_sources,
        )

        monitor = MonitorService(uow_factory=uow_factory)
        await monitor.init_sources()

        # Check DB state
        async with uow_factory() as uow:
            # Orphan 1 should be soft-deactivated
            db_o1 = await uow.sources.get_by_name("Orphaned Threat Feed")
            assert db_o1 is not None
            assert db_o1.enabled is False

            # Orphan 2 should be soft-deactivated
            db_o2 = await uow.sources.get_by_name("Orphaned Academic Feed")
            assert db_o2 is not None
            assert db_o2.enabled is False

            # User custom feed must remain enabled
            db_user = await uow.sources.get_by_name("User Custom Feed")
            assert db_user is not None
            assert db_user.enabled is True

            # Persistent labs must remain enabled
            db_p0 = await uow.sources.get_by_name("Persistent Lab 0")
            assert db_p0 is not None
            assert db_p0.enabled is True

    @pytest.mark.asyncio
    async def test_reconciliation_guardrail_aborts_on_small_yaml(self, test_uow_factory, monkeypatch):
        """Verify that deactivation is skipped if YAML has fewer than 50 sources."""
        uow_factory = test_uow_factory

        async with uow_factory() as uow:
            src = Source(
                name="Active Feed",
                category=Category.AI_MODELS,
                type=SourceType.RSS,
                url="https://active.ai/feed",
                enabled=True,
                config={"origin": "yaml"},
            )
            await uow.sources.add(src)
            await uow.commit()

        # Mock YAML returning only 2 sources (< 50)
        mock_yaml_sources = [
            SourceConfig(name="New Source 1", category="ai_models", type="rss", url="https://s1.org"),
            SourceConfig(name="New Source 2", category="ai_models", type="rss", url="https://s2.org"),
        ]

        monkeypatch.setattr(
            "ai_security_monitor.application.services.monitor_service.load_sources_from_yaml",
            lambda *args, **kwargs: mock_yaml_sources,
        )

        monitor = MonitorService(uow_factory=uow_factory)
        await monitor.init_sources()

        # Active Feed must NOT be deactivated because YAML was under threshold
        async with uow_factory() as uow:
            db_src = await uow.sources.get_by_name("Active Feed")
            assert db_src is not None
            assert db_src.enabled is True

    @pytest.mark.asyncio
    async def test_stable_url_rename_reconciliation(self, test_uow_factory, monkeypatch):
        """Verify that renaming a source in YAML updates its name by URL rather than duplicating."""
        uow_factory = test_uow_factory

        async with uow_factory() as uow:
            old_src = Source(
                name="Old Misconfigured Name",
                category=Category.AI_RESEARCH,
                type=SourceType.RSS,
                url="https://stable.org/rss.xml",
                enabled=True,
                config={"origin": "yaml"},
            )
            await uow.sources.add(old_src)
            # Add 55 dummy sources
            for i in range(55):
                await uow.sources.add(
                    Source(
                        name=f"Feed {i}",
                        category=Category.AI_MODELS,
                        type=SourceType.RSS,
                        url=f"https://f{i}.org",
                        enabled=True,
                    )
                )
            await uow.commit()

        # Mock YAML with the new renamed name for the same URL
        mock_yaml = [
            SourceConfig(
                name="New Correct Lab Name",
                category="ai_research",
                type="rss",
                url="https://stable.org/rss.xml",
                enabled=True,
                tier=2.0,
            )
        ] + [
            SourceConfig(name=f"Feed {i}", category="ai_models", type="rss", url=f"https://f{i}.org", enabled=True)
            for i in range(55)
        ]

        monkeypatch.setattr(
            "ai_security_monitor.application.services.monitor_service.load_sources_from_yaml",
            lambda *args, **kwargs: mock_yaml,
        )

        monitor = MonitorService(uow_factory=uow_factory)
        await monitor.init_sources()

        async with uow_factory() as uow:
            # Old name should no longer exist as its own entity
            old_db = await uow.sources.get_by_name("Old Misconfigured Name")
            assert old_db is None

            # New name should exist, with the original URL, and remain enabled
            new_db = await uow.sources.get_by_name("New Correct Lab Name")
            assert new_db is not None
            assert new_db.url == "https://stable.org/rss.xml"
            assert new_db.enabled is True
