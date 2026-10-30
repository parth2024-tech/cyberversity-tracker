#!/usr/bin/env python3
"""
Frontier AI Lab & Regional Coverage Report Script.

Computes regional source and entry shares, tracks frontier AI lab coverage,
identifies intelligence gaps and silent labs, and outputs copy-pasteable Markdown or JSON.

Usage:
    python scripts/coverage_report.py                  # Full global ecosystem report
    python scripts/coverage_report.py --region china   # China corridor breakdown
    python scripts/coverage_report.py --format json    # Structured JSON output
    python scripts/coverage_report.py --backfill       # Backfill lab tags on untagged entries
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_security_monitor.application.services.coverage_service import coverage_service
from ai_security_monitor.infrastructure.database.connection import db_manager


async def run_report(
    region: str | None = None,
    format_type: str = "table",
    backfill: bool = False,
) -> int:
    await db_manager.init_db()

    async with db_manager.session() as session:
        if backfill:
            tagged = await coverage_service.backfill_entry_labs(session)
            await session.commit()
            print(f"[+] Tagged {tagged} entries with frontier AI labs.")

        report = await coverage_service.generate_coverage_report(
            session, target_region=region
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
        description="AetherGuard Frontier AI Lab & Regional Coverage Report"
    )
    parser.add_argument(
        "--region",
        "-r",
        type=str,
        default=None,
        help="Filter report by region (e.g. china, us, europe)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["table", "json"],
        default="table",
        help="Output format: table (markdown) or json",
    )
    parser.add_argument(
        "--backfill",
        "-b",
        action="store_true",
        help="Run lab tagging backfill on existing entries before reporting",
    )

    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            run_report(
                region=args.region,
                format_type=args.format,
                backfill=args.backfill,
            )
        )
    )


if __name__ == "__main__":
    main()
