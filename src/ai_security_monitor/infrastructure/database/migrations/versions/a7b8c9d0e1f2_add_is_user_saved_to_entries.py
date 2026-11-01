"""add_is_user_saved_to_entries

Revision ID: a7b8c9d0e1f2
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - add is_user_saved column and index to entries table."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("entries")]

    if "is_user_saved" not in cols:
        with op.batch_alter_table("entries", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_user_saved",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
            batch_op.create_index(
                "ix_entries_is_user_saved", ["is_user_saved"], unique=False
            )


def downgrade() -> None:
    """Downgrade schema - remove is_user_saved column from entries table."""
    with op.batch_alter_table("entries", schema=None) as batch_op:
        batch_op.drop_index("ix_entries_is_user_saved")
        batch_op.drop_column("is_user_saved")
