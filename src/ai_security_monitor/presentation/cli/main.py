"""
Typer CLI application for AI Security Monitor.
"""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.infrastructure.database.connection import db_manager

app = typer.Typer(
    name="ai-security-monitor",
    help="Autonomous AI Security Threat Radar & Intelligence CLI",
    add_completion=False,
)
console = Console()


@app.command()
def server(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host address"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on code change"),
):
    """Launch the real-time web command center and API server."""
    import os
    import uvicorn
    # Support cloud runtime PORT environment variable (Render, Fly.io, etc.)
    env_port = os.environ.get("PORT") or os.environ.get("API_PORT")
    if env_port and port == 8000:
        try:
            port = int(env_port)
        except ValueError:
            pass

    console.print(f"[bold cyan]🚀 Launching AI Security Monitor Command Center on http://{host}:{port}[/bold cyan]")
    uvicorn.run("ai_security_monitor.presentation.api.main:app", host=host, port=port, reload=reload)


@app.command()
def fetch(
    force: bool = typer.Option(False, "--force", "-f", help="Force sweep without rate limit cache"),
):
    """Execute an immediate intelligence sweep across all active sources."""
    async def _run():
        await db_manager.init_db()
        service = MonitorService()
        console.print("[bold yellow]📡 Sweeping intelligence feeds & academic zero-days...[/bold yellow]")
        res = await service.fetch_all(force=force)

        table = Table(title="Sweep Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Sources Checked", str(res["total_sources"]))
        table.add_row("Successful Sweeps", str(res["success"]))
        table.add_row("Errors", str(res["error"]))
        table.add_row("New Entries Ingested & Analyzed", str(res["total_new"]))
        console.print(table)
        await db_manager.close()

    asyncio.run(_run())


@app.command()
def stats():
    """Display real-time database intelligence statistics and metrics."""
    async def _run():
        await db_manager.init_db()
        service = MonitorService()
        data = await service.get_stats()

        console.print("\n[bold cyan]📊 AetherGuard Threat Telemetry[/bold cyan]")
        console.print("=" * 45)
        console.print(f"Total Tracked Entries:     [bold white]{data['total_entries']}[/bold white]")
        console.print(f"Active Sources:            [bold white]{data['total_sources']}[/bold white]")
        console.print(f"⚡ High Velocity Threats:  [bold red]{data['high_velocity_entries']}[/bold red]")
        console.print(f"⚠️ Pre-CVE Zero-Day Warns: [bold yellow]{data['pre_cve_warnings']}[/bold yellow]")

        console.print("\n[bold]Entries by Category:[/bold]")
        for cat, count in data.get("by_category", {}).items():
            console.print(f"  • {cat.replace('_', ' ').title()}: [cyan]{count}[/cyan]")
        await db_manager.close()

    asyncio.run(_run())


@app.command()
def sources():
    """List all registered and configured intelligence sources."""
    async def _run():
        await db_manager.init_db()
        service = MonitorService()
        await service.init_sources()

        async with service._uow_factory() as uow:
            srcs = await uow.sources.list()

        table = Table(title="Configured Threat Feeds & Channels")
        table.add_column("Status", style="bold")
        table.add_column("Name", style="white")
        table.add_column("Type", style="cyan")
        table.add_column("Category", style="yellow")
        table.add_column("Rate Limit", style="magenta")

        for s in srcs:
            status_icon = "[green]● ACTIVE[/green]" if s.enabled else "[red]○ DISABLED[/red]"
            table.add_row(status_icon, s.name, s.type.value, s.category.value, f"{s.rate_limit_seconds}s")

        console.print(table)
        await db_manager.close()

    asyncio.run(_run())


def main():
    app()


if __name__ == "__main__":
    main()
