"""
SQLAlchemy ORM models.
Maps to database tables for persistent storage.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import (
    String, Text, Integer, DateTime, Boolean, ForeignKey, Index, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON


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
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, default="")
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rate_limit_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_entries_new: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(SQLiteJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    entries: Mapped[list["EntryModel"]] = relationship(back_populates="source", lazy="dynamic")
    fetch_logs: Mapped[list["FetchLogModel"]] = relationship(back_populates="source", lazy="dynamic")

    __table_args__ = (
        Index("ix_sources_category_enabled", "category", "enabled"),
    )


class EntryModel(Base):
    """Intelligence entry model."""
    __tablename__ = "entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(SQLiteJSON, default=list)
    metadata: Mapped[dict] = mapped_column(SQLiteJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    source: Mapped["SourceModel"] = relationship(back_populates="entries")
    analysis: Mapped[Optional["AnalysisModel"]] = relationship(back_populates="entry", uselist=False)

    __table_args__ = (
        Index("ix_entries_category_published", "category", "published_at"),
        Index("ix_entries_source_published", "source_id", "published_at"),
        Index("ix_entries_content_hash", "content_hash"),
    )


class AnalysisModel(Base):
    """AI analysis model."""
    __tablename__ = "entry_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entry_id: Mapped[str] = mapped_column(String(36), ForeignKey("entries.id"), unique=True, nullable=False, index=True)
    attack_vector: Mapped[str] = mapped_column(Text, nullable=False)
    risk_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False)
    threat_velocity: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-100
    severity_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-100
    blast_radius_score: Mapped[int] = mapped_column(Integer, default=0)  # 1-100
    affected_ecosystem: Mapped[list[str]] = mapped_column(SQLiteJSON, default=list)
    is_pre_cve_warning: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attack_archetype: Mapped[str] = mapped_column(String(100), default="")
    weaponization_potential: Mapped[str] = mapped_column(String(50), default="Theoretical")
    model: Mapped[str] = mapped_column(String(50), default="heuristic")
    confidence: Mapped[float] = mapped_column(default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    entry: Mapped["EntryModel"] = relationship(back_populates="analysis")

    __table_args__ = (
        Index("ix_analysis_threat_velocity", "threat_velocity"),
        Index("ix_analysis_pre_cve", "is_pre_cve_warning"),
        Index("ix_analysis_severity", "severity_index"),
    )


class FetchLogModel(Base):
    """Fetch operation log model."""
    __tablename__ = "fetch_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    entries_new: Mapped[int] = mapped_column(Integer, default=0)
    entries_total: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    source: Mapped["SourceModel"] = relationship(back_populates="fetch_logs")

    __table_args__ = (
        Index("ix_fetch_log_source_fetched", "source_id", "fetched_at"),
        Index("ix_fetch_log_status", "status"),
    )


class DigestModel(Base):
    """Generated digest model."""
    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    schedule: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # daily, weekly
    entries_by_category: Mapped[dict] = mapped_column(SQLiteJSON, default=dict)
    total_entries: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_channels: Mapped[list[str]] = mapped_column(SQLiteJSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_digests_schedule_created", "schedule", "created_at"),
    )