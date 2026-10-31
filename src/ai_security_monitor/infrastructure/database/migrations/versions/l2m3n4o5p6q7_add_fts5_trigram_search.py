"""Add FTS5 trigram search index with Chinese and translated text support (Feature 13).

Revision ID: l2m3n4o5p6q7
Revises: make_source_url_nullable
Create Date: 2026-10-31 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create or upgrade entries_fts virtual table with trigram tokenizer and triggers."""
    conn = op.get_bind()

    # Drop existing triggers and table if they exist
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_ai;"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_au;"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_ad;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS entries_fts;"))

    # Create FTS5 virtual table with trigram tokenizer
    conn.execute(
        sa.text(
            "CREATE VIRTUAL TABLE entries_fts USING fts5("
            "title, summary, category, translated_text, entry_id UNINDEXED, tokenize='trigram'"
            ");"
        )
    )

    # Maintain FTS5 index automatically on insert, update, delete
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN "
            "INSERT INTO entries_fts(entry_id, title, summary, category, translated_text) "
            "VALUES ("
            "new.id, new.title, new.summary, new.category, "
            "coalesce(json_extract(new.metadata_json, '$.translated_text'), '')"
            "); "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN "
            "DELETE FROM entries_fts WHERE entry_id = old.id; "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN "
            "DELETE FROM entries_fts WHERE entry_id = old.id; "
            "INSERT INTO entries_fts(entry_id, title, summary, category, translated_text) "
            "VALUES ("
            "new.id, new.title, new.summary, new.category, "
            "coalesce(json_extract(new.metadata_json, '$.translated_text'), '')"
            "); "
            "END;"
        )
    )

    # Backfill all existing non-purged entries
    conn.execute(
        sa.text(
            "INSERT INTO entries_fts(entry_id, title, summary, category, translated_text) "
            "SELECT id, title, summary, category, "
            "coalesce(json_extract(metadata_json, '$.translated_text'), '') "
            "FROM entries WHERE is_purged = 0;"
        )
    )


def downgrade() -> None:
    """Downgrade back to standard entries_fts table."""
    conn = op.get_bind()
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_ai;"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_au;"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS entries_ad;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS entries_fts;"))

    conn.execute(
        sa.text(
            "CREATE VIRTUAL TABLE entries_fts USING fts5("
            "title, summary, category, entry_id UNINDEXED"
            ");"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN "
            "INSERT INTO entries_fts(entry_id, title, summary, category) "
            "VALUES (new.id, new.title, new.summary, new.category); "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN "
            "DELETE FROM entries_fts WHERE entry_id = old.id; "
            "END;"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN "
            "DELETE FROM entries_fts WHERE entry_id = old.id; "
            "INSERT INTO entries_fts(entry_id, title, summary, category) "
            "VALUES (new.id, new.title, new.summary, new.category); "
            "END;"
        )
    )
