"""
Value objects - immutable domain objects with value equality.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class ContentHash:
    """SHA256 content hash for deduplication."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("Content hash cannot be empty")
        if len(self.value) != 64:  # SHA256 hex = 64 chars
            raise ValueError("Content hash must be 64 character hex string")

    @classmethod
    def from_content(cls, *parts: str) -> Self:
        """Create hash from content parts."""
        content = "|".join(str(p) for p in parts if p)
        hash_value = hashlib.sha256(content.encode()).hexdigest()
        return cls(value=hash_value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ThreatScore:
    """Threat scoring value object (1-100)."""

    velocity: int  # 1-100: How fast threat is moving
    severity: int  # 1-100: How severe the impact
    blast_radius: int = 0  # 1-100: Ecosystem impact

    def __post_init__(self):
        for field_name in ("velocity", "severity", "blast_radius"):
            value = getattr(self, field_name)
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be 0-100, got {value}")

    @property
    def is_high_velocity(self) -> bool:
        return self.velocity >= 70

    @property
    def is_critical(self) -> bool:
        return self.velocity >= 80 and self.severity >= 70

    def __str__(self) -> str:
        return f"V:{self.velocity} S:{self.severity} B:{self.blast_radius}"


class WeaponizationLevel(str, Enum):
    """Weaponization potential level."""

    THEORETICAL = "Theoretical"
    POC_VERIFIED = "PoC Verified"
    ACTIVE_WEAPONIZATION = "Active Weaponization"

    @classmethod
    def theoretical(cls) -> "WeaponizationLevel":
        return cls.THEORETICAL

    @classmethod
    def poc_verified(cls) -> "WeaponizationLevel":
        return cls.POC_VERIFIED

    @classmethod
    def active_weaponization(cls) -> "WeaponizationLevel":
        return cls.ACTIVE_WEAPONIZATION

    def __str__(self) -> str:
        return self.value


class AttackArchetype(str, Enum):
    """Known attack archetypes for classification."""

    JAILBREAK = "Jailbreak"
    RAG_POISONING = "RAG Poisoning"
    MODEL_INVERSION = "Model Inversion"
    PROMPT_INJECTION = "Prompt Injection"
    DATA_POISONING = "Data Poisoning"
    MODEL_EXTRACTION = "Model Extraction"
    SUPPLY_CHAIN = "Supply Chain Compromise"
    RCE = "Remote Code Execution"
    PRIVILEGE_ESCALATION = "Privilege Escalation"
    NOVEL_ACADEMIC = "Novel Academic Threat Vector"
    STANDARD_VULN = "Standard Vulnerability"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, value: str) -> "AttackArchetype":
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN

    def __str__(self) -> str:
        return self.value


class DecisionAction(str, Enum):
    """Validated concrete action recommendation for personal intelligence decision briefs."""

    TEST_IN_SANDBOX = "TEST_IN_SANDBOX"
    UPGRADE_DEPENDENCY = "UPGRADE_DEPENDENCY"
    READ_PAPER = "READ_PAPER"
    MONITOR_CLAIMS = "MONITOR_CLAIMS"
    IGNORE_HYPE = "IGNORE_HYPE"

    @classmethod
    def from_string(cls, val: str) -> "DecisionAction":
        val_clean = str(val).strip().upper().replace(" ", "_").replace("-", "_")
        for member in cls:
            if member.value == val_clean or member.name == val_clean:
                return member
        return cls.MONITOR_CLAIMS


class EvidenceConfidence(str, Enum):
    """Deterministic evidence calibration confidence level."""

    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    PRELIMINARY = "PRELIMINARY"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    @classmethod
    def from_string(cls, val: str) -> "EvidenceConfidence":
        val_clean = str(val).strip().upper().replace(" ", "_")
        for member in cls:
            if member.value == val_clean or member.name == val_clean:
                return member
        return cls.PRELIMINARY


class StackImpactLevel(str, Enum):
    """Categorized personal stack impact level."""

    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, val: str) -> "StackImpactLevel":
        val_clean = str(val).strip().upper().replace(" ", "_")
        for member in cls:
            if member.value == val_clean or member.name == val_clean:
                return member
        return cls.UNKNOWN


class NoveltyType(str, Enum):
    """Distinguishes genuine architectural breakthrough from repackaging/incremental progress."""

    GENUINE_NOVELTY = "GENUINE_NOVELTY"
    INCREMENTAL_UPDATE = "INCREMENTAL_UPDATE"
    REPACKAGING = "REPACKAGING"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"

    @classmethod
    def from_string(cls, val: str) -> "NoveltyType":
        val_clean = str(val).strip().upper().replace(" ", "_")
        for member in cls:
            if member.value == val_clean or member.name == val_clean:
                return member
        return cls.INSUFFICIENT_HISTORY


@dataclass(slots=True)
class HistoricalComparison:
    """Historical entry retrieved from local vector memory for novelty grounding."""

    entry_id: str | None
    title: str
    published_at: str | None = None
    similarity_score: float = 0.0
    relation: str = "similar_topic"
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NoveltyAssessment:
    """Nuanced distinction between local DB novelty and global industry novelty."""

    novelty_type: NoveltyType = NoveltyType.INSUFFICIENT_HISTORY
    summary: str = ""
    comparison_notes: str = ""
    uncertainties: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["novelty_type"] = self.novelty_type.value
        return data


@dataclass(slots=True)
class StackRelevance:
    """Personalized relevance assessment grounded in configured watchlist and blast radius."""

    impact_level: StackImpactLevel = StackImpactLevel.NO_MATCH
    matching_watchlist_rules: list[str] = field(default_factory=list)
    matched_technologies: list[str] = field(default_factory=list)
    direct_impact: str | None = None
    indirect_impact: str | None = None
    affected_components: list[str] = field(default_factory=list)
    suggested_priority: str = "P2"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["impact_level"] = self.impact_level.value
        return data


@dataclass(slots=True)
class EvidenceAssessment:
    """Deterministic evaluation of claim truth and source corroboration."""

    confidence: EvidenceConfidence = EvidenceConfidence.PRELIMINARY
    primary_source_type: str = "general"
    corroboration_count: int = 1
    has_reproducible_artifact: bool = False
    claim_verification_score: float = 1.0
    notes: str = ""
    conflicting_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = self.confidence.value
        return data


@dataclass(slots=True)
class PersonalDecisionBrief:
    """Structured Five-Question Personal Intelligence Decision Brief."""

    event_summary: str
    significance: str
    novelty_assessment: NoveltyAssessment
    historical_comparisons: list[HistoricalComparison] = field(default_factory=list)
    stack_relevance: StackRelevance = field(default_factory=StackRelevance)
    evidence_assessment: EvidenceAssessment = field(default_factory=EvidenceAssessment)
    recommended_action: DecisionAction = DecisionAction.MONITOR_CLAIMS
    action_rationale: str = ""
    source_references: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    analysis_version: str = "v1-decision-brief"

    def to_dict(self) -> dict[str, Any]:
        """Convert entire Decision Brief to JSON-compatible dictionary."""
        return {
            "event_summary": self.event_summary,
            "significance": self.significance,
            "novelty_assessment": self.novelty_assessment.to_dict(),
            "historical_comparisons": [
                c.to_dict() for c in self.historical_comparisons
            ],
            "stack_relevance": self.stack_relevance.to_dict(),
            "evidence_assessment": self.evidence_assessment.to_dict(),
            "recommended_action": self.recommended_action.value,
            "action_rationale": self.action_rationale,
            "source_references": list(self.source_references),
            "generated_at": self.generated_at,
            "analysis_version": self.analysis_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PersonalDecisionBrief":
        """Reconstruct PersonalDecisionBrief from a JSON dictionary."""
        if not data:
            return cls(
                event_summary="",
                significance="",
                novelty_assessment=NoveltyAssessment(),
            )

        novelty_data = data.get("novelty_assessment") or {}
        novelty = NoveltyAssessment(
            novelty_type=NoveltyType.from_string(novelty_data.get("novelty_type", "")),
            summary=novelty_data.get("summary", ""),
            comparison_notes=novelty_data.get("comparison_notes", ""),
            uncertainties=list(novelty_data.get("uncertainties", [])),
        )

        hist_list = []
        for h in data.get("historical_comparisons", []):
            if isinstance(h, dict):
                hist_list.append(
                    HistoricalComparison(
                        entry_id=h.get("entry_id"),
                        title=h.get("title", ""),
                        published_at=h.get("published_at"),
                        similarity_score=float(h.get("similarity_score", 0.0)),
                        relation=h.get("relation", "similar_topic"),
                        source_url=h.get("source_url"),
                    )
                )

        stack_data = data.get("stack_relevance") or {}
        stack = StackRelevance(
            impact_level=StackImpactLevel.from_string(
                stack_data.get("impact_level", "")
            ),
            matching_watchlist_rules=list(
                stack_data.get("matching_watchlist_rules", [])
            ),
            matched_technologies=list(stack_data.get("matched_technologies", [])),
            direct_impact=stack_data.get("direct_impact"),
            indirect_impact=stack_data.get("indirect_impact"),
            affected_components=list(stack_data.get("affected_components", [])),
            suggested_priority=stack_data.get("suggested_priority", "P2"),
            reasons=list(stack_data.get("reasons", [])),
        )

        ev_data = data.get("evidence_assessment") or {}
        evidence = EvidenceAssessment(
            confidence=EvidenceConfidence.from_string(ev_data.get("confidence", "")),
            primary_source_type=ev_data.get("primary_source_type", "general"),
            corroboration_count=int(ev_data.get("corroboration_count", 1)),
            has_reproducible_artifact=bool(
                ev_data.get("has_reproducible_artifact", False)
            ),
            claim_verification_score=float(
                ev_data.get("claim_verification_score", 1.0)
            ),
            notes=ev_data.get("notes", ""),
            conflicting_signals=list(ev_data.get("conflicting_signals", [])),
        )

        action = DecisionAction.from_string(data.get("recommended_action", ""))

        return cls(
            event_summary=data.get("event_summary", ""),
            significance=data.get("significance", ""),
            novelty_assessment=novelty,
            historical_comparisons=hist_list,
            stack_relevance=stack,
            evidence_assessment=evidence,
            recommended_action=action,
            action_rationale=data.get("action_rationale", ""),
            source_references=list(data.get("source_references", [])),
            generated_at=data.get("generated_at", datetime.now(UTC).isoformat()),
            analysis_version=data.get("analysis_version", "v1-decision-brief"),
        )
