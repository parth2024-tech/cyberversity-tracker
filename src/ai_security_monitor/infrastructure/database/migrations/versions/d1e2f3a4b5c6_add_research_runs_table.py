"""add_research_runs_table

Revision ID: d1e2f3a4b5c6
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c9d2e5f3a1b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create research_runs audit and replay table."""
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column(
            "sources_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("execution_steps", sa.JSON(), nullable=True),
        sa.Column(
            "cost_estimate", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column(
            "coverage_score", sa.Float(), nullable=False, server_default=sa.text("1.0")
        ),
        sa.Column("output_markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("research_runs", schema=None) as batch_op:
        batch_op.create_index("ix_research_runs_query", ["query"], unique=False)
        batch_op.create_index(
            "ix_research_runs_created_at", ["created_at"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema - drop research_runs table."""
    with op.batch_alter_table("research_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_research_runs_created_at")
        batch_op.drop_index("ix_research_runs_query")
    op.drop_table("research_runs")
