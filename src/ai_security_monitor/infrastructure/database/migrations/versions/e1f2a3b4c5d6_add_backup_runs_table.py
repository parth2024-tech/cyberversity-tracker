"""add_backup_runs_table

Revision ID: e1f2a3b4c5d6
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create backup_runs table."""
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("compressed_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("encrypted_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sha256_raw", sa.String(length=64), nullable=True),
        sa.Column("sha256_encrypted", sa.String(length=64), nullable=True),
        sa.Column("integrity_check_passed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("uploaded_to_remote", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("remote_key", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("backup_runs", schema=None) as batch_op:
        batch_op.create_index("ix_backup_runs_status", ["status"], unique=False)
        batch_op.create_index("ix_backup_runs_created_at", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema - drop backup_runs table."""
    with op.batch_alter_table("backup_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_backup_runs_created_at")
        batch_op.drop_index("ix_backup_runs_status")

    op.drop_table("backup_runs")
