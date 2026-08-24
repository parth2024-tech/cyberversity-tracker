"""
Unit tests for Analyzer plugins (Heuristic, Blast Radius, LLM).
"""
import pytest

from ai_security_monitor.infrastructure.analyzers.blast_radius_analyzer import (
    BlastRadiusAnalyzer,
)
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
    HeuristicAnalyzer,
)


@pytest.mark.asyncio
async def test_heuristic_analyzer(sample_entry):
    analyzer = HeuristicAnalyzer()
    result = await analyzer.analyze(sample_entry)

    assert result.threat_velocity >= 1
    assert result.severity_index >= 1
    assert result.attack_vector != ""
    assert result.risk_assessment != ""
    assert result.mitigation != ""


@pytest.mark.asyncio
async def test_blast_radius_analyzer_with_ai_frameworks(sample_entry):
    analyzer = BlastRadiusAnalyzer()
    result = await analyzer.analyze(sample_entry)

    assert result.blast_radius_score >= 1
    assert isinstance(result.affected_ecosystem, list)
    # The title contains "Vision-Language Models" -> should trigger Pre-CVE Warning
    assert result.is_pre_cve_warning is True
    assert result.attack_archetype != ""
