"""add no-slop filter entries_filtered and filtered_entries table

Revision ID: e4f5a6b7c8d9
Revises: make_source_url_nullable
Create Date: 2026-10-30 22:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add entries_filtered column to fetch_log if not exists
    bind = op.get_bind()
    insp = sa.inspect(bind)
    fetch_log_cols = [c["name"] for c in insp.get_columns("fetch_log")]
    if "entries_filtered" not in fetch_log_cols:
        op.add_column(
            "fetch_log",
            sa.Column(
                "entries_filtered",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    # 2. Create filtered_entries table for 7-day inspection audit trail
    if not insp.has_table("filtered_entries"):
        op.create_table(
            "filtered_entries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=False),
            sa.Column("source_name", sa.String(length=255), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("reason", sa.String(length=100), nullable=False),
            sa.Column("matched_pattern", sa.String(length=255), nullable=True),
            sa.Column(
                "filtered_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
            ),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["sources.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_filtered_entries_source_filtered",
            "filtered_entries",
            ["source_id", "filtered_at"],
            unique=False,
        )
        op.create_index(
            "ix_filtered_entries_filtered_at",
            "filtered_entries",
            ["filtered_at"],
            unique=False,
        )
        op.create_index(
            "ix_filtered_entries_reason",
            "filtered_entries",
            ["reason"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("filtered_entries"):
        op.drop_index("ix_filtered_entries_reason", table_name="filtered_entries")
        op.drop_index("ix_filtered_entries_filtered_at", table_name="filtered_entries")
        op.drop_index("ix_filtered_entries_source_filtered", table_name="filtered_entries")
        op.drop_table("filtered_entries")

    fetch_log_cols = [c["name"] for c in insp.get_columns("fetch_log")]
    if "entries_filtered" in fetch_log_cols:
        with op.batch_alter_table("fetch_log") as batch_op:
            batch_op.drop_column("entries_filtered")
