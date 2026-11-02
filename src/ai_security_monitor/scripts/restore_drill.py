"""
Verifiable Restore Drill CLI (Workstream C1).
Decrypts age-encrypted SQLite backup snapshot, verifies PRAGMA integrity_check,
and asserts table row-count parity against reference database.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ai_security_monitor.application.services.backup_service import BackupService

console = Console()


def run_drill(
    backup_file: Path,
    secret_key: str,
    target_db: Path,
    reference_db: Path | None = None,
    cleanup: bool = False,
) -> int:
    """Execute verifiable restore drill and display formatted outcome."""
    console.print(f"[bold cyan]🔍 Initiating AetherGuard Restore Drill on {backup_file.name}...[/bold cyan]")

    service = BackupService()
    result = service.restore_and_verify(
        encrypted_path=backup_file,
        secret_key=secret_key,
        target_db_path=target_db,
        reference_db_path=reference_db,
    )

    table = Table(title="Restore Drill Verification Report")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Backup File", str(backup_file))
    table.add_row("Restored Target DB", str(target_db))
    table.add_row(
        "PRAGMA Integrity Check",
        "[bold green]PASSED (ok)[/bold green]" if result.integrity_check_passed else "[bold red]FAILED[/bold red]",
    )
    table.add_row(
        "Overall Parity Verified",
        "[bold green]VERIFIED (100% Match)[/bold green]"
        if result.parity_verified
        else ("[bold yellow]SKIPPED (No reference provided)[/bold yellow]" if not reference_db else "[bold red]MISMATCH DETECTED[/bold red]"),
    )
    table.add_row("Drill Duration", f"{result.duration_seconds}s")

    console.print(table)

    if result.table_counts:
        count_table = Table(title="Restored SQLite Table Row Counts")
        count_table.add_column("Table Name", style="cyan")
        count_table.add_column("Restored Rows", style="green")
        if reference_db:
            count_table.add_column("Reference Rows", style="yellow")
            count_table.add_column("Parity", style="bold")

        for tbl, cnt in sorted(result.table_counts.items()):
            if reference_db:
                ref_cnt = result.parity_details.get("reference", {}).get(tbl, 0)
                status = "[green]✓ MATCH[/green]" if cnt == ref_cnt else f"[red]✗ DIFF ({cnt - ref_cnt})[/red]"
                count_table.add_row(tbl, str(cnt), str(ref_cnt), status)
            else:
                count_table.add_row(tbl, str(cnt))

        console.print(count_table)

    if cleanup and target_db.exists():
        try:
            target_db.unlink()
            console.print("[dim]Cleaned up temporary restored database.[/dim]")
        except OSError:
            pass

    if not result.success:
        console.print(f"[bold red]❌ Restore drill FAILED: {result.error_message}[/bold red]")
        return 1

    console.print("[bold green]✅ Restore drill SUCCEEDED! Database backup is valid and intact.[/bold green]")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and restore an encrypted age-protected SQLite backup snapshot."
    )
    parser.add_argument(
        "--backup-file",
        "-b",
        type=Path,
        required=True,
        help="Path to .db.gz.age encrypted backup file",
    )
    parser.add_argument(
        "--secret-key",
        "-k",
        type=str,
        default=os.environ.get("BACKUP_AGE_SECRET_KEY"),
        help="Age secret identity key (AGE-SECRET-KEY-1...). Defaults to BACKUP_AGE_SECRET_KEY env var.",
    )
    parser.add_argument(
        "--target-db",
        "-t",
        type=Path,
        default=None,
        help="Destination path for restored SQLite database",
    )
    parser.add_argument(
        "--reference-db",
        "-r",
        type=Path,
        default=None,
        help="Optional path to reference SQLite DB for row-count parity check",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete restored database after verification passes",
    )

    args = parser.parse_args()

    if not args.secret_key:
        console.print("[bold red]Error: Age secret key required via --secret-key or BACKUP_AGE_SECRET_KEY env var.[/bold red]")
        sys.exit(1)

    target_db = args.target_db
    if not target_db:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        target_db = Path(f"/tmp/restore_drill_{timestamp}.db")

    exit_code = run_drill(
        backup_file=args.backup_file,
        secret_key=args.secret_key,
        target_db=target_db,
        reference_db=args.reference_db,
        cleanup=args.cleanup,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
