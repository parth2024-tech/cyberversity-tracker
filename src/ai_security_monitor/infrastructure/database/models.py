"""
SQLAlchemy ORM models.
Maps to database tables for persistent storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


def generate_uuid() -> str:
    """Generate UUID string for primary keys."""
    return str(uuid4())


class SourceModel(Base):
    """Source configuration model."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_entries_new: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships (lazy="select" prevents massive eager loads of thousands of entries when querying sources)
    entries: Mapped[list[EntryModel]] = relationship(
        back_populates="source", lazy="select"
    )
    fetch_logs: Mapped[list[FetchLogModel]] = relationship(
        back_populates="source", lazy="select"
    )

    __table_args__ = (Index("ix_sources_category_enabled", "category", "enabled"),)

    @property
    def tier(self) -> float:
        """Source credibility tier (1.0 = Labs/ArXiv, 1.5 = Repos/Tools, 2.0 = Aggregators/Default)."""
        return float((self.config or {}).get("tier", 2.0))


class EntryModel(Base):
    """Intelligence entry model."""

    __tablename__ = "entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra_metadata: Mapped[dict] = mapped_column("metadata_json", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    is_purged: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", index=True
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_user_saved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", index=True
    )

    # Relationships
    source: Mapped[SourceModel] = relationship(
        back_populates="entries", lazy="selectin"
    )
    analysis: Mapped[AnalysisModel | None] = relationship(
        back_populates="entry", uselist=False, lazy="selectin"
    )
    entities: Mapped[list[EntryEntityModel]] = relationship(
        "EntryEntityModel",
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_entries_category_published", "category", "published_at"),
        Index("ix_entries_source_published", "source_id", "published_at"),
    )


class AnalysisModel(Base):
    """AI analysis model."""

    __tablename__ = "entry_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entries.id"), unique=True, nullable=False, index=True
    )
    attack_vector: Mapped[str] = mapped_column(Text, nullable=False)
    risk_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False)
    threat_velocity: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-100
    severity_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-100
    blast_radius_score: Mapped[int] = mapped_column(Integer, default=0)  # 1-100
    affected_ecosystem: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_pre_cve_warning: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attack_archetype: Mapped[str] = mapped_column(String(100), default="")
    weaponization_potential: Mapped[str] = mapped_column(
        String(50), default="Theoretical"
    )
    mitre_attack_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, index=True
    )
    mitre_technique: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )
    model: Mapped[str] = mapped_column(String(50), default="heuristic")
    confidence: Mapped[float] = mapped_column(default=1.0)
    overall_confidence: Mapped[float] = mapped_column(default=0.7)
    evidence_version: Mapped[str] = mapped_column(String(20), default="v1")
    decision_brief: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    entry: Mapped[EntryModel] = relationship(back_populates="analysis", lazy="selectin")

    __table_args__ = (
        Index("ix_analysis_threat_velocity", "threat_velocity"),
        Index("ix_analysis_pre_cve", "is_pre_cve_warning"),
        Index("ix_analysis_severity", "severity_index"),
        # Composite indexes for the three sort-JOIN queries in entries router
        # These turn full table scans into index lookups on the 6,800+ row table
        Index("ix_analysis_entry_velocity", "entry_id", "threat_velocity"),
        Index("ix_analysis_entry_blast", "entry_id", "blast_radius_score"),
        Index("ix_analysis_entry_severity", "entry_id", "severity_index"),
    )


class FetchLogModel(Base):
    """Fetch operation log model."""

    __tablename__ = "fetch_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    entries_new: Mapped[int] = mapped_column(Integer, default=0)
    entries_total: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )

    # Relationships
    source: Mapped[SourceModel] = relationship(back_populates="fetch_logs")

    __table_args__ = (
        Index("ix_fetch_log_source_fetched", "source_id", "fetched_at"),
        Index("ix_fetch_log_status", "status"),
    )


class DigestModel(Base):
    """Generated digest model."""

    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    schedule: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # daily, weekly
    entries_by_category: Mapped[dict] = mapped_column(JSON, default=dict)
    total_entries: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )

    __table_args__ = (Index("ix_digests_schedule_created", "schedule", "created_at"),)


class WatchlistRuleModel(Base):
    """User-defined framework watchlist and threat alert rule model."""

    __tablename__ = "watchlist_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_threat_velocity: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


class AnalysisEvidenceModel(Base):
    """Epistemic evidence tracking for analysis claims."""

    __tablename__ = "analysis_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entry_analysis.id"), nullable=False, index=True
    )
    claim_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # fact, inference, hypothesis, assumption, unknown
    claim_target: Mapped[str] = mapped_column(Text, nullable=False)
    claim_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.0)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # heuristic, llm, hybrid
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


class AnalysisOutcomeModel(Base):
    """Ground truth outcomes for calibration."""

    __tablename__ = "analysis_outcome"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entry_analysis.id"), nullable=False, index=True
    )
    outcome_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # telegram_sent, user_dismissed, user_escalated, false_positive, confirmed
    outcome_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


class ReceiptModel(Base):
    """Execution receipt model for LLM inference idempotency and retry caps."""

    __tablename__ = "llm_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    logical_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_tier: Mapped[str | None] = mapped_column(
        String(30), nullable=True, index=True
    )
    cache_read_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    cache_creation_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class EntryEntityModel(Base):
    """Relational knowledge graph entity links extracted from intelligence entries."""

    __tablename__ = "entry_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entry_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    entry: Mapped[EntryModel] = relationship("EntryModel", back_populates="entities")

    __table_args__ = (
        Index("ix_entry_entities_type_name", "entity_type", "name"),
        Index("ix_entry_entities_created_type", "created_at", "entity_type"),
    )


class ResearchRunModel(Base):
    """Audit and replay log for autonomous deep research loop executions."""

    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    query: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    sources_count: Mapped[int] = mapped_column(Integer, default=0)
    execution_steps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    coverage_score: Mapped[float] = mapped_column(Float, default=1.0)
    output_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )


class CouncilReviewModel(Base):
    """Multi-Agent Council evaluation stored in shadow mode for calibration review (Workstream A2)."""

    __tablename__ = "council_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entry_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="shadow", nullable=False, index=True
    )  # "shadow", "pending_review", "approved", "rejected", "calibrated"
    consensus_verdict: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    consensus_summary: Mapped[str] = mapped_column(Text, nullable=False)
    persona_evaluations: Mapped[dict] = mapped_column(JSON, nullable=False)
    verified_claims: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    receipt_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_council_reviews_entry_status", "entry_id", "status"),
        Index("ix_council_reviews_created_verdict", "created_at", "consensus_verdict"),
    )


class EntityDailyCountModel(Base):
    """Pre-aggregated daily mention counts for AI knowledge graph entities (Workstream B1)."""

    __tablename__ = "entity_daily_counts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entity_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index(
            "uq_entity_daily_counts_key_date",
            "entity_name",
            "entity_type",
            "bucket_date",
            unique=True,
        ),
        Index("ix_entity_daily_counts_date_type", "bucket_date", "entity_type"),
    )


class BackupRunModel(Base):
    """Execution log for encrypted offsite database backups and restore drills."""

    __tablename__ = "backup_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress", nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    compressed_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    encrypted_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sha256_encrypted: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_check_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_to_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )


class DocumentModel(Base):
    """Immutable native-language source document."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    lang_confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    script: Mapped[str | None] = mapped_column(String(8), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_blob_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    views: Mapped[list[DocumentViewModel]] = relationship(
        "DocumentViewModel",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    mentions: Mapped[list[MentionModel]] = relationship(
        "MentionModel",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    event_documents: Mapped[list[EventDocumentModel]] = relationship(
        "EventDocumentModel",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    claims: Mapped[list[ClaimModel]] = relationship(
        "ClaimModel",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_documents_lang_published", "lang", "published_at"),)


class DocumentViewModel(Base):
    """Derived versioned view of a document."""

    __tablename__ = "document_views"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    doc_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    view_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    producer: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    document: Mapped[DocumentModel] = relationship(
        "DocumentModel", back_populates="views"
    )

    __table_args__ = (Index("ix_document_views_doc_view", "doc_id", "view_type"),)


class CanonicalEntityModel(Base):
    """Language-independent canonical entity."""

    __tablename__ = "entities"

    canonical_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    aliases: Mapped[list[EntityAliasModel]] = relationship(
        "EntityAliasModel",
        back_populates="entity",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    mentions: Mapped[list[MentionModel]] = relationship(
        "MentionModel",
        back_populates="entity",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EntityAliasModel(Base):
    """Alias for a canonical entity across languages and scripts."""

    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entity_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("entities.canonical_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    lang: Mapped[str | None] = mapped_column(String(12), nullable=True)
    script: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entity: Mapped[CanonicalEntityModel] = relationship(
        "CanonicalEntityModel", back_populates="aliases"
    )

    __table_args__ = (Index("ix_entity_aliases_alias_lang", "alias", "lang"),)


class MentionModel(Base):
    """Span mention linking a document to a canonical entity."""

    __tablename__ = "mentions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    doc_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("entities.canonical_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    linker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    document: Mapped[DocumentModel] = relationship(
        "DocumentModel", back_populates="mentions"
    )
    entity: Mapped[CanonicalEntityModel] = relationship(
        "CanonicalEntityModel", back_populates="mentions"
    )


class ParitySnapshotModel(Base):
    """Language-parity SLO telemetry snapshot."""

    __tablename__ = "parity_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    zh_count_7d: Mapped[int] = mapped_column(Integer, nullable=False)
    en_count_7d: Mapped[int] = mapped_column(Integer, nullable=False)
    capture_rate_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    zh_median_latency_h: Mapped[float] = mapped_column(Float, nullable=False)
    en_median_latency_h: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class EventModel(Base):
    """Canonical cross-lingual intelligence event."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    canonical_entity_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    version_tag: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    first_seen_lang: Mapped[str] = mapped_column(
        String(12), default="en", nullable=False
    )
    first_source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    documents: Mapped[list[EventDocumentModel]] = relationship(
        "EventDocumentModel",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    claims: Mapped[list[ClaimModel]] = relationship(
        "ClaimModel",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_events_type_first_seen", "type", "first_seen_at"),)


class EventDocumentModel(Base):
    """Associates a document with an event under a specific evidentiary role."""

    __tablename__ = "event_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), default="corroborating", nullable=False, index=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    event: Mapped[EventModel] = relationship("EventModel", back_populates="documents")
    document: Mapped[DocumentModel] = relationship(
        "DocumentModel", back_populates="event_documents"
    )

    __table_args__ = (
        UniqueConstraint("event_id", "doc_id", name="uq_event_documents_event_doc"),
        Index("ix_event_documents_doc_role", "doc_id", "role"),
    )


class ClaimModel(Base):
    """Structured claim extracted from original native document with evidence span."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    normalized_value: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    event: Mapped[EventModel] = relationship("EventModel", back_populates="claims")
    document: Mapped[DocumentModel] = relationship(
        "DocumentModel", back_populates="claims"
    )

    __table_args__ = (Index("ix_claims_event_field", "event_id", "field"),)
