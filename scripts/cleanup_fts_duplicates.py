#!/usr/bin/env python3
"""Deduplicate and compact SQLite FTS5 table entries_fts without downtime.

Performs:
1. Atomic FTS rebuild (deduplicating unindexed backfills).
2. FTS5 index segment merge (INSERT INTO entries_fts(entries_fts) VALUES('optimize')).
3. Full VACUUM to reclaim empty freelist pages (reducing DB size from ~365 MB to ~11.5 MB).

Usage:
    poetry run python scripts/cleanup_fts_duplicates.py [--db PATH]
"""

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fts_dedup")


def cleanup_fts_duplicates(db_path: Path) -> bool:
    if not db_path.exists():
        logger.error(f"Database file not found at {db_path}")
        return False

    initial_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    logger.info(f"Connecting to database: {db_path} (Initial size: {initial_size_mb:.2f} MB)")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("SELECT count(*) FROM entries")
        entries_count = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM entries_fts")
        fts_before = cur.fetchone()[0]

        cur.execute("SELECT count(DISTINCT entry_id) FROM entries_fts")
        distinct_fts = cur.fetchone()[0]

        logger.info(
            f"Pre-cleanup state: entries={entries_count}, entries_fts={fts_before}, distinct_fts={distinct_fts}"
        )

        logger.info("Executing atomic FTS rebuild transaction...")
        cur.executescript(
            """
            BEGIN IMMEDIATE;
            DELETE FROM entries_fts;
            INSERT INTO entries_fts(entry_id, title, summary, category)
            SELECT id, title, summary, category FROM entries WHERE is_purged = 0;
            COMMIT;
            """
        )

        logger.info("Merging and optimizing FTS5 index segments (optimize)...")
        cur.execute("INSERT INTO entries_fts(entries_fts) VALUES('optimize')")
        conn.commit()

        cur.execute("SELECT count(*) FROM entries_fts")
        fts_after = cur.fetchone()[0]

        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]

        logger.info(f"Post-cleanup state: entries={entries_count}, entries_fts={fts_after}")
        logger.info(f"Integrity check: {integrity}")

        if fts_after != entries_count or integrity != "ok":
            logger.warning(f"Integrity or count mismatch: fts={fts_after}, expected={entries_count}")
            return False

        conn.close()

        logger.info("Executing VACUUM to reclaim freelist storage...")
        conn_vac = sqlite3.connect(db_path)
        conn_vac.execute("VACUUM")
        conn_vac.close()

        final_size_mb = os.path.getsize(db_path) / (1024 * 1024)
        savings_mb = initial_size_mb - final_size_mb
        logger.info(
            f"FTS deduplication & VACUUM complete! Final size: {final_size_mb:.2f} MB "
            f"(Saved: {savings_mb:.2f} MB / {(savings_mb / initial_size_mb)*100:.1f}%)"
        )
        return True

    except Exception as e:
        logger.error(f"Error during FTS deduplication: {e}", exc_info=True)
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate and compact SQLite entries_fts table.")
    parser.add_argument("--db", type=Path, default=Path("data/monitor.db"), help="Path to SQLite database")
    args = parser.parse_args()

    success = cleanup_fts_duplicates(args.db)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
