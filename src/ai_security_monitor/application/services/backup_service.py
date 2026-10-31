"""
Encrypted Offsite Backup & Verifiable Restore Drill Service (Pillar 7 / Workstream C1).
Handles hot SQLite online backups via VACUUM INTO, PRAGMA integrity verification,
asymmetric age (pyrage X25519) encryption, SHA-256 checksumming, grandfather-father-son
retention pruning (7 daily, 4 weekly, 6 monthly), and verifiable restore drills.
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
      1. Native SQLite point-in-time hot backup via VACUUM INTO.
      2. PRAGMA integrity_check before compression and encryption.
      3. Gzip compression with dual SHA-256 integrity fingerprints.
      4. Asymmetric X25519 public-key encryption with pyrage (age).
      5. Grandfather-father-son retention pruning (7 daily, 4 weekly, 6 monthly).
      6. Verifiable restore drill validating schema, integrity, and row count parity.
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
    def calculate_sha256(data: bytes) -> str:
        """Compute SHA-256 digest of binary payload."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def calculate_file_sha256(file_path: Path) -> str:
        """Compute SHA-256 digest of a file in chunks."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def verify_integrity(db_path: Path) -> bool:
        """Execute PRAGMA integrity_check on SQLite database."""
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
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

        conn = sqlite3.connect(str(source_db.resolve()))
        try:
            conn.execute("VACUUM INTO ?", (str(target_snapshot.resolve()),))
        except Exception as exc:
            logger.warning(
                "VACUUM INTO failed, falling back to sqlite3 backup API",
                error=str(exc),
            )
            dest_conn = sqlite3.connect(str(target_snapshot.resolve()))
            try:
                conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            conn.close()

    def encrypt_payload(self, data: bytes, public_key: str) -> bytes:
        """Encrypt payload using asymmetric age X25519 public key."""
        recipient = pyrage.x25519.Recipient.from_str(public_key.strip())
        return pyrage.encrypt(data, [recipient])

    def decrypt_payload(self, encrypted_data: bytes, secret_key: str) -> bytes:
        """Decrypt age payload using asymmetric X25519 secret identity."""
        try:
            identity = pyrage.x25519.Identity.from_str(secret_key.strip())
            return pyrage.decrypt(encrypted_data, [identity])
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
        Execute full backup pipeline:
        Lock -> VACUUM INTO -> PRAGMA integrity_check -> SHA-256 raw ->
        Gzip -> pyrage age encryption -> SHA-256 encrypted -> Write -> Prune -> Record.
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

                # 3. Size and raw checksum
                raw_size = raw_temp_snapshot.stat().st_size
                sha256_raw = self.calculate_file_sha256(raw_temp_snapshot)

                # 4. Gzip compression
                with open(raw_temp_snapshot, "rb") as f:
                    raw_bytes = f.read()
                compressed_bytes = gzip.compress(raw_bytes, compresslevel=6)
                compressed_size = len(compressed_bytes)

                # 5. Age Asymmetric Encryption
                encrypted_bytes = self.encrypt_payload(compressed_bytes, resolved_pubkey)
                encrypted_size = len(encrypted_bytes)
                sha256_encrypted = self.calculate_sha256(encrypted_bytes)

                # 6. Write final encrypted snapshot
                with open(final_filepath, "wb") as f:
                    f.write(encrypted_bytes)

                # 7. Optional remote S3/R2 upload
                uploaded_remote = False
                remote_key: str | None = None
                if upload_remote and settings.backup.s3_bucket_name:
                    uploaded_remote, remote_key = await self._upload_to_remote(
                        final_filepath, final_filename
                    )

                # 8. Grandfather-Father-Son Retention Pruning
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
                    duration_seconds=round(duration, 3),
                )

                if record_in_db:
                    await self._record_run(result)

                logger.info(
                    "Encrypted database backup created successfully",
                    filename=final_filename,
                    raw_mb=round(raw_size / (1024 * 1024), 2),
                    enc_mb=round(encrypted_size / (1024 * 1024), 2),
                    duration_s=result.duration_seconds,
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
                if raw_temp_snapshot.exists():
                    try:
                        raw_temp_snapshot.unlink()
                    except OSError:
                        pass

    def prune_backups(self, backup_dir: Path | None = None) -> list[Path]:
        """
        Enforce Grandfather-Father-Son (GFS) archival retention policy:
          - Daily: 1 backup per day for the last 7 days.
          - Weekly: 1 backup per week for the last 4 weeks.
          - Monthly: 1 backup per month for the last 6 months.
        Never purges the single most recent backup.
        Returns list of pruned file paths.
        """
        target_dir = backup_dir or self.backup_dir
        if not target_dir.exists():
            return []

        pattern = re.compile(r"aetherguard_backup_(\d{8})_(\d{6})_.*\.db\.gz\.age$")
        backups: list[tuple[datetime, Path]] = []

        for p in target_dir.glob("aetherguard_backup_*.db.gz.age"):
            m = pattern.match(p.name)
            if m:
                try:
                    dt = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S").replace(
                        tzinfo=UTC
                    )
                    backups.append((dt, p))
                except ValueError:
                    dt = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
                    backups.append((dt, p))
            else:
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
            # 1. Daily rule
            if dt >= cutoff_daily:
                day_key = dt.strftime("%Y-%m-%d")
                if day_key not in seen_days:
                    seen_days.add(day_key)
                    retained.add(path)

            # 2. Weekly rule
            if dt >= cutoff_weekly:
                week_key = f"{dt.year}-W{dt.isocalendar().week:02d}"
                if week_key not in seen_weeks:
                    seen_weeks.add(week_key)
                    retained.add(path)

            # 3. Monthly rule
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
    ) -> RestoreResult:
        """
        Execute verifiable restore drill:
          1. Decrypt using age secret key (identity).
          2. Decompress gzip payload.
          3. Write target SQLite file.
          4. Execute PRAGMA integrity_check.
          5. Verify table row count parity against reference database.
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

        try:
            with open(enc_file, "rb") as f:
                encrypted_bytes = f.read()

            compressed_bytes = self.decrypt_payload(encrypted_bytes, secret_key)
            raw_bytes = gzip.decompress(compressed_bytes)

            with open(target_path, "wb") as f:
                f.write(raw_bytes)

            # Check integrity
            integrity_ok = self.verify_integrity(target_path)
            if not integrity_ok:
                return RestoreResult(
                    success=False,
                    target_db_path=target_path,
                    integrity_check_passed=False,
                    error_message="PRAGMA integrity_check failed on restored database!",
                )

            # Query row counts
            table_counts = self._query_table_counts(target_path)
            parity_verified = True
            parity_details: dict[str, Any] = {}

            if reference_db_path:
                ref_path = Path(reference_db_path).resolve()
                if ref_path.exists():
                    ref_counts = self._query_table_counts(ref_path)
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

    @staticmethod
    def _query_table_counts(db_path: Path) -> dict[str, int]:
        """Inspect table row counts on SQLite database."""
        counts: dict[str, int] = {}
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for tbl in tables:
                try:
                    cursor.execute(f"SELECT count(*) FROM {tbl}")
                    counts[tbl] = cursor.fetchone()[0]
                except Exception:
                    pass
            return counts
        finally:
            conn.close()

    async def _upload_to_remote(self, file_path: Path, filename: str) -> tuple[bool, str]:
        """Upload backup snapshot to S3 or Cloudflare R2 if configured."""
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
            s3_client.upload_file(str(file_path), settings.backup.s3_bucket_name, remote_key)
            logger.info("Uploaded backup to remote S3/R2", remote_key=remote_key)
            return True, remote_key
        except ImportError:
            logger.warning(
                "boto3 package not installed; skipping offsite S3/R2 push, local encrypted backup preserved."
            )
            return False, ""
        except Exception as exc:
            logger.warning("Remote offsite backup upload failed", error=str(exc))
            return False, ""

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
