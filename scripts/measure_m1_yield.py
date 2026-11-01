"""
M1 Measurement Script: Per-source yield vs declared cadence from production DB.
Analyzes sources that are late, silent, or erroring based on real fetch_log and entries tables.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def measure_m1_yield(db_path: str = "data/monitor.db") -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    now = datetime.now(UTC)
    two_weeks_ago = now - timedelta(days=14)

    # 1. Total counts
    total_sources = cursor.execute("SELECT count(*) FROM sources").fetchone()[0]
    enabled_sources = cursor.execute("SELECT count(*) FROM sources WHERE enabled = 1").fetchone()[0]
    total_entries = cursor.execute("SELECT count(*) FROM entries").fetchone()[0]
    fresh_entries = cursor.execute(
        "SELECT count(*) FROM entries WHERE published_at >= ?",
        (two_weeks_ago.isoformat(),),
    ).fetchone()[0]

    # 2. Per-source stats from fetch_log and entries
    cursor.execute("""
        SELECT
            s.id,
            s.name,
            s.category,
            s.type,
            s.enabled,
            s.rate_limit_seconds,
            s.last_fetched_at,
            s.last_status,
            s.last_entries_new,
            s.config,
            COUNT(DISTINCT e.id) as total_entries_count,
            COUNT(DISTINCT CASE WHEN e.published_at >= ? THEN e.id END) as fresh_entries_count,
            COUNT(DISTINCT fl.id) as total_fetches,
            COUNT(DISTINCT CASE WHEN fl.status = 'success' THEN fl.id END) as success_fetches,
            COUNT(DISTINCT CASE WHEN fl.status != 'success' THEN fl.id END) as failed_fetches
        FROM sources s
        LEFT JOIN entries e ON e.source_id = s.id
        LEFT JOIN fetch_log fl ON fl.source_id = s.id
        GROUP BY s.id
    """, (two_weeks_ago.isoformat(),))

    rows = cursor.fetchall()

    erroring = []
    silent = []
    late = []
    healthy = []

    for r in rows:
        cadence_sec = r["rate_limit_seconds"] or 86400
        cadence_days = max(1, cadence_sec // 86400)

        last_fetched_str = r["last_fetched_at"]
        last_fetched = None
        if last_fetched_str:
            try:
                clean_str = last_fetched_str.replace("Z", "+00:00")
                last_fetched = datetime.fromisoformat(clean_str)
                if last_fetched.tzinfo is None:
                    last_fetched = last_fetched.replace(tzinfo=UTC)
            except Exception:
                pass

        total_fetches = r["total_fetches"]
        failed_fetches = r["failed_fetches"]
        failure_rate = (failed_fetches / total_fetches) if total_fetches > 0 else 0.0

        item = {
            "name": r["name"],
            "type": r["type"],
            "category": r["category"],
            "enabled": bool(r["enabled"]),
            "cadence_days": cadence_days,
            "last_fetched_at": last_fetched_str,
            "last_status": r["last_status"],
            "total_entries": r["total_entries_count"],
            "fresh_entries_14d": r["fresh_entries_count"],
            "total_fetches": total_fetches,
            "failure_rate": round(failure_rate, 2),
        }

        # Classification
        if r["enabled"]:
            if failure_rate >= 0.5 and total_fetches >= 2:
                erroring.append(item)
            elif r["total_entries_count"] == 0 and total_fetches > 0:
                silent.append(item)
            elif last_fetched and (now - last_fetched) > timedelta(days=cadence_days * 2):
                late.append(item)
            elif r["total_entries_count"] > 0:
                healthy.append(item)

    conn.close()

    return {
        "total_sources": total_sources,
        "enabled_sources": enabled_sources,
        "total_entries": total_entries,
        "fresh_entries_14d": fresh_entries,
        "summary": {
            "healthy_count": len(healthy),
            "erroring_count": len(erroring),
            "silent_count": len(silent),
            "late_count": len(late),
        },
        "erroring_sources": sorted(erroring, key=lambda x: x["failure_rate"], reverse=True),
        "silent_sources": sorted(silent, key=lambda x: x["total_fetches"], reverse=True),
        "late_sources": sorted(late, key=lambda x: x["last_fetched_at"] or ""),
        "top_healthy_producers": sorted(healthy, key=lambda x: x["fresh_entries_14d"], reverse=True)[:15],
    }


if __name__ == "__main__":
    report = measure_m1_yield()
    print("=================== M1 PRODUCTION YIELD REPORT ===================")
    print(f"Total Sources in DB:   {report['total_sources']} ({report['enabled_sources']} enabled)")
    print(f"Total Entries:         {report['total_entries']} ({report['fresh_entries_14d']} within 14 days)")
    print(f"Status Breakdown:      {report['summary']['healthy_count']} Healthy | {report['summary']['erroring_count']} Erroring | {report['summary']['silent_count']} Silent (0 yield) | {report['summary']['late_count']} Late")
    print("\n--- TOP ERRORING SOURCES ---")
    for s in report["erroring_sources"][:10]:
        print(f"  ❌ {s['name'][:40]:<40} | Type: {s['type']:<10} | Fail Rate: {s['failure_rate']*100:.0f}% ({s['total_fetches']} fetches) | Status: {s['last_status']}")
    print("\n--- TOP SILENT SOURCES (0 entries yielded despite fetches) ---")
    for s in report["silent_sources"][:10]:
        print(f"  🔇 {s['name'][:40]:<40} | Type: {s['type']:<10} | Fetches: {s['total_fetches']:<3} | Status: {s['last_status']}")
    print("\n--- TOP 10 HEALTHY PRODUCERS (Fresh Entries in 14 Days) ---")
    for s in report["top_healthy_producers"][:10]:
        print(f"  ✅ {s['name'][:40]:<40} | Type: {s['type']:<10} | 14d Fresh: {s['fresh_entries_14d']:<3} | Total: {s['total_entries']}")
