"""initial_schema

Revision ID: 626b47a8f364
Revises:
Create Date: 2026-08-27 00:55:00.352279

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "626b47a8f364"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - idempotent base schema creation / legacy cleanup."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    if "sources" not in existing_tables:
        # Fresh database: create base tables directly
        op.create_table(
            "sources",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False, unique=True),
            sa.Column("type", sa.String(length=50), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("1")),
            sa.Column(
                "rate_limit_seconds", sa.Integer(), server_default=sa.text("3600")
            ),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),
            sa.Column("last_entries_new", sa.Integer(), server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sources_category", "sources", ["category"], unique=False)
        op.create_index("ix_sources_enabled", "sources", ["enabled"], unique=False)
        op.create_index("ix_sources_name", "sources", ["name"], unique=True)
        op.create_index(
            "ix_sources_category_enabled", "sources", ["category", "enabled"], unique=False
        )

        op.create_table(
            "entries",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "source_id",
                sa.String(length=36),
                sa.ForeignKey("sources.id"),
                nullable=False,
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), unique=True, nullable=False),
            sa.Column("summary", sa.Text(), server_default=sa.text("''")),
            sa.Column("published_at", sa.DateTime(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("raw_data", sa.JSON(), nullable=True),
            sa.Column("is_purged", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("purged_at", sa.DateTime(), nullable=True),
            sa.Column("is_user_saved", sa.Boolean(), server_default=sa.text("0")),
        )
        op.create_index("ix_entries_source_id", "entries", ["source_id"], unique=False)
        op.create_index(
            "ix_entries_content_hash", "entries", ["content_hash"], unique=True
        )
        op.create_index(
            "ix_entries_published_at", "entries", ["published_at"], unique=False
        )
        op.create_index(
            "ix_entries_fetched_at", "entries", ["fetched_at"], unique=False
        )
        op.create_index("ix_entries_category", "entries", ["category"], unique=False)

        op.create_table(
            "fetch_log",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "source_id",
                sa.String(length=36),
                sa.ForeignKey("sources.id"),
                nullable=False,
            ),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("entries_found", sa.Integer(), server_default=sa.text("0")),
            sa.Column("entries_new", sa.Integer(), server_default=sa.text("0")),
            sa.Column("duration_seconds", sa.Float(), server_default=sa.text("0.0")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_fetch_log_source_id", "fetch_log", ["source_id"], unique=False
        )
        op.create_index(
            "ix_fetch_log_fetched_at", "fetch_log", ["fetched_at"], unique=False
        )

        op.create_table(
            "entry_analysis",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "entry_id",
                sa.String(length=36),
                sa.ForeignKey("entries.id"),
                nullable=False,
            ),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("threat_velocity", sa.Float(), server_default=sa.text("0.5")),
            sa.Column("confidence", sa.Float(), server_default=sa.text("0.7")),
            sa.Column("cvss_score", sa.Float(), nullable=True),
            sa.Column("affects_stack", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("affected_components", sa.JSON(), nullable=True),
            sa.Column("attack_vector", sa.String(length=100), nullable=True),
            sa.Column("key_takeaways", sa.JSON(), nullable=True),
            sa.Column("recommendations", sa.JSON(), nullable=True),
            sa.Column("analyzed_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_entry_analysis_entry_id", "entry_analysis", ["entry_id"], unique=False
        )

        op.create_table(
            "llm_receipts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("logical_key", sa.String(length=64), unique=True, nullable=True),
            sa.Column("entry_id", sa.String(length=36), nullable=True),
            sa.Column("provider", sa.String(length=50), server_default="ollama"),
            sa.Column("model", sa.String(length=100), server_default="qwen2.5:7b"),
            sa.Column("prompt_version", sa.String(length=20), server_default="v1"),
            sa.Column("status", sa.String(length=20), server_default="pending"),
            sa.Column("attempts", sa.Integer(), server_default=sa.text("1")),
            sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3")),
            sa.Column("response_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=100), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), server_default=sa.text("0")),
            sa.Column("completion_tokens", sa.Integer(), server_default=sa.text("0")),
            sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0")),
            sa.Column("estimated_cost_usd", sa.Float(), server_default=sa.text("0.0")),
            sa.Column("call_purpose", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("execution_tier", sa.String(length=30), nullable=True),
            sa.Column(
                "cache_read_input_tokens", sa.Integer(), server_default=sa.text("0")
            ),
            sa.Column(
                "cache_creation_input_tokens", sa.Integer(), server_default=sa.text("0")
            ),
        )
    else:
        # Existing database: safely remove legacy prototype tables and indexes if present
        if "digest_history" in existing_tables:
            op.drop_table("digest_history")
        if "analysis_evidence" in existing_tables:
            evidence_indexes = {
                idx["name"] for idx in insp.get_indexes("analysis_evidence")
            }
            for idx_name in (
                "idx_analysis_evidence_analysis",
                "idx_analysis_evidence_target",
                "idx_analysis_evidence_type",
            ):
                if idx_name in evidence_indexes:
                    op.drop_index(idx_name, table_name="analysis_evidence")
            op.drop_table("analysis_evidence")
        if "analysis_outcome" in existing_tables:
            outcome_indexes = {
                idx["name"] for idx in insp.get_indexes("analysis_outcome")
            }
            if "idx_analysis_outcome_analysis" in outcome_indexes:
                op.drop_index(
                    "idx_analysis_outcome_analysis", table_name="analysis_outcome"
                )
            op.drop_table("analysis_outcome")

        if "entries" in existing_tables:
            entries_indexes = {idx["name"] for idx in insp.get_indexes("entries")}
            for idx_name in (
                "idx_entries_category",
                "idx_entries_fetched",
                "idx_entries_hash",
                "idx_entries_published",
                "idx_entries_source",
            ):
                if idx_name in entries_indexes:
                    op.drop_index(idx_name, table_name="entries")

        if "entry_analysis" in existing_tables:
            ea_indexes = {idx["name"] for idx in insp.get_indexes("entry_analysis")}
            for idx_name in ("idx_entry_analysis_entry", "idx_entry_analysis_velocity"):
                if idx_name in ea_indexes:
                    op.drop_index(idx_name, table_name="entry_analysis")
            ea_cols = {col["name"] for col in insp.get_columns("entry_analysis")}
            if "evidence_version" in ea_cols:
                op.drop_column("entry_analysis", "evidence_version")
            if "overall_confidence" in ea_cols:
                op.drop_column("entry_analysis", "overall_confidence")

        if "fetch_log" in existing_tables:
            fetch_indexes = {idx["name"] for idx in insp.get_indexes("fetch_log")}
            for idx_name in ("idx_fetch_log_source", "idx_fetch_log_time"):
                if idx_name in fetch_indexes:
                    op.drop_index(idx_name, table_name="fetch_log")
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(
        op.f("idx_fetch_log_time"), "fetch_log", ["fetched_at"], unique=False
    )
    op.create_index(
        op.f("idx_fetch_log_source"), "fetch_log", ["source_id"], unique=False
    )
    op.add_column(
        "entry_analysis",
        sa.Column(
            "overall_confidence",
            sa.REAL(),
            server_default=sa.text("(0.7)"),
            nullable=True,
        ),
    )
    op.add_column(
        "entry_analysis",
        sa.Column(
            "evidence_version", sa.TEXT(), server_default=sa.text("'v1'"), nullable=True
        ),
    )
    op.create_index(
        op.f("idx_entry_analysis_velocity"),
        "entry_analysis",
        ["threat_velocity"],
        unique=False,
    )
    op.create_index(
        op.f("idx_entry_analysis_entry"), "entry_analysis", ["entry_id"], unique=False
    )
    op.create_index(op.f("idx_entries_source"), "entries", ["source_id"], unique=False)
    op.create_index(
        op.f("idx_entries_published"), "entries", ["published_at"], unique=False
    )
    op.create_index(op.f("idx_entries_hash"), "entries", ["content_hash"], unique=False)
    op.create_index(
        op.f("idx_entries_fetched"), "entries", ["fetched_at"], unique=False
    )
    op.create_index(op.f("idx_entries_category"), "entries", ["category"], unique=False)
    op.create_table(
        "analysis_outcome",
        sa.Column("id", sa.INTEGER(), nullable=True),
        sa.Column("analysis_id", sa.TEXT(), nullable=False),
        sa.Column("outcome_type", sa.TEXT(), nullable=False),
        sa.Column("outcome_value", sa.TEXT(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "outcome_type IN ('telegram_sent','user_dismissed','user_escalated','false_positive','confirmed')"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["entry_analysis.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("idx_analysis_outcome_analysis"),
        "analysis_outcome",
        ["analysis_id"],
        unique=False,
    )
    op.create_table(
        "analysis_evidence",
        sa.Column("id", sa.INTEGER(), nullable=True),
        sa.Column("analysis_id", sa.TEXT(), nullable=False),
        sa.Column("claim_type", sa.TEXT(), nullable=False),
        sa.Column("claim_target", sa.TEXT(), nullable=False),
        sa.Column("claim_value", sa.TEXT(), nullable=False),
        sa.Column("confidence", sa.REAL(), nullable=False),
        sa.Column("evidence_json", sa.TEXT(), nullable=True),
        sa.Column("method", sa.TEXT(), nullable=False),
        sa.Column("model_version", sa.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "claim_type IN ('fact','inference','hypothesis','assumption','unknown')"
        ),
        sa.CheckConstraint("method IN ('heuristic','llm','hybrid')"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0"),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["entry_analysis.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("idx_analysis_evidence_type"),
        "analysis_evidence",
        ["claim_type"],
        unique=False,
    )
    op.create_index(
        op.f("idx_analysis_evidence_target"),
        "analysis_evidence",
        ["claim_target"],
        unique=False,
    )
    op.create_index(
        op.f("idx_analysis_evidence_analysis"),
        "analysis_evidence",
        ["analysis_id"],
        unique=False,
    )
    op.create_table(
        "digest_history",
        sa.Column("id", sa.INTEGER(), nullable=True),
        sa.Column("period_start", sa.TIMESTAMP(), nullable=False),
        sa.Column("period_end", sa.TIMESTAMP(), nullable=False),
        sa.Column(
            "entry_count", sa.INTEGER(), server_default=sa.text("0"), nullable=True
        ),
        sa.Column("delivery_method", sa.TEXT(), nullable=True),
        sa.Column("delivery_status", sa.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###
