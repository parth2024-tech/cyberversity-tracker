# Pydantic schemas for Analysis API.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ai_security_monitor.domain.entities import AnalysisModel


class AnalysisBase(BaseModel):
    """Base analysis schema."""
    attack_vector: str = Field(..., description="Attack vector description")
    risk_assessment: str = Field(..., description="Risk assessment")
    mitigation: str = Field(..., description="Mitigation steps")
    threat_velocity: int = Field(..., ge=1, le=100, description="Threat velocity (1-100)")
    severity_index: int = Field(..., ge=1, le=100, description="Severity index (1-100)")
    blast_radius_score: int = Field(default=0, ge=0, le=100, description="Blast radius score (0-100)")
    affected_ecosystem: list[str] = Field(default_factory=list, description="Affected ecosystems")
    is_pre_cve_warning: bool = Field(default=False, description="Pre-CVE warning flag")
    attack_archetype: str = Field(default="", description="Attack archetype")
    weaponization_potential: str = Field(default="Theoretical", description="Weaponization potential")
    model: AnalysisModel = Field(default=AnalysisModel.HEURISTIC, description="Analysis model")
    confidence: float = Field(default=1.0, ge=0, le=1, description="Confidence score")


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
