"""cleanup_orphans_and_enforce_foreign_keys

Revision ID: a1b2c3d4e5f6
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c9d2e5f3a1b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - clean up orphan rows across dependent tables and create cascade triggers."""
    conn = op.get_bind()

    # 1. Clean up any existing orphan rows in foreign-key referencing tables (Defect Ledger D7)
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    if "entry_analysis" in tables and "entries" in tables:
        conn.execute(
            sa.text(
                "DELETE FROM entry_analysis WHERE entry_id NOT IN (SELECT id FROM entries)"
            )
        )

    if "entry_entities" in tables and "entries" in tables:
        conn.execute(
            sa.text(
                "DELETE FROM entry_entities WHERE entry_id NOT IN (SELECT id FROM entries)"
            )
        )

    if "llm_receipts" in tables and "entries" in tables:
        llm_cols = {col["name"] for col in insp.get_columns("llm_receipts")}
        if "entry_id" in llm_cols:
            conn.execute(
                sa.text(
                    "DELETE FROM llm_receipts WHERE entry_id IS NOT NULL AND entry_id NOT IN (SELECT id FROM entries)"
                )
            )

    if "analysis_outcome" in tables and "entry_analysis" in tables:
        conn.execute(
            sa.text(
                "DELETE FROM analysis_outcome WHERE analysis_id NOT IN (SELECT id FROM entry_analysis)"
            )
        )

    # 2. Create SQLite cascade triggers ensuring dependent rows are deleted even under raw SQL
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS entries_analysis_ad AFTER DELETE ON entries BEGIN "
            "DELETE FROM entry_analysis WHERE entry_id = old.id; "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS entries_entities_ad AFTER DELETE ON entries BEGIN "
            "DELETE FROM entry_entities WHERE entry_id = old.id; "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS entries_receipts_ad AFTER DELETE ON entries BEGIN "
            "DELETE FROM llm_receipts WHERE entry_id = old.id; "
            "END;"
        )
    )


def downgrade() -> None:
    """Downgrade schema - drop cascade deletion triggers."""
    conn = op.get_bind()
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_analysis_ad"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_entities_ad"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_receipts_ad"))
