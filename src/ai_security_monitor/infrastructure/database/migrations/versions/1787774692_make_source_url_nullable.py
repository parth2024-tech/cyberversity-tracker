"""make_source_url_nullable

Revision ID: make_source_url_nullable
Revises: da4ca2059230
Create Date: 2026-08-27 01:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'make_source_url_nullable'
down_revision: str | Sequence[str] | None = 'da4ca2059230'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - make sources.url nullable."""
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.alter_column('url',
               existing_type=sa.Text(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema - make sources.url NOT NULL."""
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.alter_column('url',
               existing_type=sa.Text(),
               nullable=False,
               server_default=sa.text("''"))
