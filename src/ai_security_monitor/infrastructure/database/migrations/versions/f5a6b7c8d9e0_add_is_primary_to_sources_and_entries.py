"""add is_primary to sources and entries

Revision ID: f5a6b7c8d9e0
Revises: make_source_url_nullable
Create Date: 2026-10-30 23:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Add is_primary to sources
    sources_cols = [c["name"] for c in insp.get_columns("sources")]
    if "is_primary" not in sources_cols:
        op.add_column(
            "sources",
            sa.Column(
                "is_primary",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        op.create_index(
            "ix_sources_is_primary",
            "sources",
            ["is_primary"],
            unique=False,
        )

    # 2. Add is_primary to entries
    entries_cols = [c["name"] for c in insp.get_columns("entries")]
    if "is_primary" not in entries_cols:
        op.add_column(
            "entries",
            sa.Column(
                "is_primary",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        op.create_index(
            "ix_entries_is_primary",
            "entries",
            ["is_primary"],
            unique=False,
        )

    # 3. Backfill primary classification for known frontier labs, official repos, and arXiv
    op.execute(
        sa.text(
            """
            UPDATE sources
            SET is_primary = 1
            WHERE category IN ('ai_models', 'ai_research')
               OR type IN ('arxiv', 'github_trending')
               OR LOWER(name) LIKE '%openai%'
               OR LOWER(name) LIKE '%deepmind%'
               OR LOWER(name) LIKE '%deepseek%'
               OR LOWER(name) LIKE '%qwen%'
               OR LOWER(name) LIKE '%mistral%'
               OR LOWER(name) LIKE '%meta ai%'
               OR LOWER(name) LIKE '%anthropic%'
               OR LOWER(name) LIKE '%microsoft ai%'
               OR LOWER(name) LIKE '%nvidia%'
               OR LOWER(name) LIKE '%zhipu%'
               OR LOWER(name) LIKE '%moonshot%'
               OR LOWER(name) LIKE '%minimax%'
               OR LOWER(name) LIKE '%shanghai ai lab%'
               OR LOWER(name) LIKE '%internlm%'
               OR LOWER(name) LIKE '%huggingface%'
            """
        )
    )

    # 4. Backfill existing entries from sources.is_primary
    op.execute(
        sa.text(
            """
            UPDATE entries
            SET is_primary = 1
            WHERE source_id IN (SELECT id FROM sources WHERE is_primary = 1)
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    entries_cols = [c["name"] for c in insp.get_columns("entries")]
    if "is_primary" in entries_cols:
        op.drop_index("ix_entries_is_primary", table_name="entries")
        with op.batch_alter_table("entries") as batch_op:
            batch_op.drop_column("is_primary")

    sources_cols = [c["name"] for c in insp.get_columns("sources")]
    if "is_primary" in sources_cols:
        op.drop_index("ix_sources_is_primary", table_name="sources")
        with op.batch_alter_table("sources") as batch_op:
            batch_op.drop_column("is_primary")
