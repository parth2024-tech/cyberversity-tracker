"""add_source_quarantine_columns

Revision ID: b8c1d4e2f5a0
Revises: e7b9a1c3d5f0
Create Date: 2026-10-31 23:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c1d4e2f5a0"
down_revision: str | Sequence[str] | None = "e7b9a1c3d5f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - add quarantine columns to sources table."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_columns = {c["name"] for c in insp.get_columns("sources")}

    cols_to_add = [
        col
        for col in [
            "is_quarantined",
            "consecutive_failures",
            "quarantined_at",
            "quarantine_reason",
        ]
        if col not in existing_columns
    ]

    if not cols_to_add:
        return

    with op.batch_alter_table("sources", schema=None) as batch_op:
        if "is_quarantined" in cols_to_add:
            batch_op.add_column(
                sa.Column(
                    "is_quarantined",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "consecutive_failures" in cols_to_add:
            batch_op.add_column(
                sa.Column(
                    "consecutive_failures",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "quarantined_at" in cols_to_add:
            batch_op.add_column(
                sa.Column("quarantined_at", sa.DateTime(), nullable=True)
            )
        if "quarantine_reason" in cols_to_add:
            batch_op.add_column(
                sa.Column("quarantine_reason", sa.Text(), nullable=True)
            )


def downgrade() -> None:
    """Downgrade schema - remove quarantine columns from sources table."""
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_column("quarantine_reason")
        batch_op.drop_column("quarantined_at")
        batch_op.drop_column("consecutive_failures")
        batch_op.drop_column("is_quarantined")
