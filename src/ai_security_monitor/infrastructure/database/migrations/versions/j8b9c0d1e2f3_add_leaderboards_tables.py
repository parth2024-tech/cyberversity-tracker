"""add leaderboards and leaderboard_snapshots tables (Feature 8)

Revision ID: j8b9c0d1e2f3
Revises: make_source_url_nullable
Create Date: 2026-10-31 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create leaderboards and leaderboard_snapshots tables."""
    op.create_table(
        "leaderboards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("parser", sa.String(length=50), nullable=False),
        sa.Column(
            "category", sa.String(length=50), nullable=False, server_default="general"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OK"),
        sa.Column("last_snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_leaderboards_name", "leaderboards", ["name"], unique=True)
    op.create_index(
        "ix_leaderboards_enabled", "leaderboards", ["enabled"], unique=False
    )

    op.create_table(
        "leaderboard_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("leaderboard_id", sa.String(length=36), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_json", sa.JSON(), nullable=False),
        sa.Column("diff_events_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["leaderboard_id"], ["leaderboards.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_leaderboard_snapshots_leaderboard_id",
        "leaderboard_snapshots",
        ["leaderboard_id"],
        unique=False,
    )
    op.create_index(
        "ix_leaderboard_snapshots_taken_at",
        "leaderboard_snapshots",
        ["taken_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop leaderboard_snapshots and leaderboards tables."""
    op.drop_index(
        "ix_leaderboard_snapshots_taken_at", table_name="leaderboard_snapshots"
    )
    op.drop_index(
        "ix_leaderboard_snapshots_leaderboard_id", table_name="leaderboard_snapshots"
    )
    op.drop_table("leaderboard_snapshots")

    op.drop_index("ix_leaderboards_enabled", table_name="leaderboards")
    op.drop_index("ix_leaderboards_name", table_name="leaderboards")
    op.drop_table("leaderboards")
