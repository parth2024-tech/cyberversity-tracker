#!/usr/bin/env python3
"""
CLI Report Script: Per-Source China Telemetry & Signal-to-Noise Ratio (SNR).
Run directly: python scripts/china_telemetry.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from rich.console import Console
from rich.table import Table

from ai_security_monitor.application.services.china_telemetry_service import (
    china_telemetry_service,
)
from ai_security_monitor.infrastructure.database.connection import db_manager


async def run_report():
    console = Console()
    await db_manager.init_db()

    console.print(
        "\n[bold cyan]🇨🇳 China AI Corridor — Per-Source Health, Yield & Signal-to-Noise Audit[/bold cyan]\n"
    )

    data = await china_telemetry_service.get_telemetry()

    table = Table(
        title=f"Source Telemetry & Yield Breakdown (Generated: {data['generated_at'][:19]})",
        show_lines=True,
    )
    table.add_column("Source Name", style="cyan", no_wrap=True)
    table.add_column("Health Status", justify="center")
    table.add_column("Category", style="magenta")
    table.add_column("DB Total", justify="right", style="bold white")
    table.add_column("14d Yield", justify="right", style="green")
    table.add_column("SNR %", justify="right")
    table.add_column("Sweeps", justify="right", style="dim")
    table.add_column("Diagnostic Finding", style="yellow")

    for s in data["sources"]:
        status = s["health_status"]
        if status == "healthy":
            status_badge = "[bold green]● HEALTHY[/bold green]"
        elif status == "operational":
            status_badge = "[green]● OPERATIONAL[/green]"
        elif status == "stale":
            status_badge = "[bold red]✖ STALE PINNED[/bold red]"
        elif status == "failing":
            status_badge = "[bold red]✖ FAILING[/bold red]"
        elif status == "degraded":
            status_badge = "[yellow]▲ DEGRADED[/yellow]"
        elif status == "zero_yield":
            status_badge = "[yellow]○ ZERO YIELD[/yellow]"
        elif status == "unpolled":
            status_badge = "[dim]◌ UNPOLLED[/dim]"
        else:
            status_badge = f"[dim]{status}[/dim]"

        snr = s["signal_to_noise_ratio_pct"]
        if snr >= 80.0:
            snr_badge = f"[bold green]{snr:.1f}%[/bold green]"
        elif snr >= 50.0:
            snr_badge = f"[yellow]{snr:.1f}%[/yellow]"
        elif s["total_entries_db"] > 0:
            snr_badge = f"[red]{snr:.1f}%[/red]"
        else:
            snr_badge = "[dim]0.0%[/dim]"

        table.add_row(
            s["source_name"][:40],
            status_badge,
            s["category"],
            str(s["total_entries_db"]),
            str(s["entries_last_14d"]),
            snr_badge,
            f"{s['total_sweeps']} (err: {s['error_sweeps']})",
            s["diagnosis"][:65],
        )

    console.print(table)

    console.print("\n[bold]Corridor Metrics:[/bold]")
    console.print(
        f"  • Total Configured Sources  : [bold cyan]{data['total_sources']}[/bold cyan]"
    )
    console.print(
        f"  • Active Yielding Sources   : [bold green]{data['active_sources']}[/bold green]"
    )
    console.print(
        f"  • Zero-Yield / Stale Feeds  : [bold yellow]{data['zero_yield_sources']}[/bold yellow]"
    )
    console.print(
        f"  • Total Ingested Entries    : [bold white]{data['total_entries_db']}[/bold white]"
    )
    console.print(
        f"  • Total AI Signal Entries   : [bold green]{data['total_signal_entries']}[/bold green]"
    )
    console.print(
        f"  • Corridor Signal-to-Noise  : [bold green]{data['overall_snr_pct']}%[/bold green]\n"
    )

    # Actionable Insights
    console.print("[bold]Diagnostic Action Items:[/bold]")
    for s in data["sources"]:
        if s["health_status"] == "stale":
            console.print(
                f"  [red]→ Upstream Update Required:[/red] [bold]{s['source_name']}[/bold] is pinned to a dormant repo ({s['url']}). Replace with active org or model family repo."
            )
        elif s["health_status"] == "degraded" or s["health_status"] == "failing":
            console.print(
                f"  [yellow]→ Network/Timeout Fix:[/yellow] [bold]{s['source_name']}[/bold] encountered fetch failure: {s['last_error_message']}"
            )

    console.print("")
    await db_manager.close()


if __name__ == "__main__":
    asyncio.run(run_report())
