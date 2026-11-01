"""add_council_reviews_table

Revision ID: d1e2f3a4b5c6
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 14:30:00.000000

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
    """Upgrade schema - create council_reviews table for multi-agent council in shadow mode."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "council_reviews" in insp.get_table_names():
        return

    op.create_table(
        "council_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="shadow", nullable=False
        ),
        sa.Column("consensus_verdict", sa.String(length=50), nullable=False),
        sa.Column("consensus_score", sa.Float(), nullable=False),
        sa.Column("consensus_summary", sa.Text(), nullable=False),
        sa.Column("persona_evaluations", sa.JSON(), nullable=False),
        sa.Column("verified_claims", sa.JSON(), nullable=False),
        sa.Column("receipt_keys", sa.JSON(), nullable=False),
        sa.Column(
            "total_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "total_latency_ms",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "estimated_cost_usd",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("council_reviews", schema=None) as batch_op:
        batch_op.create_index("ix_council_reviews_entry_id", ["entry_id"], unique=False)
        batch_op.create_index("ix_council_reviews_status", ["status"], unique=False)
        batch_op.create_index(
            "ix_council_reviews_entry_status", ["entry_id", "status"], unique=False
        )
        batch_op.create_index(
            "ix_council_reviews_created_verdict",
            ["created_at", "consensus_verdict"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema - drop council_reviews table."""
    with op.batch_alter_table("council_reviews", schema=None) as batch_op:
        batch_op.drop_index("ix_council_reviews_created_verdict")
        batch_op.drop_index("ix_council_reviews_entry_status")
        batch_op.drop_index("ix_council_reviews_status")
        batch_op.drop_index("ix_council_reviews_entry_id")

    op.drop_table("council_reviews")
