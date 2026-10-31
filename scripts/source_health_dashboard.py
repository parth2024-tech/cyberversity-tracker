#!/usr/bin/env python3
"""
AetherGuard Source Health Dashboard CLI script.
Synchronizes deterministic source health states from SQLite fetch_log & entries tables,
and renders a rich dashboard table sorted worst-first.
"""

import asyncio
import os
import sys

from rich.console import Console
from rich.table import Table

# Add project root to sys.path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.application.services.source_health_service import (
    source_health_service,
)
from ai_security_monitor.infrastructure.database.connection import db_manager


async def run_dashboard(
    state_filter: str | None = None,
    region_filter: str | None = None,
    sync_first: bool = True,
):
    console = Console()
    await db_manager.init_db()
    service = MonitorService()

    async with service._uow_factory() as uow:
        if sync_first:
            console.print(
                "[bold cyan]🔄 Synchronizing source health states from database history...[/bold cyan]"
            )
            summary = await source_health_service.sync_all_from_db(uow.session)
            await uow.commit()
            console.print(
                f"[green]✓ Synchronized {summary['total_sources']} sources:[/green] "
                f"BLOCKED={summary['counts']['BLOCKED']}, "
                f"REDIRECTED={summary['counts']['REDIRECTED']}, "
                f"DEAD={summary['counts']['DEAD']}, "
                f"STALE={summary['counts']['STALE']}, "
                f"OK={summary['counts']['OK']}\n"
            )

        repo = uow.source_health
        results = await repo.list(state=state_filter, region=region_filter)

    table = Table(title="AetherGuard Source Health Dashboard (Worst-First Ordering)")
    table.add_column("State", style="bold")
    table.add_column("Source", style="white")
    table.add_column("Region", style="cyan")
    table.add_column("Tier", justify="right", style="magenta")
    table.add_column("Last New Entry", style="yellow")
    table.add_column("Last Status", style="blue")
    table.add_column("7d Yield", justify="right", style="green")
    table.add_column("Failures", justify="right", style="red")
    table.add_column("Zero Runs", justify="right", style="dim")
    table.add_column("Diagnosis / Detail", style="dim italic")

    state_colors = {
        "BLOCKED": "[bold white on red] BLOCKED [/]",
        "REDIRECTED": "[bold black on yellow] REDIRECTED [/]",
        "DEAD": "[bold red] DEAD [/]",
        "STALE": "[bold yellow] STALE [/]",
        "PENDING": "[bold cyan] PENDING [/]",
        "OK": "[bold green] OK [/]",
    }

    for r in results:
        st = r["state"]
        st_badge = state_colors.get(st, st)
        last_entry = r["last_new_entry_at"][:19] if r["last_new_entry_at"] else "Never"
        last_status = str(r["last_http_status"]) if r["last_http_status"] else "N/A"
        diag = (r["error_message"] or "")[:40]
        table.add_row(
            st_badge,
            r["source_name"],
            r["region"].upper(),
            f"T{r['tier']:.1f}",
            last_entry,
            last_status,
            str(r["seven_day_yield"]),
            str(r["consecutive_failures"]),
            str(r["consecutive_zero_runs"]),
            diag,
        )

    console.print(table)
    console.print(
        f"[bold white]Total sources matching query:[/bold white] [cyan]{len(results)}[/cyan]\n"
    )
    await db_manager.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AetherGuard Source Health Dashboard")
    parser.add_argument(
        "--state", "-s", help="Filter by state (OK, STALE, DEAD, BLOCKED, REDIRECTED)"
    )
    parser.add_argument(
        "--region", "-r", help="Filter by region (e.g. china, global, europe, us)"
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip synchronizing from fetch_logs before display",
    )
    args = parser.parse_args()

    asyncio.run(
        run_dashboard(
            state_filter=args.state,
            region_filter=args.region,
            sync_first=not args.no_sync,
        )
    )


if __name__ == "__main__":
    main()
