"""multilingual_event_architecture_phase_a

Revision ID: e8a1b2c3d4e5
Revises: c9d2e5f3a1b0
Create Date: 2026-11-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = "e8a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create documents, document_views, entities, entity_aliases, mentions, parity_snapshots."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. documents table
    if "documents" not in existing_tables:
        op.create_table(
            "documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=False),
            sa.Column("entry_id", sa.String(length=36), nullable=True),
            sa.Column("original_text", sa.Text(), nullable=False),
            sa.Column("lang", sa.String(length=12), nullable=False),
            sa.Column("lang_confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.Column("script", sa.String(length=8), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("raw_blob_ref", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["sources.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["entry_id"],
                ["entries.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("documents", schema=None) as batch_op:
            batch_op.create_index("ix_documents_source_id", ["source_id"], unique=False)
            batch_op.create_index("ix_documents_entry_id", ["entry_id"], unique=False)
            batch_op.create_index("ix_documents_lang", ["lang"], unique=False)
            batch_op.create_index("ix_documents_published_at", ["published_at"], unique=False)
            batch_op.create_index("ix_documents_content_hash", ["content_hash"], unique=False)
            batch_op.create_index("ix_documents_lang_published", ["lang", "published_at"], unique=False)

    # 2. document_views table
    if "document_views" not in existing_tables:
        op.create_table(
            "document_views",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("doc_id", sa.String(length=36), nullable=False),
            sa.Column("view_type", sa.String(length=20), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("producer", sa.String(length=64), nullable=False),
            sa.Column("quality_score", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["doc_id"],
                ["documents.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("document_views", schema=None) as batch_op:
            batch_op.create_index("ix_document_views_doc_id", ["doc_id"], unique=False)
            batch_op.create_index("ix_document_views_view_type", ["view_type"], unique=False)
            batch_op.create_index("ix_document_views_doc_view", ["doc_id", "view_type"], unique=False)

    # 3. entities table
    if "entities" not in existing_tables:
        op.create_table(
            "entities",
            sa.Column("canonical_id", sa.String(length=64), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("canonical_name", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("canonical_id"),
        )
        with op.batch_alter_table("entities", schema=None) as batch_op:
            batch_op.create_index("ix_entities_type", ["type"], unique=False)
            batch_op.create_index("ix_entities_canonical_name", ["canonical_name"], unique=False)

    # 4. entity_aliases table
    if "entity_aliases" not in existing_tables:
        op.create_table(
            "entity_aliases",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("alias", sa.String(length=128), nullable=False),
            sa.Column("lang", sa.String(length=12), nullable=True),
            sa.Column("script", sa.String(length=8), nullable=True),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.Column("valid_from", sa.DateTime(), nullable=True),
            sa.Column("valid_to", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["entity_id"],
                ["entities.canonical_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("entity_aliases", schema=None) as batch_op:
            batch_op.create_index("ix_entity_aliases_entity_id", ["entity_id"], unique=False)
            batch_op.create_index("ix_entity_aliases_alias", ["alias"], unique=False)
            batch_op.create_index("ix_entity_aliases_alias_lang", ["alias", "lang"], unique=False)

    # 5. mentions table
    if "mentions" not in existing_tables:
        op.create_table(
            "mentions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("doc_id", sa.String(length=36), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("span_start", sa.Integer(), nullable=False),
            sa.Column("span_end", sa.Integer(), nullable=False),
            sa.Column("linker_version", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.ForeignKeyConstraint(
                ["doc_id"],
                ["documents.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["entity_id"],
                ["entities.canonical_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("mentions", schema=None) as batch_op:
            batch_op.create_index("ix_mentions_doc_id", ["doc_id"], unique=False)
            batch_op.create_index("ix_mentions_entity_id", ["entity_id"], unique=False)

    # 6. parity_snapshots table
    if "parity_snapshots" not in existing_tables:
        op.create_table(
            "parity_snapshots",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("zh_count_7d", sa.Integer(), nullable=False),
            sa.Column("en_count_7d", sa.Integer(), nullable=False),
            sa.Column("capture_rate_ratio", sa.Float(), nullable=False),
            sa.Column("zh_median_latency_h", sa.Float(), nullable=False),
            sa.Column("en_median_latency_h", sa.Float(), nullable=False),
            sa.Column("latency_ratio", sa.Float(), nullable=False),
            sa.Column("details", sqlite.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("parity_snapshots", schema=None) as batch_op:
            batch_op.create_index("ix_parity_snapshots_timestamp", ["timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema - drop Phase A tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "parity_snapshots" in existing_tables:
        with op.batch_alter_table("parity_snapshots", schema=None) as batch_op:
            batch_op.drop_index("ix_parity_snapshots_timestamp")
        op.drop_table("parity_snapshots")

    if "mentions" in existing_tables:
        with op.batch_alter_table("mentions", schema=None) as batch_op:
            batch_op.drop_index("ix_mentions_entity_id")
            batch_op.drop_index("ix_mentions_doc_id")
        op.drop_table("mentions")

    if "entity_aliases" in existing_tables:
        with op.batch_alter_table("entity_aliases", schema=None) as batch_op:
            batch_op.drop_index("ix_entity_aliases_alias_lang")
            batch_op.drop_index("ix_entity_aliases_alias")
            batch_op.drop_index("ix_entity_aliases_entity_id")
        op.drop_table("entity_aliases")

    if "entities" in existing_tables:
        with op.batch_alter_table("entities", schema=None) as batch_op:
            batch_op.drop_index("ix_entities_canonical_name")
            batch_op.drop_index("ix_entities_type")
        op.drop_table("entities")

    if "document_views" in existing_tables:
        with op.batch_alter_table("document_views", schema=None) as batch_op:
            batch_op.drop_index("ix_document_views_doc_view")
            batch_op.drop_index("ix_document_views_view_type")
            batch_op.drop_index("ix_document_views_doc_id")
        op.drop_table("document_views")

    if "documents" in existing_tables:
        with op.batch_alter_table("documents", schema=None) as batch_op:
            batch_op.drop_index("ix_documents_lang_published")
            batch_op.drop_index("ix_documents_content_hash")
            batch_op.drop_index("ix_documents_published_at")
            batch_op.drop_index("ix_documents_lang")
            batch_op.drop_index("ix_documents_entry_id")
            batch_op.drop_index("ix_documents_source_id")
        op.drop_table("documents")
