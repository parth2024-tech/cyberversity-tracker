"""
Encrypted Offsite Backup & Verifiable Restore Drill Service (Pillar 7 / Workstream C1).
Handles hot SQLite online backups via VACUUM INTO, PRAGMA integrity verification,
asymmetric age (pyrage X25519) encryption, SHA-256 checksumming, S3/Cloudflare R2 offsite upload,
grandfather-father-son retention pruning (7 daily, 4 weekly, 6 monthly), and verifiable restore drills.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyrage
import structlog

from ai_security_monitor.config.settings import settings

logger = structlog.get_logger(__name__)

# Strict regex matching AetherGuard backup filenames
BACKUP_FILENAME_REGEX = re.compile(
    r"^aetherguard_backup_(\d{8})_(\d{6})_[a-zA-Z0-9_-]+\.db\.gz\.age$"
)


class BackupError(Exception):
    """Base exception for backup operations."""

    pass


class BackupLockError(BackupError):
    """Raised when another backup process holds the concurrency lock."""

    pass


class DatabaseIntegrityError(BackupError):
    """Raised when SQLite PRAGMA integrity_check fails."""

    pass


class DecryptionError(BackupError):
    """Raised when asymmetric age decryption fails."""

    pass


@dataclass
class BackupResult:
    """Detailed summary of a completed backup run."""

    backup_run_id: str
    status: str
    filename: str
    filepath: Path
    raw_size_bytes: int
    compressed_size_bytes: int
    encrypted_size_bytes: int
    sha256_raw: str
    sha256_encrypted: str
    integrity_check_passed: bool
    uploaded_to_remote: bool
    remote_key: str | None = None
    table_counts: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str | None = None


@dataclass
class RestoreResult:
    """Detailed summary of a restore drill verification."""

    success: bool
    target_db_path: Path
    integrity_check_passed: bool
    table_counts: dict[str, int] = field(default_factory=dict)
    parity_verified: bool = False
    parity_details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str | None = None


class BackupLock:
    """Non-blocking file lock to prevent concurrent backup runs."""

    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self._fd: int | None = None

    def __enter__(self) -> BackupLock:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_file), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except (BlockingIOError, OSError) as exc:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            raise BackupLockError(
                f"Concurrent backup already running (lock: {self.lock_file})"
            ) from exc

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                os.close(self._fd)
                self._fd = None


class BackupService:
    """
    Automated Encrypted Offsite Backup & Restore Drill Engine.
    Implements:
      1. Native SQLite point-in-time hot backup via VACUUM INTO with sqlite-vec support.
      2. PRAGMA integrity_check before compression and encryption.
      3. Streaming Gzip compression with dual SHA-256 integrity fingerprints.
      4. Disk-headroom optimization (immediate unlinking of raw snapshot before encryption).
      5. Streaming asymmetric X25519 public-key encryption via pyrage.encrypt_file.
      6. Offsite S3/Cloudflare R2 push with remote GFS pruning.
      7. Grandfather-father-son retention pruning (7 daily, 4 weekly, 6 monthly).
      8. Verifiable restore drill validating schema, integrity, and row count parity.
    """

    def __init__(
        self,
        backup_dir: Path | str | None = None,
        public_key: str | None = None,
    ):
        self.backup_dir = (
            Path(backup_dir) if backup_dir else Path(settings.backup.backup_dir)
        )
        self.public_key = (
            public_key
            or settings.backup.age_public_key
            or os.environ.get("BACKUP_AGE_PUBLIC_KEY")
        )

    @staticmethod
    def _connect_sqlite(db_path: Path | str, readonly: bool = False) -> sqlite3.Connection:
        """
        Open SQLite connection with sqlite-vec extension loaded when available.
        Ensures virtual tables (entries_vec, entries_fts) are correctly parsed.
        """
        p = Path(db_path).resolve()
        uri = f"file:{p}?mode=ro" if readonly else str(p)
        conn = sqlite3.connect(uri, uri=readonly)
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            pass
        return conn

    @staticmethod
    def resolve_db_path(db_url: str | None = None) -> Path:
        """Resolve absolute filesystem path to SQLite database from connection URL."""
        url = db_url or settings.database.url
        clean = (
            url.replace("sqlite+aiosqlite:///", "")
            .replace("sqlite:///", "")
            .split("?")[0]
        )
        return Path(clean).resolve()

    @staticmethod
    def calculate_file_sha256(file_path: Path) -> str:
        """Compute SHA-256 digest of a file in 64KB stream chunks (memory < 1MB)."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def verify_integrity(self, db_path: Path) -> bool:
        """Execute PRAGMA integrity_check on SQLite database."""
        conn = self._connect_sqlite(db_path, readonly=True)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            rows = cursor.fetchall()
            return rows == [("ok",)]
        finally:
            conn.close()

    def _create_raw_snapshot(self, source_db: Path, target_snapshot: Path) -> None:
        """
        Create consistent point-in-time hot backup using VACUUM INTO.
        Operates without blocking active readers or writers in WAL mode.
        """
        if not source_db.exists():
            raise BackupError(f"Source database not found: {source_db}")

        if target_snapshot.exists():
            target_snapshot.unlink()

        conn = self._connect_sqlite(source_db, readonly=True)
        try:
            conn.execute("VACUUM INTO ?", (str(target_snapshot.resolve()),))
        except Exception as exc:
            logger.warning(
                "VACUUM INTO failed, falling back to sqlite3 backup API",
                error=str(exc),
            )
            dest_conn = self._connect_sqlite(target_snapshot, readonly=False)
            try:
                conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            conn.close()

    @staticmethod
    def compress_file_stream(input_file: Path, output_gz_file: Path) -> int:
        """
        Stream-compress file into gzip in 1MB chunks (memory < 10MB).
        Returns compressed file size in bytes.
        """
        with open(input_file, "rb") as f_in, gzip.open(output_gz_file, "wb", compresslevel=6) as f_out:
            while chunk := f_in.read(1024 * 1024):
                f_out.write(chunk)
        return output_gz_file.stat().st_size

    @staticmethod
    def decompress_file_stream(input_gz_file: Path, output_file: Path) -> int:
        """
        Stream-decompress gzip file into destination in 1MB chunks.
        Returns decompressed file size in bytes.
        """
        with gzip.open(input_gz_file, "rb") as f_in, open(output_file, "wb") as f_out:
            while chunk := f_in.read(1024 * 1024):
                f_out.write(chunk)
        return output_file.stat().st_size

    def encrypt_file(self, input_file: Path, output_age_file: Path, public_key: str) -> None:
        """Stream-encrypt file using asymmetric age X25519 public key."""
        recipient = pyrage.x25519.Recipient.from_str(public_key.strip())
        pyrage.encrypt_file(str(input_file), str(output_age_file), [recipient])

    def decrypt_file(self, input_age_file: Path, output_file: Path, secret_key: str) -> None:
        """Stream-decrypt age file using asymmetric X25519 secret identity."""
        try:
            identity = pyrage.x25519.Identity.from_str(secret_key.strip())
            pyrage.decrypt_file(str(input_age_file), str(output_file), [identity])
        except Exception as exc:
            raise DecryptionError(f"Age payload decryption failed: {exc}") from exc

    async def create_backup(
        self,
        db_path: Path | str | None = None,
        public_key: str | None = None,
        upload_remote: bool = False,
        record_in_db: bool = True,
    ) -> BackupResult:
        """
        Execute full backup pipeline with strict memory & disk headroom optimization:
        1. Acquire single-run lock (BackupLock).
        2. VACUUM INTO -> point-in-time snapshot.
        3. PRAGMA integrity_check.
        4. Inspect table row counts.
        5. Stream gzip compression.
        6. IMMEDIATELY unlink raw snapshot (prevents disk usage from tripling).
        7. Stream age asymmetric encryption.
        8. IMMEDIATELY unlink intermediate gzip file.
        9. Compute SHA-256 checksums.
        10. Optional S3/R2 remote upload with remote GFS pruning.
        11. Local GFS retention pruning.
        12. Record execution in backup_runs table.
        """
        start_time = time.monotonic()
        run_id = str(uuid4())
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.backup_dir / ".backup.lock"

        resolved_source = (
            Path(db_path).resolve()
            if db_path
            else self.resolve_db_path()
        )
        resolved_pubkey = (
            public_key
            or self.public_key
            or os.environ.get("BACKUP_AGE_PUBLIC_KEY")
        )

        if not resolved_pubkey:
            raise BackupError(
                "BACKUP_AGE_PUBLIC_KEY is not configured. "
                "Provide an age X25519 public key (age1...) to ensure zero-knowledge encryption."
            )

        with BackupLock(lock_file):
            timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            raw_temp_snapshot = self.backup_dir / f"temp_snapshot_{run_id}.db"
            temp_gz_file = self.backup_dir / f"temp_snapshot_{run_id}.db.gz"
            final_filename = f"aetherguard_backup_{timestamp_str}_{run_id[:8]}.db.gz.age"
            final_filepath = self.backup_dir / final_filename

            try:
                # 1. Hot snapshot via VACUUM INTO
                self._create_raw_snapshot(resolved_source, raw_temp_snapshot)

                # 2. PRAGMA integrity check on snapshot
                if not self.verify_integrity(raw_temp_snapshot):
                    raise DatabaseIntegrityError(
                        f"Database snapshot {raw_temp_snapshot} failed PRAGMA integrity_check!"
                    )

                # 3. Size and raw checksum (streamed)
                raw_size = raw_temp_snapshot.stat().st_size
                sha256_raw = self.calculate_file_sha256(raw_temp_snapshot)
                table_counts = self._query_table_counts(raw_temp_snapshot)

                # 4. Stream gzip compression
                compressed_size = self.compress_file_stream(raw_temp_snapshot, temp_gz_file)

                # 5. DISK HEADROOM OPTIMIZATION: delete raw snapshot immediately
                if raw_temp_snapshot.exists():
                    raw_temp_snapshot.unlink()

                # 6. Stream Age Asymmetric Encryption
                self.encrypt_file(temp_gz_file, final_filepath, resolved_pubkey)
                encrypted_size = final_filepath.stat().st_size
                sha256_encrypted = self.calculate_file_sha256(final_filepath)

                # 7. DISK HEADROOM OPTIMIZATION: delete intermediate gzip immediately
                if temp_gz_file.exists():
                    temp_gz_file.unlink()

                # 8. Optional remote S3/R2 upload & remote GFS pruning
                uploaded_remote = False
                remote_key: str | None = None
                if upload_remote and settings.backup.s3_bucket_name:
                    uploaded_remote, remote_key = await self._upload_to_remote(
                        final_filepath, final_filename, sha256_raw, sha256_encrypted
                    )
                    await self._prune_remote_backups()

                # 9. Local Grandfather-Father-Son Retention Pruning
                self.prune_backups()

                duration = time.monotonic() - start_time
                result = BackupResult(
                    backup_run_id=run_id,
                    status="success",
                    filename=final_filename,
                    filepath=final_filepath,
                    raw_size_bytes=raw_size,
                    compressed_size_bytes=compressed_size,
                    encrypted_size_bytes=encrypted_size,
                    sha256_raw=sha256_raw,
                    sha256_encrypted=sha256_encrypted,
                    integrity_check_passed=True,
                    uploaded_to_remote=uploaded_remote,
                    remote_key=remote_key,
                    table_counts=table_counts,
                    duration_seconds=round(duration, 3),
                )

                if record_in_db:
                    await self._record_run(result)

                logger.info(
                    "Encrypted database backup created successfully",
                    filename=final_filename,
                    raw_mb=round(raw_size / (1024 * 1024), 2),
                    enc_mb=round(encrypted_size / (1024 * 1024), 2),
                    compression_ratio=round((1 - (encrypted_size / max(1, raw_size))) * 100, 1),
                    duration_s=result.duration_seconds,
                    uploaded_remote=uploaded_remote,
                )
                return result

            except Exception as exc:
                duration = time.monotonic() - start_time
                error_msg = str(exc)
                logger.error("Encrypted backup failed", error=error_msg)
                fail_result = BackupResult(
                    backup_run_id=run_id,
                    status="failed",
                    filename=final_filename,
                    filepath=final_filepath,
                    raw_size_bytes=0,
                    compressed_size_bytes=0,
                    encrypted_size_bytes=0,
                    sha256_raw="",
                    sha256_encrypted="",
                    integrity_check_passed=False,
                    uploaded_to_remote=False,
                    duration_seconds=round(duration, 3),
                    error_message=error_msg,
                )
                if record_in_db:
                    try:
                        await self._record_run(fail_result)
                    except Exception:
                        pass
                raise
            finally:
                for temp_p in (raw_temp_snapshot, temp_gz_file):
                    if temp_p.exists():
                        try:
                            temp_p.unlink()
                        except OSError:
                            pass

    def prune_backups(self, backup_dir: Path | None = None) -> list[Path]:
        """
        Enforce Grandfather-Father-Son (GFS) archival retention policy locally:
          - Daily: 1 backup per day for the last 7 days.
          - Weekly: 1 backup per week for the last 4 weeks.
          - Monthly: 1 backup per month for the last 6 months.
        STRICT SAFETY INVARIANTS:
          1. ONLY deletes files strictly matching BACKUP_FILENAME_REGEX.
          2. Never touches manual backups (e.g. monitor_backup_*.db, *.tar.gz).
          3. Never purges the single most recent backup regardless of age.
        Returns list of pruned file paths.
        """
        target_dir = backup_dir or self.backup_dir
        if not target_dir.exists():
            return []

        backups: list[tuple[datetime, Path]] = []

        # Only examine files starting with aetherguard_backup_ and ending with .db.gz.age
        for p in target_dir.glob("aetherguard_backup_*.db.gz.age"):
            m = BACKUP_FILENAME_REGEX.match(p.name)
            if not m:
                # Strictly skip any file not adhering to standard naming
                continue
            try:
                dt = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S").replace(
                    tzinfo=UTC
                )
                backups.append((dt, p))
            except ValueError:
                dt = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
                backups.append((dt, p))

        if not backups:
            return []

        # Sort newest first
        backups.sort(key=lambda x: x[0], reverse=True)
        most_recent_backup = backups[0][1]

        now = datetime.now(UTC)
        cutoff_daily = now - timedelta(days=settings.backup.retention_daily)
        cutoff_weekly = now - timedelta(weeks=settings.backup.retention_weekly)
        cutoff_monthly = now - timedelta(days=settings.backup.retention_monthly * 30)

        retained: set[Path] = {most_recent_backup}
        seen_days: set[str] = set()
        seen_weeks: set[str] = set()
        seen_months: set[str] = set()

        for dt, path in backups:
            # 1. Daily rule (last 7 days)
            if dt >= cutoff_daily:
                day_key = dt.strftime("%Y-%m-%d")
                if day_key not in seen_days:
                    seen_days.add(day_key)
                    retained.add(path)

            # 2. Weekly rule (last 4 weeks)
            if dt >= cutoff_weekly:
                week_key = f"{dt.year}-W{dt.isocalendar().week:02d}"
                if week_key not in seen_weeks:
                    seen_weeks.add(week_key)
                    retained.add(path)

            # 3. Monthly rule (last 6 months)
            if dt >= cutoff_monthly:
                month_key = dt.strftime("%Y-%m")
                if month_key not in seen_months:
                    seen_months.add(month_key)
                    retained.add(path)

        pruned: list[Path] = []
        for _, path in backups:
            if path not in retained:
                try:
                    path.unlink()
                    pruned.append(path)
                    logger.info("Pruned expired backup file", path=str(path))
                except OSError as exc:
                    logger.warning("Failed to delete expired backup", path=str(path), error=str(exc))

        return pruned

    def restore_and_verify(
        self,
        encrypted_path: Path | str,
        secret_key: str,
        target_db_path: Path | str,
        reference_db_path: Path | str | None = None,
        expected_table_counts: dict[str, int] | None = None,
    ) -> RestoreResult:
        """
        Execute verifiable restore drill:
          1. Stream-decrypt age file to temporary gzip.
          2. Stream-decompress gzip to target SQLite DB.
          3. Verify PRAGMA integrity_check (with sqlite-vec loaded).
          4. Inspect ALL table counts across entire database schema.
          5. Verify exact parity against reference DB or expected snapshot counts.
        """
        start_time = time.monotonic()
        enc_file = Path(encrypted_path).resolve()
        target_path = Path(target_db_path).resolve()

        if not enc_file.exists():
            return RestoreResult(
                success=False,
                target_db_path=target_path,
                integrity_check_passed=False,
                error_message=f"Encrypted backup file does not exist: {enc_file}",
            )

        if target_path.exists():
            target_path.unlink()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_gz = target_path.parent / f"restore_temp_{uuid4().hex[:8]}.db.gz"

        try:
            # 1. Stream decrypt
            self.decrypt_file(enc_file, temp_gz, secret_key)

            # 2. Stream decompress
            self.decompress_file_stream(temp_gz, target_path)

            # 3. Clean up intermediate gzip immediately
            if temp_gz.exists():
                temp_gz.unlink()

            # 4. Check integrity with sqlite-vec loaded
            integrity_ok = self.verify_integrity(target_path)
            if not integrity_ok:
                return RestoreResult(
                    success=False,
                    target_db_path=target_path,
                    integrity_check_passed=False,
                    error_message="PRAGMA integrity_check failed on restored database!",
                )

            # 5. Query table counts across all logical tables
            table_counts = self._query_table_counts(target_path)
            parity_verified = True
            parity_details: dict[str, Any] = {}

            # Check parity against expected counts (e.g. from backup metadata) or reference DB
            ref_counts = expected_table_counts
            if not ref_counts and reference_db_path:
                ref_path = Path(reference_db_path).resolve()
                if ref_path.exists():
                    ref_counts = self._query_table_counts(ref_path)

            if ref_counts:
                parity_details["reference"] = ref_counts
                parity_details["restored"] = table_counts
                for tbl, ref_cnt in ref_counts.items():
                    tgt_cnt = table_counts.get(tbl, 0)
                    if tgt_cnt != ref_cnt:
                        parity_verified = False
                        parity_details[f"{tbl}_mismatch"] = {
                            "reference": ref_cnt,
                            "restored": tgt_cnt,
                        }

            duration = round(time.monotonic() - start_time, 3)
            return RestoreResult(
                success=integrity_ok and parity_verified,
                target_db_path=target_path,
                integrity_check_passed=integrity_ok,
                table_counts=table_counts,
                parity_verified=parity_verified,
                parity_details=parity_details,
                duration_seconds=duration,
            )

        except Exception as exc:
            duration = round(time.monotonic() - start_time, 3)
            return RestoreResult(
                success=False,
                target_db_path=target_path,
                integrity_check_passed=False,
                duration_seconds=duration,
                error_message=str(exc),
            )
        finally:
            if temp_gz.exists():
                try:
                    temp_gz.unlink()
                except OSError:
                    pass

    def _query_table_counts(self, db_path: Path) -> dict[str, int]:
        """
        Inspect row counts across all logical tables and virtual tables in SQLite DB.
        Excludes SQLite internal tables and FTS shadow tables (_data, _idx, _docsize, _config).
        """
        counts: dict[str, int] = {}
        conn = self._connect_sqlite(db_path, readonly=True)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "  AND name NOT LIKE 'sqlite_%' "
                "  AND name NOT LIKE '%_data' "
                "  AND name NOT LIKE '%_idx' "
                "  AND name NOT LIKE '%_content' "
                "  AND name NOT LIKE '%_docsize' "
                "  AND name NOT LIKE '%_config'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for tbl in tables:
                try:
                    cursor.execute(f'SELECT count(*) FROM "{tbl}"')
                    counts[tbl] = cursor.fetchone()[0]
                except Exception:
                    pass
            return counts
        finally:
            conn.close()

    async def _upload_to_remote(
        self, file_path: Path, filename: str, sha256_raw: str, sha256_encrypted: str
    ) -> tuple[bool, str]:
        """Upload backup snapshot to S3 or Cloudflare R2 with metadata checksums."""
        try:
            import boto3  # type: ignore

            s3_client = boto3.client(
                "s3",
                endpoint_url=settings.backup.s3_endpoint_url,
                aws_access_key_id=settings.backup.s3_access_key_id,
                aws_secret_access_key=settings.backup.s3_secret_access_key,
                region_name=settings.backup.s3_region_name,
            )
            remote_key = f"backups/{filename}"
            extra_args = {
                "ContentType": "application/octet-stream",
                "Metadata": {
                    "sha256_raw": sha256_raw,
                    "sha256_encrypted": sha256_encrypted,
                },
            }
            s3_client.upload_file(
                str(file_path),
                settings.backup.s3_bucket_name,
                remote_key,
                ExtraArgs=extra_args,
            )
            logger.info("Uploaded backup to remote S3/R2", remote_key=remote_key)
            return True, remote_key
        except Exception as exc:
            logger.warning("Remote offsite backup upload failed", error=str(exc))
            return False, ""

    async def _prune_remote_backups(self) -> list[str]:
        """
        Enforce GFS retention policy on remote S3/R2 storage:
        Lists remote backups, calculates 7 daily, 4 weekly, 6 monthly, and deletes expired.
        """
        if not settings.backup.s3_bucket_name:
            return []

        try:
            import boto3

            s3_client = boto3.client(
                "s3",
                endpoint_url=settings.backup.s3_endpoint_url,
                aws_access_key_id=settings.backup.s3_access_key_id,
                aws_secret_access_key=settings.backup.s3_secret_access_key,
                region_name=settings.backup.s3_region_name,
            )
            paginator = s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=settings.backup.s3_bucket_name,
                Prefix="backups/aetherguard_backup_",
            )

            backups: list[tuple[datetime, str]] = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj.get("Key", "")
                    base_name = os.path.basename(key)
                    m = BACKUP_FILENAME_REGEX.match(base_name)
                    if not m:
                        continue
                    try:
                        dt = datetime.strptime(
                            f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S"
                        ).replace(tzinfo=UTC)
                        backups.append((dt, key))
                    except ValueError:
                        continue

            if not backups:
                return []

            backups.sort(key=lambda x: x[0], reverse=True)
            most_recent_key = backups[0][1]

            now = datetime.now(UTC)
            cutoff_daily = now - timedelta(days=settings.backup.retention_daily)
            cutoff_weekly = now - timedelta(weeks=settings.backup.retention_weekly)
            cutoff_monthly = now - timedelta(days=settings.backup.retention_monthly * 30)

            retained: set[str] = {most_recent_key}
            seen_days: set[str] = set()
            seen_weeks: set[str] = set()
            seen_months: set[str] = set()

            for dt, key in backups:
                if dt >= cutoff_daily:
                    day_key = dt.strftime("%Y-%m-%d")
                    if day_key not in seen_days:
                        seen_days.add(day_key)
                        retained.add(key)
                if dt >= cutoff_weekly:
                    week_key = f"{dt.year}-W{dt.isocalendar().week:02d}"
                    if week_key not in seen_weeks:
                        seen_weeks.add(week_key)
                        retained.add(key)
                if dt >= cutoff_monthly:
                    month_key = dt.strftime("%Y-%m")
                    if month_key not in seen_months:
                        seen_months.add(month_key)
                        retained.add(key)

            to_delete = [
                {"Key": key}
                for _, key in backups
                if key not in retained
            ]

            if to_delete:
                s3_client.delete_objects(
                    Bucket=settings.backup.s3_bucket_name,
                    Delete={"Objects": to_delete},
                )
                logger.info(f"Pruned {len(to_delete)} expired remote backups from S3/R2")
                return [d["Key"] for d in to_delete]
            return []

        except Exception as exc:
            logger.warning("Remote S3/R2 backup pruning failed", error=str(exc))
            return []

    async def _record_run(self, result: BackupResult) -> None:
        """Persist backup execution telemetry to backup_runs table."""
        from ai_security_monitor.infrastructure.database.connection import db_manager
        from ai_security_monitor.infrastructure.database.models import BackupRunModel

        async with db_manager.session() as session:
            model = BackupRunModel(
                id=result.backup_run_id,
                status=result.status,
                filename=result.filename,
                raw_size_bytes=result.raw_size_bytes,
                compressed_size_bytes=result.compressed_size_bytes,
                encrypted_size_bytes=result.encrypted_size_bytes,
                sha256_raw=result.sha256_raw,
                sha256_encrypted=result.sha256_encrypted,
                integrity_check_passed=result.integrity_check_passed,
                uploaded_to_remote=result.uploaded_to_remote,
                remote_key=result.remote_key,
                error_message=result.error_message,
                duration_seconds=result.duration_seconds,
                created_at=datetime.now(UTC),
            )
            session.add(model)
            await session.commit()
