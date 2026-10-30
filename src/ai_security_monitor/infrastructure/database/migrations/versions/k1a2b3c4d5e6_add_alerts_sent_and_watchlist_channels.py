"""Add alerts_sent table and watchlist rules channels.

Revision ID: k1a2b3c4d5e6
Revises: make_source_url_nullable
Create Date: 2026-10-31 02:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create alerts_sent table and add channel/rule filters to watchlist_rules."""
    op.create_table(
        "alerts_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("watch_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_sent_watch_id", "alerts_sent", ["watch_id"])
    op.create_index("ix_alerts_sent_entry_id", "alerts_sent", ["entry_id"])
    op.create_index("ix_alerts_sent_story_id", "alerts_sent", ["story_id"])
    op.create_index("ix_alerts_sent_sent_at", "alerts_sent", ["sent_at"])
    op.create_index(
        "ix_alerts_sent_watch_entry", "alerts_sent", ["watch_id", "entry_id"]
    )
    op.create_index(
        "ix_alerts_sent_watch_story", "alerts_sent", ["watch_id", "story_id"]
    )

    with op.batch_alter_table("watchlist_rules", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lab", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("model_family", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(sa.Column("region", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("min_score", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "channel",
                sa.String(length=50),
                nullable=False,
                server_default="telegram",
            )
        )
        batch_op.add_column(sa.Column("channel_config", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rules_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop alerts_sent table and remove channel/rule filters from watchlist_rules."""
    with op.batch_alter_table("watchlist_rules", schema=None) as batch_op:
        batch_op.drop_column("rules_json")
        batch_op.drop_column("channel_config")
        batch_op.drop_column("channel")
        batch_op.drop_column("min_score")
        batch_op.drop_column("region")
        batch_op.drop_column("model_family")
        batch_op.drop_column("lab")

    op.drop_index("ix_alerts_sent_watch_story", table_name="alerts_sent")
    op.drop_index("ix_alerts_sent_watch_entry", table_name="alerts_sent")
    op.drop_index("ix_alerts_sent_sent_at", table_name="alerts_sent")
    op.drop_index("ix_alerts_sent_story_id", table_name="alerts_sent")
    op.drop_index("ix_alerts_sent_entry_id", table_name="alerts_sent")
    op.drop_index("ix_alerts_sent_watch_id", table_name="alerts_sent")
    op.drop_table("alerts_sent")
