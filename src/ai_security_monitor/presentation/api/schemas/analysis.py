# Pydantic schemas for Analysis API.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ai_security_monitor.domain.entities import AnalysisModel
from ai_security_monitor.domain.value_objects import (
    DecisionAction,
    EvidenceConfidence,
    NoveltyType,
    StackImpactLevel,
)


class HistoricalComparisonSchema(BaseModel):
    """Historical entry comparison schema."""

    entry_id: str | None = None
    title: str = Field(..., max_length=500, description="Headline of historical entry")
    published_at: str | None = None
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relation: str = Field(default="similar_topic", max_length=200)
    source_url: str | None = None


class NoveltyAssessmentSchema(BaseModel):
    """Nuanced distinction between local and global novelty."""

    novelty_type: NoveltyType = Field(
        default=NoveltyType.INSUFFICIENT_HISTORY, description="Novelty classification"
    )
    summary: str = Field(default="", max_length=1500, description="Novelty summary")
    comparison_notes: str = Field(
        default="", max_length=2000, description="Comparison notes"
    )
    uncertainties: list[str] = Field(
        default_factory=list, description="Known uncertainties"
    )


class StackRelevanceSchema(BaseModel):
    """Personalized stack impact schema."""

    impact_level: StackImpactLevel = Field(
        default=StackImpactLevel.NO_MATCH, description="Direct or indirect impact"
    )
    matching_watchlist_rules: list[str] = Field(
        default_factory=list, description="Matched watchlist rule names"
    )
    matched_technologies: list[str] = Field(
        default_factory=list, description="Matched framework components"
    )
    direct_impact: str | None = Field(default=None, max_length=1000)
    indirect_impact: str | None = Field(default=None, max_length=1000)
    affected_components: list[str] = Field(default_factory=list)
    suggested_priority: str = Field(default="P2", max_length=20)
    reasons: list[str] = Field(default_factory=list)


class EvidenceAssessmentSchema(BaseModel):
    """Deterministic evidence calibration schema."""

    confidence: EvidenceConfidence = Field(
        default=EvidenceConfidence.PRELIMINARY, description="Epistemic confidence level"
    )
    primary_source_type: str = Field(default="general", max_length=100)
    corroboration_count: int = Field(default=1, ge=0)
    has_reproducible_artifact: bool = Field(default=False)
    claim_verification_score: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: str = Field(default="", max_length=1500)
    conflicting_signals: list[str] = Field(default_factory=list)


class PersonalDecisionBriefSchema(BaseModel):
    """Structured Five-Question Personal Intelligence Decision Brief schema."""

    event_summary: str = Field(..., max_length=2500, description="Q1: What happened?")
    significance: str = Field(
        ..., max_length=2500, description="Q2: Why does it matter?"
    )
    novelty_assessment: NoveltyAssessmentSchema = Field(
        ..., description="Q3: What's new?"
    )
    historical_comparisons: list[HistoricalComparisonSchema] = Field(
        default_factory=list, description="Historical vector comparisons"
    )
    stack_relevance: StackRelevanceSchema = Field(
        default_factory=StackRelevanceSchema, description="Q4: Stack impact"
    )
    evidence_assessment: EvidenceAssessmentSchema = Field(
        default_factory=EvidenceAssessmentSchema, description="Evidence confidence"
    )
    recommended_action: DecisionAction = Field(
        default=DecisionAction.MONITOR_CLAIMS, description="Q5: What should I do next?"
    )
    action_rationale: str = Field(
        default="", max_length=1500, description="Action rationale"
    )
    source_references: list[str] = Field(
        default_factory=list, description="Citations and evidence links"
    )
    generated_at: str = Field(default="", description="ISO timestamp")
    analysis_version: str = Field(default="v1-decision-brief", max_length=50)


class AnalysisBase(BaseModel):
    """Base analysis schema."""

    attack_vector: str = Field(..., description="Attack vector description")
    risk_assessment: str = Field(..., description="Risk assessment")
    mitigation: str = Field(..., description="Mitigation steps")
    threat_velocity: int = Field(
        ..., ge=1, le=100, description="Threat velocity (1-100)"
    )
    severity_index: int = Field(..., ge=1, le=100, description="Severity index (1-100)")
    blast_radius_score: int = Field(
        default=0, ge=0, le=100, description="Blast radius score (0-100)"
    )
    affected_ecosystem: list[str] = Field(
        default_factory=list, description="Affected ecosystems"
    )
    is_pre_cve_warning: bool = Field(default=False, description="Pre-CVE warning flag")
    attack_archetype: str = Field(default="", description="Attack archetype")
    weaponization_potential: str = Field(
        default="Theoretical", description="Weaponization potential"
    )
    model: AnalysisModel = Field(
        default=AnalysisModel.HEURISTIC, description="Analysis model"
    )
    confidence: float = Field(default=1.0, ge=0, le=1, description="Confidence score")
    decision_brief: PersonalDecisionBriefSchema | None = Field(
        default=None, description="Personal Intelligence Decision Brief"
    )


class AnalysisCreate(AnalysisBase):
    """Schema for creating an analysis."""

    entry_id: UUID = Field(..., description="Entry UUID")


class AnalysisRead(AnalysisBase):
    """Schema for reading an analysis."""

    id: UUID
    entry_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
