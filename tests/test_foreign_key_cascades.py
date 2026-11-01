"""
Unit and integration tests for Defect Ledger D7: Foreign keys and cascade deletion.

Requirements:
1. Every SQLite connection must have PRAGMA foreign_keys=ON enabled.
2. Deleting an entry must cascade delete all dependent rows across:
   - entry_analysis (via ON DELETE CASCADE)
   - entry_entities (via ON DELETE CASCADE)
   - llm_receipts (via ON DELETE CASCADE or trigger)
   - entries_fts (via AFTER DELETE trigger)
3. Zero orphan rows must remain in any table referencing entries.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from ai_security_monitor.infrastructure.database.connection import DatabaseManager
from ai_security_monitor.infrastructure.database.models import (
    AnalysisModel,
    EntryEntityModel,
    EntryModel,
    ReceiptModel,
    SourceModel,
)


@pytest.mark.asyncio
async def test_pragma_foreign_keys_is_enabled(tmp_path):
    """PRAGMA foreign_keys must be 1 (ON) on every connection."""
    db_file = tmp_path / "test_fk.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)

    async with manager.engine.connect() as conn:
        res = await conn.execute(text("PRAGMA foreign_keys"))
        fk_enabled = res.scalar()

    await manager.close()
    assert fk_enabled == 1, f"Expected PRAGMA foreign_keys=1 (ON), got {fk_enabled}"


@pytest.mark.asyncio
async def test_cascade_delete_entry_removes_dependent_rows(tmp_path):
    """Deleting an entry must cascade delete all child rows in analysis, entities, and receipts."""
    db_file = tmp_path / "test_cascade.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)

    await manager.init_db()

    entry_id = str(uuid4())
    source_id = str(uuid4())
    analysis_id = str(uuid4())
    entity_id = str(uuid4())
    receipt_id = str(uuid4())
    now = datetime.now(UTC)

    async with manager.session_factory() as session:
        source = SourceModel(
            id=source_id,
            name="Cascade Test Source",
            category="ai_research",
            type="rss",
            url="https://example.com/rss",
        )
        session.add(source)

        entry = EntryModel(
            id=entry_id,
            source_id=source_id,
            title="Cascade Test Frontier Breakthrough",
            url="https://example.com/cascade-1",
            content_hash="hash-cascade-001",
            summary="Testing cascading deletes",
            category="ai_research",
            published_at=now,
        )
        session.add(entry)

        analysis = AnalysisModel(
            id=analysis_id,
            entry_id=entry_id,
            attack_vector="AI Specification",
            risk_assessment="Low",
            mitigation="None",
            threat_velocity=50,
            severity_index=50,
        )
        session.add(analysis)

        entity = EntryEntityModel(
            id=entity_id,
            entry_id=entry_id,
            entity_type="model",
            name="CascadeModel",
            display_name="Cascade Model",
            created_at=now,
        )
        session.add(entity)

        receipt = ReceiptModel(
            id=receipt_id,
            logical_key=f"receipt-key-{entry_id}",
            entry_id=entry_id,
            provider="ollama",
            model="qwen2.5:7b",
            prompt_version="v1.0",
            status="completed",
            attempts=1,
            max_attempts=3,
        )
        session.add(receipt)

        await session.commit()

    # Raw DELETE on entry table
    async with manager.session_factory() as session:
        await session.execute(text("DELETE FROM entries WHERE id = :eid"), {"eid": entry_id})
        await session.commit()

    # Verify zero dependent rows remain in analysis, entities, receipts, and FTS
    async with manager.session_factory() as session:
        analysis_res = await session.execute(
            text("SELECT COUNT(*) FROM entry_analysis WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        assert analysis_res.scalar() == 0, "Orphan row remained in entry_analysis!"

        entities_res = await session.execute(
            text("SELECT COUNT(*) FROM entry_entities WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        assert entities_res.scalar() == 0, "Orphan row remained in entry_entities!"

        receipts_res = await session.execute(
            text("SELECT COUNT(*) FROM llm_receipts WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        assert receipts_res.scalar() == 0, "Orphan row remained in llm_receipts!"

        fts_res = await session.execute(
            text("SELECT COUNT(*) FROM entries_fts WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        assert fts_res.scalar() == 0, "Orphan row remained in entries_fts!"

    await manager.close()


@pytest.mark.asyncio
async def test_cascade_delete_source_removes_children(tmp_path):
    """Deleting a source must cascade delete all associated entries, analyses, entities, and fetch logs."""
    db_file = tmp_path / "test_source_cascade.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)
    await manager.init_db()

    source_id = str(uuid4())
    entry_id = str(uuid4())
    analysis_id = str(uuid4())
    now = datetime.now(UTC)

    async with manager.session_factory() as session:
        source = SourceModel(
            id=source_id,
            name="Cascade Parent Source",
            category="ai_research",
            type="rss",
            url="https://example.com/feed",
        )
        session.add(source)

        entry = EntryModel(
            id=entry_id,
            source_id=source_id,
            title="Parent Source Child Entry",
            url="https://example.com/child",
            content_hash="child-hash-001",
            summary="Testing source cascade",
            category="ai_research",
            published_at=now,
        )
        session.add(entry)

        analysis = AnalysisModel(
            id=analysis_id,
            entry_id=entry_id,
            attack_vector="AI Specification",
            risk_assessment="Low",
            mitigation="None",
            threat_velocity=40,
            severity_index=40,
        )
        session.add(analysis)
        await session.commit()

    # Raw DELETE on source
    async with manager.session_factory() as session:
        await session.execute(text("DELETE FROM sources WHERE id = :sid"), {"sid": source_id})
        await session.commit()

    # Verify zero dependent rows remain in entries and entry_analysis
    async with manager.session_factory() as session:
        ent_res = await session.execute(
            text("SELECT COUNT(*) FROM entries WHERE source_id = :sid"),
            {"sid": source_id},
        )
        assert ent_res.scalar() == 0, "Orphan entry remained after source deletion!"

        analysis_res = await session.execute(
            text("SELECT COUNT(*) FROM entry_analysis WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        assert analysis_res.scalar() == 0, "Orphan analysis remained after source deletion!"

    await manager.close()


@pytest.mark.asyncio
async def test_cleanup_migration_deletes_orphans(tmp_path):
    """Alembic migration a1b2c3d4e5f6 must clean up any preexisting orphan rows."""
    from alembic import command
    from alembic.config import Config

    db_file = tmp_path / "test_migration_cleanup.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Upgrade to head
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    import sqlite3
    con = sqlite3.connect(str(db_file))
    cur = con.cursor()

    # Insert raw orphan row without matching entry (disable foreign keys temporarily to simulate legacy DB)
    cur.execute("PRAGMA foreign_keys=OFF")
    orphan_entry_id = str(uuid4())
    cur.execute(
        "INSERT INTO entry_analysis (id, entry_id, summary, category, analyzed_at, created_at) "
        "VALUES (?, ?, 'Legacy summary', 'ai_research', datetime('now'), datetime('now'))",
        (str(uuid4()), orphan_entry_id),
    )
    cur.execute(
        "INSERT INTO llm_receipts (id, logical_key, entry_id, provider, model, prompt_version, status, attempts, max_attempts, created_at, updated_at) "
        "VALUES (?, 'orphan-key-99', ?, 'ollama', 'test', 'v1', 'done', 1, 3, datetime('now'), datetime('now'))",
        (str(uuid4()), orphan_entry_id),
    )
    con.commit()

    # Verify orphans exist
    cur.execute("SELECT COUNT(*) FROM entry_analysis WHERE entry_id = ?", (orphan_entry_id,))
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM llm_receipts WHERE entry_id = ?", (orphan_entry_id,))
    assert cur.fetchone()[0] == 1
    con.close()

    # Downgrade 1 revision and re-upgrade to run the cleanup
    await asyncio.to_thread(command.downgrade, alembic_cfg, "-1")
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    con = sqlite3.connect(str(db_file))
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM entry_analysis WHERE entry_id = ?", (orphan_entry_id,))
    assert cur.fetchone()[0] == 0, "Orphan entry_analysis was not deleted by migration upgrade!"
    cur.execute("SELECT COUNT(*) FROM llm_receipts WHERE entry_id = ?", (orphan_entry_id,))
    assert cur.fetchone()[0] == 0, "Orphan llm_receipts was not deleted by migration upgrade!"
    con.close()
