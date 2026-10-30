#!/usr/bin/env python3
"""
Missed-Story Audit Script.
Compares ingested database intelligence against ground-truth AI model releases
and benchmarks to detect ecosystem blind spots and ingestion lag.

Usage:
    python scripts/run_audit.py                        # Full audit across all stories
    python scripts/run_audit.py --since 2026-09-01     # Audit releases since Sept 1, 2026
    python scripts/run_audit.py --region china         # China corridor audit
    python scripts/run_audit.py --format json          # JSON format
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_security_monitor.application.services.audit_service import audit_service
from ai_security_monitor.infrastructure.database.connection import db_manager


async def run(
    since_str: str | None = None,
    region: str | None = None,
    window_days: int = 7,
    format_type: str = "table",
) -> int:
    await db_manager.init_db()

    since_dt: datetime | None = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str)
        except ValueError:
            print(
                f"[!] Warning: invalid date format '{since_str}', ignoring --since filter."
            )

    async with db_manager.session() as session:
        report = await audit_service.run_audit(
            session=session,
            since=since_dt,
            region=region,
            window_days=window_days,
        )
        await session.commit()

    if format_type.lower() == "json":
        print(json.dumps(report, indent=2, default=str))
    else:
        print(report.get("markdown_report", ""))

    await db_manager.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="AetherGuard Ground-Truth Missed-Story Audit"
    )
    parser.add_argument(
        "--since",
        type=str,
        default="2026-09-01",
        help="Audit stories released on or after this ISO date (default: 2026-09-01)",
    )
    parser.add_argument(
        "--region",
        "-r",
        type=str,
        default=None,
        help="Filter audit by region (e.g. china, us, europe)",
    )
    parser.add_argument(
        "--window",
        "-w",
        type=int,
        default=7,
        help="Publication window tolerance in days (default: 7)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["table", "json"],
        default="table",
        help="Output format: table (markdown) or json",
    )

    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            run(
                since_str=args.since,
                region=args.region,
                window_days=args.window,
                format_type=args.format,
            )
        )
    )


if __name__ == "__main__":
    main()
