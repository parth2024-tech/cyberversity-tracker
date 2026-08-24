"""
Unit tests for Domain layer (Entities, Value Objects, Events).
"""

import pytest

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
)
from ai_security_monitor.domain.value_objects import (
    AttackArchetype,
    ContentHash,
    ThreatScore,
    WeaponizationLevel,
)


def test_content_hash_validation():
    # Valid hash
    valid_hex = "a" * 64
    ch = ContentHash(valid_hex)
    assert str(ch) == valid_hex

    # Auto generation
    ch_auto = ContentHash.from_content("title", "url", "2026-08-25")
    assert len(str(ch_auto)) == 64

    # Invalid length
    with pytest.raises(ValueError):
        ContentHash("invalid_short_hash")


def test_threat_score():
    score = ThreatScore(velocity=85, severity=90, blast_radius=75)
    assert score.is_high_velocity is True
    assert score.is_critical is True

    low_score = ThreatScore(velocity=30, severity=40)
    assert low_score.is_high_velocity is False
    assert low_score.is_critical is False

    with pytest.raises(ValueError):
        ThreatScore(velocity=150, severity=50)


def test_weaponization_level():
    w = WeaponizationLevel.poc_verified()
    assert str(w) == "PoC Verified"


def test_attack_archetype():
    a = AttackArchetype.from_string("Jailbreak")
    assert str(a) == "Jailbreak"

    unknown = AttackArchetype.from_string("non_existent_type")
    assert str(unknown) == "Unknown"


def test_entry_and_analysis_relationship(sample_source, sample_entry):
    assert sample_entry.source_id == sample_source.id
    assert sample_entry.category == Category.AI_RESEARCH

    analysis = Analysis(
        entry_id=sample_entry.id,
        attack_vector="Multimodal perturbation",
        risk_assessment="System prompt extraction",
        mitigation="Input sanitize filter",
        threat_velocity=85,
        severity_index=80,
        blast_radius_score=70,
        affected_ecosystem=["PyTorch", "Transformers"],
        is_pre_cve_warning=True,
        attack_archetype="Jailbreak",
        weaponization_potential="PoC Verified",
        model=AnalysisModel.HEURISTIC
    )
    sample_entry.analysis = analysis
    assert sample_entry.analysis.is_pre_cve_warning is True
    assert sample_entry.analysis.threat_velocity == 85
