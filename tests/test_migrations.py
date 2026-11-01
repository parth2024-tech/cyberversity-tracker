"""
Migration Chain Safety and CI Verification Suite (Defect Ledger D6).

Guarantees:
1. Single migration head (len(script.get_heads()) == 1).
2. Strictly linear migration ancestry from head down to <base> with no forks or orphan branches.
3. Clean upgrade from empty database to head.
4. Clean downgrade one step (-1) and re-upgrade to head.
5. Upgrade from existing historical database snapshot.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


@pytest.fixture
def alembic_config() -> Config:
    """Return Alembic config pointing to the repository alembic.ini."""
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    assert ini_path.exists(), f"alembic.ini not found at {ini_path}"
    return Config(str(ini_path))


def test_single_migration_head(alembic_config: Config) -> None:
    """Verify that Alembic has exactly one head revision."""
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Multiple migration heads detected: {heads}. "
        "Alembic migration chain must remain strictly linear."
    )


def test_linear_migration_ancestry(alembic_config: Config) -> None:
    """Verify that every revision in the chain has a strictly linear single-parent ancestry."""
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()
    assert len(heads) == 1
    head_rev = heads[0]

    visited = []
    curr = script.get_revision(head_rev)
    while curr is not None:
        visited.append(curr.revision)
        if curr.down_revision is None:
            break
        # down_revision must be a single string, not a tuple/list (which occurs on merge heads)
        assert isinstance(curr.down_revision, str), (
            f"Revision {curr.revision} has multiple parents: {curr.down_revision}"
        )
        curr = script.get_revision(curr.down_revision)

    assert len(visited) >= 6, f"Expected at least 6 migrations in chain, got {len(visited)}"


def test_upgrade_from_empty(alembic_config: Config, tmp_path: Path) -> None:
    """Verify upgrading an empty SQLite database to head succeeds cleanly."""
    empty_db = tmp_path / "empty_test.db"
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{empty_db}")

    script = ScriptDirectory.from_config(alembic_config)
    expected_head = script.get_heads()[0]

    command.upgrade(alembic_config, "head")

    # Verify alembic_version table in SQLite
    conn = sqlite3.connect(str(empty_db))
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == expected_head


def test_downgrade_one_step_and_reupgrade(alembic_config: Config, tmp_path: Path) -> None:
    """Verify downgrading -1 step and re-upgrading to head succeeds without errors."""
    test_db = tmp_path / "downgrade_test.db"
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{test_db}")

    script = ScriptDirectory.from_config(alembic_config)
    head_rev = script.get_heads()[0]
    head_script = script.get_revision(head_rev)
    expected_previous = head_script.down_revision
    assert isinstance(expected_previous, str)

    # 1. Upgrade to head
    command.upgrade(alembic_config, "head")

    # 2. Downgrade one step (-1)
    command.downgrade(alembic_config, "-1")

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == expected_previous

    # 3. Re-upgrade to head
    command.upgrade(alembic_config, "head")

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == head_rev


def test_upgrade_from_existing_snapshot(alembic_config: Config, tmp_path: Path) -> None:
    """Verify upgrading an existing database stamped at an earlier revision to head."""
    existing_db = tmp_path / "existing_snapshot.db"

    # Seed an earlier schema snapshot stamped at b8c1d4e2f5a0 (prior to c9d2e5f3a1b0)
    conn = sqlite3.connect(str(existing_db))
    conn.execute(
        "CREATE TABLE sources ("
        "id TEXT PRIMARY KEY, name TEXT UNIQUE, category TEXT, type TEXT, url TEXT, "
        "is_quarantined BOOLEAN DEFAULT 0, consecutive_failures INTEGER DEFAULT 0, "
        "quarantined_at DATETIME, quarantine_reason TEXT, created_at DATETIME, updated_at DATETIME"
        ");"
    )
    conn.execute(
        "CREATE TABLE entries ("
        "id TEXT PRIMARY KEY, source_id TEXT, title TEXT, url TEXT, content_hash TEXT UNIQUE, "
        "published_at DATETIME, fetched_at DATETIME, created_at DATETIME, updated_at DATETIME, category TEXT"
        ");"
    )
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);")
    conn.execute("INSERT INTO alembic_version VALUES ('b8c1d4e2f5a0');")
    conn.commit()
    conn.close()

    alembic_config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{existing_db}")
    command.upgrade(alembic_config, "head")

    # Verify head reached and entry_entities created
    conn = sqlite3.connect(str(existing_db))
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "c9d2e5f3a1b0"

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entry_entities'")
    table_row = cur.fetchone()
    assert table_row is not None
    conn.close()
