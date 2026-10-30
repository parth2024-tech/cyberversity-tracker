"""add score_v2 and score_components_json to entry_analysis

Revision ID: h4c8d9e0f1a2
Revises: make_source_url_nullable
Create Date: 2026-10-31 00:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h4c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add score_v2 and score_components_json to entry_analysis."""
    with op.batch_alter_table("entry_analysis", schema=None) as batch_op:
        batch_op.add_column(sa.Column("score_v2", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "score_components_json",
                sa.JSON(),
                nullable=True,
            )
        )
        batch_op.create_index("ix_entry_analysis_score_v2", ["score_v2"], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop score_v2 and score_components_json from entry_analysis."""
    with op.batch_alter_table("entry_analysis", schema=None) as batch_op:
        batch_op.drop_index("ix_entry_analysis_score_v2")
        batch_op.drop_column("score_components_json")
        batch_op.drop_column("score_v2")
