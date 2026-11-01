"""
Test D2: Schema work inside init_db() must be strictly idempotent.

Requirement (Defect Ledger D2):
- Calling init_db() three times must result in FTS rows == entries rows.
- No duplicate FTS segments or bloat from multiple invocations.
- Rebuild, optimize, and incremental vacuum maintenance operations succeed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.infrastructure.database.connection import DatabaseManager
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyEntryRepository,
    SQLAlchemySourceRepository,
)


@pytest.mark.asyncio
async def test_init_db_called_thrice_preserves_exact_fts_parity(tmp_path):
    """Calling init_db() 3 times must leave entries_fts count strictly equal to entries count."""
    test_db = tmp_path / "test_idempotent_init.db"
    db_url = f"sqlite+aiosqlite:///{test_db}"
    mgr = DatabaseManager(url=db_url)

    # 1. First init_db()
    await mgr.init_db()

    # 2. Seed 5 entries
    source = Source(
        name="ArXiv Intelligence",
        category=Category.AI_RESEARCH,
        type=SourceType.RSS,
    )
    async with mgr.session() as session:
        src_repo = SQLAlchemySourceRepository(session)
        await src_repo.add(source)
        await session.commit()

        entry_repo = SQLAlchemyEntryRepository(session)
        for i in range(5):
            entry = Entry(
                source_id=source.id,
                title=f"Reasoning Models Scaling Breakthrough {i}",
                url=f"https://arxiv.org/abs/2601.000{i}",
                summary=f"Technical paper discussing test-time compute in iteration {i}",
                content_hash=f"hash_{i:04d}",
                category=Category.AI_RESEARCH,
                published_at=datetime.now(UTC),
            )
            await entry_repo.add(entry)
        await session.commit()

    # Verify initial parity
    async with mgr.session() as session:
        entries_count = (await session.execute(text("SELECT count(*) FROM entries"))).scalar()
        fts_count = (await session.execute(text("SELECT count(*) FROM entries_fts"))).scalar()
        assert entries_count == 5
        assert fts_count == 5

    # 3. Call init_db() second time
    await mgr.init_db()

    # 4. Call init_db() third time
    await mgr.init_db()

    # 5. Assert strict row parity (no duplicate rows in FTS)
    async with mgr.session() as session:
        entries_count = (await session.execute(text("SELECT count(*) FROM entries"))).scalar()
        fts_count = (await session.execute(text("SELECT count(*) FROM entries_fts"))).scalar()
        assert entries_count == 5
        assert fts_count == 5, f"FTS rows ({fts_count}) != entries rows ({entries_count})"

    # 6. Test maintenance routine (rebuild + optimize + incremental vacuum)
    await mgr.maintain_fts_and_storage()

    async with mgr.session() as session:
        fts_count_after = (await session.execute(text("SELECT count(*) FROM entries_fts"))).scalar()
        assert fts_count_after == 5
        # Verify search query works
        search_res = (await session.execute(text(
            "SELECT count(*) FROM entries_fts WHERE entries_fts MATCH 'reasoning'"
        ))).scalar()
        assert search_res == 5

    await mgr.close()
