"""multilingual_event_architecture_phase_c

Revision ID: f1a2b3c4d5e6
Revises: e8a1b2c3d4e5
Create Date: 2026-11-01 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create events, event_documents, claims tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. events table
    if "events" not in existing_tables:
        op.create_table(
            "events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column(
                "canonical_entity_ids",
                sqlite.JSON().with_variant(sa.JSON(), "sqlite"),
                nullable=False,
            ),
            sa.Column("version_tag", sa.String(length=64), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("first_seen_lang", sa.String(length=12), nullable=False, server_default="en"),
            sa.Column("first_source_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["first_source_id"],
                ["sources.id"],
                name="fk_events_first_source_id",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_events"),
        )
        op.create_index("ix_events_type", "events", ["type"], unique=False)
        op.create_index("ix_events_title", "events", ["title"], unique=False)
        op.create_index("ix_events_version_tag", "events", ["version_tag"], unique=False)
        op.create_index("ix_events_first_seen_at", "events", ["first_seen_at"], unique=False)
        op.create_index("ix_events_first_source_id", "events", ["first_source_id"], unique=False)
        op.create_index("ix_events_status", "events", ["status"], unique=False)
        op.create_index(
            "ix_events_type_first_seen",
            "events",
            ["type", "first_seen_at"],
            unique=False,
        )

    # 2. event_documents table
    if "event_documents" not in existing_tables:
        op.create_table(
            "event_documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("doc_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="corroborating"),
            sa.Column("linked_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["event_id"],
                ["events.id"],
                name="fk_event_documents_event_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["doc_id"],
                ["documents.id"],
                name="fk_event_documents_doc_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_event_documents"),
            sa.UniqueConstraint("event_id", "doc_id", name="uq_event_documents_event_doc"),
        )
        op.create_index("ix_event_documents_event_id", "event_documents", ["event_id"], unique=False)
        op.create_index("ix_event_documents_doc_id", "event_documents", ["doc_id"], unique=False)
        op.create_index("ix_event_documents_role", "event_documents", ["role"], unique=False)
        op.create_index("ix_event_documents_doc_role", "event_documents", ["doc_id", "role"], unique=False)

    # 3. claims table
    if "claims" not in existing_tables:
        op.create_table(
            "claims",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("doc_id", sa.String(length=36), nullable=False),
            sa.Column("field", sa.String(length=32), nullable=False),
            sa.Column("normalized_value", sa.String(length=128), nullable=False),
            sa.Column("unit", sa.String(length=32), nullable=True),
            sa.Column("evidence_span_start", sa.Integer(), nullable=True),
            sa.Column("evidence_span_end", sa.Integer(), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["event_id"],
                ["events.id"],
                name="fk_claims_event_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["doc_id"],
                ["documents.id"],
                name="fk_claims_doc_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_claims"),
        )
        op.create_index("ix_claims_event_id", "claims", ["event_id"], unique=False)
        op.create_index("ix_claims_doc_id", "claims", ["doc_id"], unique=False)
        op.create_index("ix_claims_field", "claims", ["field"], unique=False)
        op.create_index("ix_claims_event_field", "claims", ["event_id", "field"], unique=False)


def downgrade() -> None:
    """Downgrade schema - drop claims, event_documents, events tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "claims" in existing_tables:
        op.drop_table("claims")
    if "event_documents" in existing_tables:
        op.drop_table("event_documents")
    if "events" in existing_tables:
        op.drop_table("events")
