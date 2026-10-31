"""add_entry_entities_table

Revision ID: c9d2e5f3a1b0
Revises: b8c1d4e2f5a0
Create Date: 2026-11-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d2e5f3a1b0"
down_revision: str | Sequence[str] | None = "b8c1d4e2f5a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create entry_entities knowledge graph table."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "entry_entities" in insp.get_table_names():
        return

    op.create_table(
        "entry_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("metric_value", sa.String(length=64), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("entry_entities", schema=None) as batch_op:
        batch_op.create_index("ix_entry_entities_entry_id", ["entry_id"], unique=False)
        batch_op.create_index("ix_entry_entities_entity_type", ["entity_type"], unique=False)
        batch_op.create_index("ix_entry_entities_name", ["name"], unique=False)
        batch_op.create_index("ix_entry_entities_created_at", ["created_at"], unique=False)
        batch_op.create_index(
            "ix_entry_entities_type_name", ["entity_type", "name"], unique=False
        )
        batch_op.create_index(
            "ix_entry_entities_created_type", ["created_at", "entity_type"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema - drop entry_entities table."""
    with op.batch_alter_table("entry_entities", schema=None) as batch_op:
        batch_op.drop_index("ix_entry_entities_created_type")
        batch_op.drop_index("ix_entry_entities_type_name")
        batch_op.drop_index("ix_entry_entities_created_at")
        batch_op.drop_index("ix_entry_entities_name")
        batch_op.drop_index("ix_entry_entities_entity_type")
        batch_op.drop_index("ix_entry_entities_entry_id")

    op.drop_table("entry_entities")
