"""add stories table and story foreign key to entries

Revision ID: g6b7c8d9e0f1
Revises: make_source_url_nullable
Create Date: 2026-10-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g6b7c8d9e0f1"
down_revision: str | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Create stories table if it does not exist
    if not insp.has_table("stories"):
        op.create_table(
            "stories",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("cluster_key", sa.String(255), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column(
                "canonical_url", sa.String(1000), nullable=False, server_default=""
            ),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "category", sa.String(50), nullable=False, server_default="ai_models"
            ),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column(
                "first_source_id",
                sa.String(36),
                sa.ForeignKey("sources.id", name="fk_stories_first_source_id"),
                nullable=True,
            ),
            sa.Column("language_mix", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("source_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("entry_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "confidence_score", sa.Float(), nullable=False, server_default="0.5"
            ),
            sa.Column("heat_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("heat_badge", sa.String(20), nullable=True),
            sa.Column(
                "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column("anchor_entry_id", sa.String(36), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_stories_cluster_key", "stories", ["cluster_key"], unique=False
        )
        op.create_index(
            "ix_stories_first_seen_at", "stories", ["first_seen_at"], unique=False
        )
        op.create_index(
            "ix_stories_last_seen_at", "stories", ["last_seen_at"], unique=False
        )
        op.create_index(
            "ix_stories_first_source_id", "stories", ["first_source_id"], unique=False
        )

    # 2. Add story_id column to entries if not present
    entries_cols = [c["name"] for c in insp.get_columns("entries")]
    if "story_id" not in entries_cols:
        with op.batch_alter_table("entries", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "story_id",
                    sa.String(36),
                    sa.ForeignKey("stories.id", name="fk_entries_story_id"),
                    nullable=True,
                )
            )
        op.create_index("ix_entries_story_id", "entries", ["story_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    entries_cols = [c["name"] for c in insp.get_columns("entries")]
    if "story_id" in entries_cols:
        indexes = [idx["name"] for idx in insp.get_indexes("entries")]
        if "ix_entries_story_id" in indexes:
            op.drop_index("ix_entries_story_id", table_name="entries")
        with op.batch_alter_table("entries", schema=None) as batch_op:
            batch_op.drop_column("story_id")

    if insp.has_table("stories"):
        op.drop_index("ix_stories_first_source_id", table_name="stories")
        op.drop_index("ix_stories_last_seen_at", table_name="stories")
        op.drop_index("ix_stories_first_seen_at", table_name="stories")
        op.drop_index("ix_stories_cluster_key", table_name="stories")
        op.drop_table("stories")
