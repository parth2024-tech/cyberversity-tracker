"""
Unit tests for Encrypted Offsite Backup & Verifiable Restore Drill (Workstream C1).
Covers:
  - Hot SQLite snapshot creation & PRAGMA integrity verification
  - Asymmetric age (pyrage X25519) encryption & decryption round-trip
  - Full table row-count parity verification (including entry_analyses, FTS5 & sqlite-vec)
  - Single-run concurrency file lock enforcement (BackupLock)
  - Corrupted ciphertext / tampered payload rejection
  - Grandfather-Father-Son (GFS) 7-daily / 4-weekly / 6-monthly retention pruning
  - Strict preservation of manual backups (monitor_backup_*.db, etc.)
  - Remote S3/R2 upload & remote GFS pruning
  - Restore drill CLI verification execution
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyrage
import pytest

from ai_security_monitor.application.services.backup_service import (
    BackupError,
    BackupLock,
    BackupLockError,
    BackupService,
    DatabaseIntegrityError,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.scripts.restore_drill import run_drill


@pytest.fixture
def test_identity():
    """Generate ephemeral X25519 age identity for test encryption."""
    identity = pyrage.x25519.Identity.generate()
    return identity, str(identity.to_public()), str(identity)


@pytest.fixture
def populated_sqlite_db(tmp_path: Path) -> Path:
    """Create a fully populated test SQLite database with schema, FTS5, and sqlite-vec."""
    db_file = tmp_path / "test_source.db"
    conn = sqlite3.connect(str(db_file))
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        pass

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
    cursor.execute(
        "CREATE TABLE entry_analyses (id VARCHAR(36) PRIMARY KEY, entry_id VARCHAR(36), verdict TEXT, confidence FLOAT);"
    )
    cursor.execute(
        "CREATE TABLE llm_receipts (id VARCHAR(36) PRIMARY KEY, model TEXT, status TEXT);"
    )
    cursor.execute(
        "CREATE VIRTUAL TABLE entries_fts USING fts5(title, summary);"
    )

    try:
        cursor.execute(
            "CREATE VIRTUAL TABLE entries_vec USING vec0(entry_id text primary key, embedding float[4]);"
        )
        has_vec = True
    except Exception:
        has_vec = False

    # Insert test data
    for i in range(10):
        cursor.execute("INSERT INTO sources VALUES (?, ?, ?);", (f"src-{i}", f"Source {i}", True))
    for i in range(50):
        cursor.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?);",
            (f"entry-{i}", f"src-{i % 10}", f"AI Breakthrough {i}", f"Summary {i}"),
        )
        cursor.execute(
            "INSERT INTO entry_analyses VALUES (?, ?, ?, ?);",
            (f"analysis-{i}", f"entry-{i}", "MONITOR_CLAIMS", 0.95),
        )
        cursor.execute(
            "INSERT INTO entries_fts VALUES (?, ?);",
            (f"AI Breakthrough {i}", f"Summary {i}"),
        )
    for i in range(120):
        cursor.execute(
            "INSERT INTO entry_entities VALUES (?, ?, ?, ?);",
            (f"ent-{i}", f"entry-{i % 50}", "model", f"Model-{i}"),
        )
    for i in range(20):
        cursor.execute("INSERT INTO llm_receipts VALUES (?, ?, ?);", (f"rec-{i}", "qwen2.5:7b", "success"))

    if has_vec:
        for i in range(10):
            cursor.execute(
                "INSERT INTO entries_vec(entry_id, embedding) VALUES (?, ?);",
                (f"entry-{i}", "[0.1, 0.2, 0.3, 0.4]"),
            )

    conn.commit()
    conn.close()
    return db_file


@pytest.mark.asyncio
async def test_backup_and_restore_roundtrip_parity(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify complete backup -> encrypt -> decrypt -> restore -> parity cycle across all tables."""
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
    assert result.filepath.name.endswith(".db.gz.age")

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
    # Assert every single table matches
    assert restore_res.table_counts["sources"] == 10
    assert restore_res.table_counts["entries"] == 50
    assert restore_res.table_counts["entry_analyses"] == 50
    assert restore_res.table_counts["entry_entities"] == 120
    assert restore_res.table_counts["llm_receipts"] == 20
    assert restore_res.table_counts["entries_fts"] == 50


@pytest.mark.asyncio
async def test_sqlite_vec_and_fts_survive_backup_and_restore(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify that virtual tables (entries_fts and entries_vec) survive backup, restore, and are queryable."""
    _, pub_key, priv_key = test_identity
    backup_dir = tmp_path / "backups"
    service = BackupService(backup_dir=backup_dir, public_key=pub_key)

    result = await service.create_backup(
        db_path=populated_sqlite_db,
        public_key=pub_key,
        record_in_db=False,
    )

    restored_db = tmp_path / "restored_vec_fts.db"
    restore_res = service.restore_and_verify(
        encrypted_path=result.filepath,
        secret_key=priv_key,
        target_db_path=restored_db,
    )
    assert restore_res.success is True

    # Query FTS5 table on restored DB
    conn = BackupService._connect_sqlite(restored_db, readonly=True)
    c = conn.cursor()
    c.execute("SELECT title FROM entries_fts WHERE entries_fts MATCH 'Breakthrough'")
    fts_rows = c.fetchall()
    assert len(fts_rows) == 50

    # Query vec0 table if present
    c.execute("SELECT name FROM sqlite_master WHERE name='entries_vec'")
    if c.fetchone():
        c.execute("SELECT entry_id FROM entries_vec")
        vec_rows = c.fetchall()
        assert len(vec_rows) == 10
    conn.close()


@pytest.mark.asyncio
async def test_backup_lock_prevents_concurrency(tmp_path: Path):
    """Assert non-blocking file lock raises BackupLockError if already running."""
    lock_file = tmp_path / ".backup.lock"

    with BackupLock(lock_file):
        with pytest.raises(BackupLockError) as exc_info:
            with BackupLock(lock_file):
                pass
        assert "Concurrent backup already running" in str(exc_info.value)

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


@pytest.mark.asyncio
async def test_corrupted_source_db_rejected(tmp_path: Path, test_identity):
    """Verify that database failing integrity check aborts backup."""
    _, pub_key, _ = test_identity
    corrupted_db = tmp_path / "corrupted.db"
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

    # Generate 15 daily files
    for day in range(15):
        dt = now - timedelta(days=day, hours=2)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_test{day:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    # Generate 8 weekly files
    for week in range(1, 9):
        dt = now - timedelta(weeks=week, hours=5)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_w{week:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    # Generate 10 monthly files
    for month in range(1, 11):
        dt = now - timedelta(days=month * 30 + 1)
        fname = f"aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_m{month:02d}.db.gz.age"
        fpath = backup_dir / fname
        fpath.write_bytes(b"dummy")
        created_files.append(fpath)

    pruned = service.prune_backups(backup_dir)

    assert len(pruned) > 0
    newest = sorted(created_files, key=lambda p: p.name, reverse=True)[0]
    assert newest.exists()

    remaining = list(backup_dir.glob("aetherguard_backup_*.db.gz.age"))
    assert len(remaining) <= 17


def test_pruner_never_touches_manual_backups(tmp_path: Path):
    """Verify that prune_backups strictly ignores manual backups and non-standard filenames."""
    backup_dir = tmp_path / "mixed_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    service = BackupService(backup_dir=backup_dir)

    # Manual files created by past scripts or hand recovery
    manual_files = [
        backup_dir / "monitor_backup_20261031_193226.db",
        backup_dir / "monitor_before_feature_2.db",
        backup_dir / "monitor_pre_feature1_backup.db",
        backup_dir / "manual_backup.tar.gz",
        backup_dir / "aetherguard_backup_corrupted_name.txt",
    ]
    for mf in manual_files:
        mf.write_bytes(b"valuable recovery data")

    # Run pruner on the directory
    pruned = service.prune_backups(backup_dir)

    # Assert 0 manual files were pruned
    assert len(pruned) == 0
    for mf in manual_files:
        assert mf.exists(), f"Manual backup {mf.name} was erroneously deleted!"


@pytest.mark.asyncio
async def test_remote_s3_upload_and_pruning(
    tmp_path: Path, populated_sqlite_db: Path, test_identity
):
    """Verify that S3/R2 remote upload and GFS pruning execute with metadata checksums."""
    _, pub_key, _ = test_identity
    backup_dir = tmp_path / "s3_test_backups"
    service = BackupService(backup_dir=backup_dir, public_key=pub_key)

    mock_s3_client = MagicMock()
    mock_paginator = MagicMock()
    mock_s3_client.get_paginator.return_value = mock_paginator

    # Mock remote listing with 20 remote backups
    mock_contents = []
    now = datetime.now(UTC)
    for i in range(20):
        dt = now - timedelta(days=i)
        mock_contents.append({"Key": f"backups/aetherguard_backup_{dt.strftime('%Y%m%d_%H%M%S')}_{i}.db.gz.age"})
    mock_paginator.paginate.return_value = [{"Contents": mock_contents}]

    with (
        patch.object(settings.backup, "s3_bucket_name", "aetherguard-backups-bucket"),
        patch.object(settings.backup, "s3_endpoint_url", "https://mock.r2.cloudflarestorage.com"),
        patch("boto3.client", return_value=mock_s3_client),
    ):
        result = await service.create_backup(
            db_path=populated_sqlite_db,
            public_key=pub_key,
            upload_remote=True,
            record_in_db=False,
        )

        assert result.uploaded_to_remote is True
        assert result.remote_key is not None
        assert result.remote_key.startswith("backups/aetherguard_backup_")

        # Verify upload_file was invoked with metadata
        assert mock_s3_client.upload_file.called
        call_args, call_kwargs = mock_s3_client.upload_file.call_args
        assert call_args[1] == "aetherguard-backups-bucket"
        assert "Metadata" in call_kwargs.get("ExtraArgs", {})

        # Verify delete_objects was called to prune expired remote snapshots
        assert mock_s3_client.delete_objects.called


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
    assert not target_db.exists()


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
