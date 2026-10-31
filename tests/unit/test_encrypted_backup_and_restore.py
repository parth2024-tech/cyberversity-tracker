"""
Unit tests for Encrypted Offsite Backup & Verifiable Restore Drill (Workstream C1).
Covers:
  - Hot SQLite snapshot creation & PRAGMA integrity verification
  - Asymmetric age (pyrage X25519) encryption & decryption round-trip
  - Table row-count parity verification between source and restored databases
  - Single-run concurrency file lock enforcement
  - Corrupted ciphertext / tampered payload rejection
  - Grandfather-Father-Son (GFS) 7-daily / 4-weekly / 6-monthly retention pruning
  - Restore drill CLI verification execution
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyrage
import pytest

from ai_security_monitor.application.services.backup_service import (
    BackupError,
    BackupLock,
    BackupLockError,
    BackupService,
    DatabaseIntegrityError,
)
from ai_security_monitor.scripts.restore_drill import run_drill


@pytest.fixture
def test_identity():
    """Generate ephemeral X25519 age identity for test encryption."""
    identity = pyrage.x25519.Identity.generate()
    return identity, str(identity.to_public()), str(identity)


@pytest.fixture
def populated_sqlite_db(tmp_path: Path) -> Path:
    """Create a populated test SQLite database with schema and data."""
    db_file = tmp_path / "test_source.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute(
        "CREATE TABLE sources (id VARCHAR(36) PRIMARY KEY, name TEXT NOT NULL, enabled BOOLEAN);"
    )
    cursor.execute(
        "CREATE TABLE entries (id VARCHAR(36) PRIMARY KEY, source_id VARCHAR(36), title TEXT NOT NULL, summary TEXT);"
    )
    cursor.execute(
        "CREATE TABLE entry_entities (id VARCHAR(36) PRIMARY KEY, entry_id VARCHAR(36), entity_type TEXT, name TEXT);"
    )

    # Insert test data
    for i in range(10):
        cursor.execute(
            "INSERT INTO sources VALUES (?, ?, ?);",
            (f"src-{i}", f"Source {i}", True),
        )
    for i in range(50):
        cursor.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?);",
            (f"entry-{i}", f"src-{i % 10}", f"AI Breakthrough {i}", f"Summary {i}"),
        )
    for i in range(120):
        cursor.execute(
            "INSERT INTO entry_entities VALUES (?, ?, ?, ?);",
            (f"ent-{i}", f"entry-{i % 50}", "model", f"Model-{i}"),
        )

    conn.commit()
    conn.close()
    return db_file


@pytest.mark.asyncio
async def test_backup_and_restore_roundtrip_parity(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify complete backup -> encrypt -> decrypt -> restore -> parity cycle."""
    _, pub_key, priv_key = test_identity
    backup_dir = tmp_path / "backups"
    service = BackupService(backup_dir=backup_dir, public_key=pub_key)

    # 1. Create encrypted backup
    result = await service.create_backup(
        db_path=populated_sqlite_db,
        public_key=pub_key,
        upload_remote=False,
        record_in_db=False,
    )

    assert result.status == "success"
    assert result.integrity_check_passed is True
    assert result.raw_size_bytes > 0
    assert result.encrypted_size_bytes > 0
    assert result.filepath.exists()
    assert result.filepath.suffix == ".age"

    # 2. Execute restore drill
    restored_db = tmp_path / "restored.db"
    restore_res = service.restore_and_verify(
        encrypted_path=result.filepath,
        secret_key=priv_key,
        target_db_path=restored_db,
        reference_db_path=populated_sqlite_db,
    )

    assert restore_res.success is True
    assert restore_res.integrity_check_passed is True
    assert restore_res.parity_verified is True
    assert restore_res.table_counts["sources"] == 10
    assert restore_res.table_counts["entries"] == 50
    assert restore_res.table_counts["entry_entities"] == 120


@pytest.mark.asyncio
async def test_backup_lock_prevents_concurrency(tmp_path: Path):
    """Assert non-blocking file lock raises BackupLockError if already running."""
    lock_file = tmp_path / ".backup.lock"

    with BackupLock(lock_file):
        # Second simultaneous lock acquisition should fail immediately
        with pytest.raises(BackupLockError) as exc_info:
            with BackupLock(lock_file):
                pass
        assert "Concurrent backup already running" in str(exc_info.value)

    # After first lock exits, acquiring lock succeeds cleanly
    with BackupLock(lock_file):
        assert True


@pytest.mark.asyncio
async def test_corrupted_ciphertext_rejected(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify that tampering with encrypted file is caught during restore."""
    _, pub_key, priv_key = test_identity
    backup_dir = tmp_path / "backups"
    service = BackupService(backup_dir=backup_dir, public_key=pub_key)

    result = await service.create_backup(
        db_path=populated_sqlite_db,
        public_key=pub_key,
        upload_remote=False,
        record_in_db=False,
    )

    # Tamper with encrypted bytes
    with open(result.filepath, "r+b") as f:
        f.seek(150)
        f.write(b"\x00\xff\x00\xff\x00\xff")

    restored_db = tmp_path / "restored_corrupted.db"
    restore_res = service.restore_and_verify(
        encrypted_path=result.filepath,
        secret_key=priv_key,
        target_db_path=restored_db,
    )

    assert restore_res.success is False
    assert not restored_db.exists() or restore_res.integrity_check_passed is False


@pytest.mark.asyncio
async def test_corrupted_source_db_rejected(tmp_path: Path, test_identity):
    """Verify that database failing integrity check aborts backup."""
    _, pub_key, _ = test_identity
    corrupted_db = tmp_path / "corrupted.db"
    # Write garbage pretending to be sqlite
    with open(corrupted_db, "wb") as f:
        f.write(b"NOT A SQLITE DATABASE HEADER" + b"\x00" * 4096)

    service = BackupService(backup_dir=tmp_path / "backups", public_key=pub_key)

    with pytest.raises((DatabaseIntegrityError, BackupError, sqlite3.DatabaseError)):
        await service.create_backup(
            db_path=corrupted_db,
            public_key=pub_key,
            record_in_db=False,
        )


def test_grandfather_father_son_retention_pruning(tmp_path: Path):
    """Verify 7 daily, 4 weekly, 6 monthly retention pruning policy."""
    backup_dir = tmp_path / "gfs_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    service = BackupService(backup_dir=backup_dir)

    now = datetime.now(UTC)
    created_files: list[Path] = []

    # Generate 15 daily files (days 0 to 14)
    for day in range(15):
        dt = now - timedelta(days=day, hours=2)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_test{day:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    # Generate 8 weekly files (weeks 1 to 8)
    for week in range(1, 9):
        dt = now - timedelta(weeks=week, hours=5)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_w{week:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    # Generate 10 monthly files (months 1 to 10)
    for month in range(1, 11):
        dt = now - timedelta(days=month * 30 + 1)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_m{month:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    pruned = service.prune_backups(backup_dir)

    # Assert pruning deleted expired backups
    assert len(pruned) > 0
    # Verify the most recent backup was definitely kept
    newest = sorted(created_files, key=lambda p: p.name, reverse=True)[0]
    assert newest.exists()

    # Remaining files should be within daily (7) + weekly (4) + monthly (6) buckets
    remaining = list(backup_dir.glob("aetherguard_backup_*.db.gz.age"))
    assert len(remaining) <= 17


def test_restore_drill_cli_execution(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify that run_drill CLI helper returns 0 and verifies table row parity."""
    _, pub_key, priv_key = test_identity
    backup_dir = tmp_path / "backups"
    service = BackupService(backup_dir=backup_dir, public_key=pub_key)

    import asyncio
    result = asyncio.run(
        service.create_backup(
            db_path=populated_sqlite_db,
            public_key=pub_key,
            record_in_db=False,
        )
    )

    target_db = tmp_path / "cli_restored.db"
    exit_code = run_drill(
        backup_file=result.filepath,
        secret_key=priv_key,
        target_db=target_db,
        reference_db=populated_sqlite_db,
        cleanup=True,
    )

    assert exit_code == 0
    assert not target_db.exists()  # cleanup=True verified


@pytest.mark.asyncio
async def test_backup_recorded_in_db(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify that backup run is logged to backup_runs table."""
    from sqlalchemy import text

    from ai_security_monitor.infrastructure.database.connection import db_manager

    await db_manager.init_db()
    _, pub_key, _ = test_identity
    service = BackupService(backup_dir=tmp_path / "backups", public_key=pub_key)

    result = await service.create_backup(
        db_path=populated_sqlite_db,
        public_key=pub_key,
        upload_remote=False,
        record_in_db=True,
    )

    async with db_manager.session() as session:
        res = await session.execute(
            text("SELECT status, filename, integrity_check_passed FROM backup_runs WHERE id = :id"),
            {"id": result.backup_run_id},
        )
        row = res.first()
        assert row is not None
        assert row[0] == "success"
        assert row[1] == result.filename
        assert row[2] in (1, True)

