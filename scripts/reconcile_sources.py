#!/usr/bin/env python3
"""
Reconcile Sources Script.

Audits and synchronizes database sources against sources.yaml.
Soft-deactivates (enabled=False) orphaned sources that were purged from sources.yaml
while safeguarding user-created sources and preserving historical records.

Usage:
    python scripts/reconcile_sources.py           # Default: dry-run mode
    python scripts/reconcile_sources.py --apply   # Apply changes to database
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_security_monitor.config.sources import load_sources_from_yaml
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


async def reconcile(config_path: str | None = None, apply: bool = False) -> int:
    mode_str = "APPLY (WRITING TO DB)" if apply else "DRY-RUN (NO CHANGES MADE)"
    print(f"\n=== Reconciling Database Sources vs Configuration [{mode_str}] ===")

    sources_cfg = load_sources_from_yaml(config_path)
    print(f"Loaded {len(sources_cfg)} sources from YAML config.")

    min_expected = 50
    if len(sources_cfg) < min_expected:
        print(f"ERROR: YAML config has only {len(sources_cfg)} sources (< {min_expected}). Aborting reconciliation to protect catalog.")
        return 1

    yaml_names = {s.name.strip().lower(): s for s in sources_cfg}
    yaml_urls = {s.url.strip().lower(): s for s in sources_cfg if s.url and s.url.strip()}

    await db_manager.init_db()

    async with SqlAlchemyUnitOfWork() as uow:
        db_sources = await uow.sources.list(enabled_only=False)
        print(f"Found {len(db_sources)} total sources in database.\n")

        matched_active = []
        orphans_to_deactivate = []
        user_managed_sources = []
        already_disabled = []

        for s in db_sources:
            name_key = s.name.strip().lower()
            url_key = s.url.strip().lower() if s.url else ""

            # Check if user-managed
            origin = (s.config or {}).get("origin")
            if origin in ("user", "custom", "manual"):
                user_managed_sources.append(s)
                continue

            # Check if matches YAML by name or URL
            in_yaml = name_key in yaml_names or (url_key and url_key in yaml_urls)

            if in_yaml:
                if s.enabled:
                    matched_active.append(s)
                else:
                    # In YAML but currently disabled in DB
                    matched_active.append(s)
            else:
                if s.enabled:
                    orphans_to_deactivate.append(s)
                else:
                    already_disabled.append(s)

        print("Summary Analysis:")
        print(f"  - Active YAML sources matching:     {len(matched_active)}")
        print(f"  - User/custom-managed sources:       {len(user_managed_sources)}")
        print(f"  - Already disabled orphaned sources: {len(already_disabled)}")
        print(f"  - Enabled orphans to deactivate:     {len(orphans_to_deactivate)}")

        if orphans_to_deactivate:
            print(f"\nOrphaned Sources to Soft-Deactivate ({len(orphans_to_deactivate)}):")
            for s in sorted(orphans_to_deactivate, key=lambda x: x.name):
                print(f"  [DEACTIVATE] {s.name} ({s.category.value}) - URL: {s.url or 'N/A'}")

            if apply:
                for s in orphans_to_deactivate:
                    s.enabled = False
                    await uow.sources.update(s)
                await uow.commit()
                print(f"\nSUCCESS: Soft-deactivated {len(orphans_to_deactivate)} orphaned sources in database.")
            else:
                print(f"\nDRY-RUN COMPLETE: Run with --apply to commit these {len(orphans_to_deactivate)} deactivations.")
        else:
            print("\nDatabase is already in sync with YAML configuration. No deactivations needed.")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Reconcile database sources against sources.yaml")
    parser.add_argument("--config", help="Path to sources.yaml", default=None)
    parser.add_argument("--apply", action="store_true", help="Apply changes (defaults to dry-run)")
    args = parser.parse_args()

    sys.exit(asyncio.run(reconcile(args.config, args.apply)))


if __name__ == "__main__":
    main()
