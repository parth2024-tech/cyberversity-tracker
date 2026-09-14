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


@pytest.mark.asyncio
async def test_mitre_attack_and_weaponization_detection(sample_entry):
    analyzer = HeuristicAnalyzer()
    result = await analyzer.analyze(sample_entry)

    # Check MITRE ATT&CK assignment
    assert result.mitre_attack_id is not None
    assert result.mitre_technique is not None

    # Test Jailbreak MITRE mapping
    sample_entry.title = "Novel jailbreak bypasses Claude safety guardrails"
    res_jb = await analyzer.analyze(sample_entry)
    assert res_jb.mitre_attack_id == "AML.T0054"
    assert "Jailbreak" in res_jb.mitre_technique

    # Test PoC Weaponization
    sample_entry.title = "Critical RCE exploit PoC released for Fortinet VPN"
    sample_entry.summary = "A remote code execution vulnerability in Fortinet SSL-VPN allows arbitrary code execution."
    res_poc = await analyzer.analyze(sample_entry)
    assert res_poc.weaponization_potential == "PoC Verified"
    assert res_poc.mitre_attack_id == "T1190"


@pytest.mark.asyncio
async def test_heuristic_analyzer_ai_innovation(sample_entry):
    from ai_security_monitor.domain.entities import Category
    analyzer = HeuristicAnalyzer()

    # Test Trending GitHub repo
    sample_entry.category = Category.GITHUB_TRENDING
    sample_entry.title = "vllm: Easy, fast, and cheap LLM serving for everyone"
    sample_entry.summary = "High-throughput and memory-efficient inference and serving engine for LLMs."
    sample_entry.metadata = {"repo_name": "vllm-project/vllm", "language": "Python"}
    res_repo = await analyzer.analyze(sample_entry)

    assert "Infrastructure" in res_repo.attack_vector or "Tool" in res_repo.attack_vector or "Open-Source" in res_repo.risk_assessment
    assert res_repo.attack_archetype == "Trending Repository"
    assert res_repo.threat_velocity >= 50

    # Test Frontier AI Model Release
    sample_entry.category = Category.AI_MODELS
    sample_entry.title = "DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning"
    sample_entry.summary = "Open-weights reasoning model with state-of-the-art performance on AIME and MATH benchmarks."
    res_model = await analyzer.analyze(sample_entry)

    assert res_model.attack_archetype == "AI Model Release"
    assert res_model.is_pre_cve_warning is False
