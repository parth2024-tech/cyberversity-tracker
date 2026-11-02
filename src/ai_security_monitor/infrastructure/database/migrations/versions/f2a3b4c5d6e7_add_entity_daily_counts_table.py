"""add_entity_daily_counts_table

Revision ID: f2a3b4c5d6e7
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 01:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create entity_daily_counts table."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "entity_daily_counts" in insp.get_table_names():
        return

    op.create_table(
        "entity_daily_counts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_name", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("bucket_date", sa.String(length=10), nullable=False),
        sa.Column(
            "mention_count", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("entity_daily_counts", schema=None) as batch_op:
        batch_op.create_index(
            "uq_entity_daily_counts_key_date",
            ["entity_name", "entity_type", "bucket_date"],
            unique=True,
        )
        batch_op.create_index(
            "ix_entity_daily_counts_date_type",
            ["bucket_date", "entity_type"],
            unique=False,
        )
        batch_op.create_index(
            "ix_entity_daily_counts_entity_name",
            ["entity_name"],
            unique=False,
        )
        batch_op.create_index(
            "ix_entity_daily_counts_bucket_date",
            ["bucket_date"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema - drop entity_daily_counts table."""
    with op.batch_alter_table("entity_daily_counts", schema=None) as batch_op:
        batch_op.drop_index("ix_entity_daily_counts_bucket_date")
        batch_op.drop_index("ix_entity_daily_counts_entity_name")
        batch_op.drop_index("ix_entity_daily_counts_date_type")
        batch_op.drop_index("uq_entity_daily_counts_key_date")

    op.drop_table("entity_daily_counts")
