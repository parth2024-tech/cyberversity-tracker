"""add_source_health_table

Revision ID: b1c2d3e4f5a6
Revises: make_source_url_nullable
Create Date: 2026-10-30 20:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add source_health table and fetch_log columns."""
    # 1. Create source_health table
    op.create_table(
        "source_health",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("last_fetch_at", sa.DateTime(), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_new_entry_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_zero_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state", sa.String(length=20), server_default="OK", nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("seven_day_yield", sa.Integer(), server_default="0", nullable=False),
        sa.Column("entries_filtered_last", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_source_health_source_id", "source_health", ["source_id"], unique=True)
    op.create_index("ix_source_health_state", "source_health", ["state"])
    op.create_index("ix_source_health_updated", "source_health", ["updated_at"])

    # 2. Add entries_filtered and http_status to fetch_log if not already present
    with op.batch_alter_table("fetch_log", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("entries_filtered", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("http_status", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("fetch_log", schema=None) as batch_op:
        batch_op.drop_column("http_status")
        batch_op.drop_column("entries_filtered")

    op.drop_index("ix_source_health_updated", table_name="source_health")
    op.drop_index("ix_source_health_state", table_name="source_health")
    op.drop_index("ix_source_health_source_id", table_name="source_health")
    op.drop_table("source_health")
