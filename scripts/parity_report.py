#!/usr/bin/env python3
"""
Language-Parity SLO Telemetry CLI.

Generates executive reports on Chinese vs English capture ratios,
ingestion latency distribution, and compliance against the <= 1.25x SLO target.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from ai_security_monitor.application.services.language_parity_service import (
    language_parity_service,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    unit_of_work,
)


async def run_report(
    days: int,
    save_snapshot: bool,
    output_json: bool,
    check_slo: bool,
    uow: UnitOfWork | None = None,
) -> int:
    async def _execute(active_uow: UnitOfWork) -> int:
        metrics = await language_parity_service.compute_parity_metrics(
            active_uow.session, days=days
        )

        if save_snapshot:
            snapshot = await language_parity_service.record_snapshot(
                active_uow.session, metrics
            )
            print(f"[+] Persisted parity snapshot: {snapshot.id}", file=sys.stderr)

        if output_json:
            print(json.dumps(metrics.to_dict(), indent=2))
        else:
            report_md = language_parity_service.format_markdown_report(metrics)
            print(report_md)

        if check_slo:
            if not metrics.slo_capture_active:
                print(
                    "\n[!] SLO VIOLATION: Zero native Chinese documents captured in trailing window.",
                    file=sys.stderr,
                )
                return 1
            print(
                "\n[+] SLO COMPLIANT: Native multilingual intelligence intake is active.",
                file=sys.stderr,
            )

        return 0

    if uow is not None:
        return await _execute(uow)
    else:
        async with unit_of_work() as active_uow:
            return await _execute(active_uow)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Multilingual Language-Parity SLO Telemetry Reporter"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Trailing time window in days (default: 7)",
    )
    parser.add_argument(
        "--save-snapshot",
        action="store_true",
        help="Persist telemetry snapshot into parity_snapshots table",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw telemetry metrics in JSON format",
    )
    parser.add_argument(
        "--check-slo",
        action="store_true",
        help="Validate capture active SLO, exiting with code 1 if violated",
    )

    args = parser.parse_args()
    return asyncio.run(
        run_report(
            days=args.days,
            save_snapshot=args.save_snapshot,
            output_json=args.json,
            check_slo=args.check_slo,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
