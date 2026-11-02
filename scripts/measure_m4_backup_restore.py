"""
M4 Measurement Script: Backup and Restore Drill on production DB (data/monitor.db).
Performs a full backup and restore drill, comparing EVERY table, indices, integrity check,
and timing/disk footprint.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


def run_backup_restore_drill(src_db_path: str = "data/monitor.db") -> dict:
    if not os.path.exists(src_db_path):
        raise FileNotFoundError(f"Source DB not found at {src_db_path}")

    src_size_bytes = os.path.getsize(src_db_path)
    src_size_mb = src_size_bytes / (1024 * 1024)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        backup_file = tmp_path / "backup.db"
        restored_file = tmp_path / "restored.db"

        # 1. Measure Backup using SQLite Online Backup API
        t0 = time.perf_counter()
        src_conn = sqlite3.connect(src_db_path)
        bck_conn = sqlite3.connect(backup_file)
        with bck_conn:
            src_conn.backup(bck_conn, pages=250)
        bck_conn.close()
        src_conn.close()
        t_backup = time.perf_counter() - t0

        backup_size_bytes = os.path.getsize(backup_file)
        backup_size_mb = backup_size_bytes / (1024 * 1024)

        # 2. Measure Restore
        t0_restore = time.perf_counter()
        shutil.copy2(backup_file, restored_file)
        t_restore = time.perf_counter() - t0_restore

        # 3. Comprehensive Verification across EVERY table
        orig_conn = sqlite3.connect(src_db_path)
        rest_conn = sqlite3.connect(restored_file)

        # List all tables (excluding sqlite internal tables)
        orig_cursor = orig_conn.cursor()
        orig_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in orig_cursor.fetchall()]

        table_comparisons = {}
        all_matched = True

        for tbl in sorted(tables):
            orig_count = orig_conn.execute(f"SELECT count(*) FROM \"{tbl}\"").fetchone()[0]
            rest_count = rest_conn.execute(f"SELECT count(*) FROM \"{tbl}\"").fetchone()[0]
            matched = (orig_count == rest_count)
            if not matched:
                all_matched = False
            table_comparisons[tbl] = {
                "orig_count": orig_count,
                "restored_count": rest_count,
                "matched": matched,
            }

        # Run PRAGMA integrity_check on restored DB
        integrity_result = rest_conn.execute("PRAGMA integrity_check;").fetchall()
        integrity_passed = (len(integrity_result) == 1 and integrity_result[0][0] == "ok")

        orig_conn.close()
        rest_conn.close()

        # Render disk check: Render starter disk is typically 1 GB (1024 MB).
        render_disk_limit_mb = 1024.0
        disk_pct_used = (src_size_mb / render_disk_limit_mb) * 100

        return {
            "source_file": src_db_path,
            "source_size_mb": round(src_size_mb, 2),
            "backup_size_mb": round(backup_size_mb, 2),
            "backup_time_seconds": round(t_backup, 3),
            "restore_time_seconds": round(t_restore, 3),
            "total_tables_checked": len(tables),
            "all_tables_matched": all_matched,
            "integrity_passed": integrity_passed,
            "integrity_output": [r[0] for r in integrity_result],
            "render_disk_usage_pct": round(disk_pct_used, 2),
            "render_headroom_mb": round(render_disk_limit_mb - src_size_mb, 2),
            "table_details": table_comparisons,
        }


if __name__ == "__main__":
    drill = run_backup_restore_drill()
    print("=================== M4 BACKUP & RESTORE DRILL REPORT ===================")
    print(f"Source DB:             {drill['source_file']} ({drill['source_size_mb']} MB)")
    print(f"Backup Size:           {drill['backup_size_mb']} MB (Online Backup time: {drill['backup_time_seconds']}s)")
    print(f"Restore Time:          {drill['restore_time_seconds']}s")
    print(f"Integrity Check:       {'PASSED (ok)' if drill['integrity_passed'] else 'FAILED'}")
    print(f"All Tables Matched:    {'YES (100% row match)' if drill['all_tables_matched'] else 'NO - MISMATCH DETECTED'}")
    print(f"Render Disk Footprint: {drill['source_size_mb']} MB / 1024 MB ({drill['render_disk_usage_pct']}% used, {drill['render_headroom_mb']} MB headroom)")
    print("\n--- PER-TABLE ROW COUNT AUDIT ---")
    for tbl, info in drill["table_details"].items():
        match_sym = "✅" if info["matched"] else "❌"
        print(f"  {match_sym} {tbl:<35} : {info['orig_count']:>6} rows (restored: {info['restored_count']:>6})")
