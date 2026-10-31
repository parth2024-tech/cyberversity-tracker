"""add_decision_brief_to_entry_analysis

Revision ID: e7b9a1c3d5f0
Revises: make_source_url_nullable
Create Date: 2026-10-31 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b9a1c3d5f0"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - add decision_brief to entry_analysis."""
    with op.batch_alter_table("entry_analysis", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decision_brief", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove decision_brief from entry_analysis."""
    with op.batch_alter_table("entry_analysis", schema=None) as batch_op:
        batch_op.drop_column("decision_brief")
