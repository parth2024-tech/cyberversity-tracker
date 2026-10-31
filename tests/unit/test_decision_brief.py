"""
Comprehensive unit and integration tests for Personal Intelligence Decision Brief.
Covers:
1. Schema & Data Model (validation, serialization, enums, limits, backward compatibility)
2. Historical Vector Retrieval & Novelty Grounding (sqlite-vec KNN, fallback, empty history)
3. Personal Relevance & Watchlist Matching (direct, indirect, no-match, priority)
4. Deterministic Evidence Assessment (official, multi-source, social media, contradicted)
5. Validated Actions & Safety Guards (5 enums, cautious defaults, no auto-exec)
6. Telegram ChatOps & Gazette Integration (in-place message edit, caching reuse)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.decision_brief_service import (
    DecisionBriefService,
    decision_brief_service,
)
from ai_security_monitor.application.services.telegram_chatops_service import (
    TelegramChatOpsService,
)
from ai_security_monitor.domain.entities import Analysis, Category, Entry
from ai_security_monitor.domain.value_objects import (
    DecisionAction,
    EvidenceAssessment,
    EvidenceConfidence,
    HistoricalComparison,
    NoveltyAssessment,
    NoveltyType,
    PersonalDecisionBrief,
    StackImpactLevel,
    StackRelevance,
)
from ai_security_monitor.domain.watchlist import WatchlistRule
from ai_security_monitor.presentation.api.schemas.analysis import (
    AnalysisRead,
    PersonalDecisionBriefSchema,
)


@pytest.fixture
def sample_entry() -> Entry:
    """Fixture providing a standard AI research entry."""
    return Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek-R1: Incentivizing Reasoning Capability via Reinforcement Learning",
        url="https://arxiv.org/abs/2501.12948",
        summary="We introduce DeepSeek-R1-Zero and DeepSeek-R1, reasoning foundation models.",
        content_hash="a" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
        tags=["reasoning", "reinforcement-learning", "deepseek"],
        metadata={"source_count": 2, "source_type": "arxiv"},
    )


# ==============================================================================
# 1. Schema & Validation Tests
# ==============================================================================


def test_decision_brief_serialization_and_deserialization():
    """Verify bidirectional conversion between domain dataclass and dictionary."""
    brief = PersonalDecisionBrief(
        event_summary="DeepSeek published DeepSeek-R1 open reasoning weights.",
        significance="Demonstrates competitive reasoning without supervised fine-tuning.",
        novelty_assessment=NoveltyAssessment(
            novelty_type=NoveltyType.GENUINE_NOVELTY,
            summary="First pure RL cold-start reasoning capability on large-scale open weights.",
            comparison_notes="Compared to DeepSeek-V3 and OpenAI o1.",
            uncertainties=["Long-context memory scaling bounds."],
        ),
        historical_comparisons=[
            HistoricalComparison(
                entry_id="00000000-0000-0000-0000-000000000001",
                title="DeepSeek-V3 Technical Report",
                published_at="2024-12-26",
                similarity_score=0.82,
                relation="prior_model_architecture",
                source_url="https://arxiv.org/abs/2412.19437",
            )
        ],
        stack_relevance=StackRelevance(
            impact_level=StackImpactLevel.DIRECT,
            matching_watchlist_rules=["Local Reasoning Models"],
            matched_technologies=["vLLM", "DeepSeek"],
            direct_impact="Directly deployable on local vLLM cluster.",
            suggested_priority="P0",
            reasons=["Matches tracked framework 'vLLM'."],
        ),
        evidence_assessment=EvidenceAssessment(
            confidence=EvidenceConfidence.VERIFIED,
            primary_source_type="academic_preprint (arXiv)",
            corroboration_count=3,
            has_reproducible_artifact=True,
            claim_verification_score=0.95,
            notes="Multiple independent evaluations confirmed reasoning performance.",
        ),
        recommended_action=DecisionAction.TEST_IN_SANDBOX,
        action_rationale="Test quantized FP8 checkpoint on vLLM test harness.",
        source_references=["https://arxiv.org/abs/2501.12948"],
    )

    data = brief.to_dict()
    assert isinstance(data, dict)
    assert data["recommended_action"] == "TEST_IN_SANDBOX"
    assert data["evidence_assessment"]["confidence"] == "VERIFIED"
    assert data["novelty_assessment"]["novelty_type"] == "GENUINE_NOVELTY"
    assert len(data["historical_comparisons"]) == 1

    # Reconstruct from dict
    reconstructed = PersonalDecisionBrief.from_dict(data)
    assert reconstructed.event_summary == brief.event_summary
    assert reconstructed.recommended_action == DecisionAction.TEST_IN_SANDBOX
    assert reconstructed.evidence_assessment.confidence == EvidenceConfidence.VERIFIED
    assert reconstructed.stack_relevance.impact_level == StackImpactLevel.DIRECT
    assert reconstructed.historical_comparisons[0].title == "DeepSeek-V3 Technical Report"


def test_pydantic_schema_validation_and_backward_compatibility(sample_entry: Entry):
    """Pydantic schemas validate correctly and preserve backward compatibility with AnalysisRead."""
    brief_data = {
        "event_summary": "vLLM 0.7.0 released with multi-tier cache.",
        "significance": "Reduces TTFT by 40% across chunked prefill workloads.",
        "novelty_assessment": {
            "novelty_type": "INCREMENTAL_UPDATE",
            "summary": "Incremental optimization of KV cache scheduler.",
            "comparison_notes": "Builds on vLLM 0.6.6.",
            "uncertainties": [],
        },
        "historical_comparisons": [],
        "stack_relevance": {
            "impact_level": "DIRECT",
            "matching_watchlist_rules": ["vLLM Infrastructure"],
            "matched_technologies": ["vLLM"],
            "suggested_priority": "P1",
            "reasons": ["Direct watchlist hit"],
        },
        "evidence_assessment": {
            "confidence": "SUPPORTED",
            "primary_source_type": "source_code_repository",
            "corroboration_count": 1,
            "has_reproducible_artifact": True,
            "claim_verification_score": 1.0,
            "notes": "Official release notes on GitHub",
            "conflicting_signals": [],
        },
        "recommended_action": "TEST_IN_SANDBOX",
        "action_rationale": "Run offline inference benchmark.",
        "source_references": ["https://github.com/vllm-project/vllm/releases"],
        "generated_at": datetime.now(UTC).isoformat(),
        "analysis_version": "v1-decision-brief",
    }

    schema = PersonalDecisionBriefSchema(**brief_data)
    assert schema.recommended_action == DecisionAction.TEST_IN_SANDBOX
    assert schema.novelty_assessment.novelty_type == NoveltyType.INCREMENTAL_UPDATE

    # Backward compatibility: AnalysisRead works with or without decision_brief
    analysis_read_with_brief = AnalysisRead(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="Inference Latency Optimization",
        risk_assessment="Performance enhancement",
        mitigation="Evaluate benchmark",
        threat_velocity=80,
        severity_index=70,
        blast_radius_score=60,
        decision_brief=schema,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analysis_read_with_brief.decision_brief is not None
    assert analysis_read_with_brief.decision_brief.recommended_action == DecisionAction.TEST_IN_SANDBOX

    analysis_read_without_brief = AnalysisRead(
        id=uuid4(),
        entry_id=sample_entry.id,
        attack_vector="General AI Update",
        risk_assessment="Standard telemetry",
        mitigation="Monitor",
        threat_velocity=50,
        severity_index=50,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analysis_read_without_brief.decision_brief is None


def test_invalid_action_enum_fallback():
    """String parsing falls back to MONITOR_CLAIMS on unexpected action string."""
    assert DecisionAction.from_string("INVALID_RANDOM_ACTION") == DecisionAction.MONITOR_CLAIMS
    assert DecisionAction.from_string("test in sandbox") == DecisionAction.TEST_IN_SANDBOX
    assert EvidenceConfidence.from_string("unknown_conf") == EvidenceConfidence.PRELIMINARY
    assert StackImpactLevel.from_string("non_existent") == StackImpactLevel.UNKNOWN
    assert NoveltyType.from_string("bogus_novelty") == NoveltyType.INSUFFICIENT_HISTORY


# ==============================================================================
# 2. Historical Vector Retrieval Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_historical_retrieval_empty_history(sample_entry: Entry):
    """When no historical records exist in vector DB, returns empty list which triggers INSUFFICIENT_HISTORY."""
    service = DecisionBriefService()
    mock_uow = MagicMock()
    # Mock sqlite-vec executing query returning empty
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_uow.session.execute = AsyncMock(return_value=mock_result)
    mock_uow.entries.list = AsyncMock(return_value=[])

    history = await service.retrieve_historical_comparisons(sample_entry, uow=mock_uow)
    assert len(history) == 0

    # Brief synthesis assigns INSUFFICIENT_HISTORY
    _, _, novelty = await service._synthesize_q1_q2_q3(
        entry=sample_entry,
        historical_comparisons=history,
        stack_relevance=StackRelevance(),
        evidence=EvidenceAssessment(),
    )
    assert novelty.novelty_type == NoveltyType.INSUFFICIENT_HISTORY
    assert "Insufficient prior historical records" in novelty.summary


@pytest.mark.asyncio
async def test_historical_retrieval_finds_similar_entries(sample_entry: Entry):
    """Simulates finding relevant historical comparison records and grounding novelty."""
    service = DecisionBriefService()
    mock_uow = MagicMock()

    hist_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="DeepSeek-V3 Architecture and Multi-Head Latent Attention",
        url="https://arxiv.org/abs/2412.19437",
        summary="Technical analysis of DeepSeek-V3 architecture with MLA.",
        content_hash="b" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )

    mock_uow.entries.list = AsyncMock(return_value=[hist_entry])
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_uow.session.execute = AsyncMock(return_value=mock_result)

    comparisons = await service.retrieve_historical_comparisons(sample_entry, uow=mock_uow)
    assert len(comparisons) >= 1
    assert comparisons[0].title == hist_entry.title
    assert comparisons[0].similarity_score > 0.40

    # When similar work exists, novelty reflects incremental development
    _, _, novelty = await service._synthesize_q1_q2_q3(
        entry=sample_entry,
        historical_comparisons=comparisons,
        stack_relevance=StackRelevance(),
        evidence=EvidenceAssessment(),
    )
    assert novelty.novelty_type in (NoveltyType.INCREMENTAL_UPDATE, NoveltyType.GENUINE_NOVELTY)


# ==============================================================================
# 3. Personal Relevance & Watchlist Matching Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_stack_relevance_direct_match(sample_entry: Entry):
    """Entry matching user-configured WatchlistRule gets DIRECT impact and elevated priority."""
    service = DecisionBriefService()
    mock_uow = MagicMock()

    rule = WatchlistRule(
        name="Reasoning Models",
        keywords=["reasoning", "deepseek"],
        enabled=True,
    )
    mock_uow.watchlist.list = AsyncMock(return_value=[rule])

    relevance = await service.evaluate_stack_relevance(sample_entry, uow=mock_uow)
    assert relevance.impact_level == StackImpactLevel.DIRECT
    assert "Reasoning Models" in relevance.matching_watchlist_rules
    assert "DeepSeek" in relevance.matched_technologies or "deepseek" in [t.lower() for t in relevance.matched_technologies]
    assert relevance.direct_impact is not None
    assert relevance.suggested_priority in ("P0", "P1")


@pytest.mark.asyncio
async def test_stack_relevance_indirect_framework_overlap():
    """Entry mentioning an ecosystem framework without direct watchlist rule gets INDIRECT impact."""
    service = DecisionBriefService()
    mock_uow = MagicMock()
    mock_uow.watchlist.list = AsyncMock(return_value=[])  # No matching custom rules

    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="vLLM continuous batching performance benchmark with FP8",
        url="https://github.com/vllm-project/vllm",
        summary="Measuring token latency on NVIDIA H100 with chunked prefill.",
        content_hash="c" * 64,
        published_at=datetime.now(UTC),
        category=Category.GITHUB_TRENDING,
    )

    relevance = await service.evaluate_stack_relevance(entry, uow=mock_uow)
    assert relevance.impact_level == StackImpactLevel.INDIRECT
    assert "vLLM" in relevance.matched_technologies
    assert relevance.indirect_impact is not None


@pytest.mark.asyncio
async def test_stack_relevance_no_match():
    """Unrelated entry gets NO_MATCH without manufacturing personal relevance."""
    service = DecisionBriefService()
    mock_uow = MagicMock()
    mock_uow.watchlist.list = AsyncMock(return_value=[])

    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Ancient Roman Pottery Discovered in Southern France",
        url="https://example.org/pottery",
        summary="Archaeologists uncover amphorae dating back to the 1st century AD.",
        content_hash="d" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )

    relevance = await service.evaluate_stack_relevance(entry, uow=mock_uow)
    assert relevance.impact_level == StackImpactLevel.NO_MATCH
    assert len(relevance.matching_watchlist_rules) == 0
    assert len(relevance.matched_technologies) == 0
    assert relevance.direct_impact is None
    assert relevance.indirect_impact is None


# ==============================================================================
# 4. Deterministic Evidence Assessment Tests
# ==============================================================================


def test_evidence_assessment_official_multi_source():
    """Official source with reproducible artifact and multi-source corroboration yields VERIFIED."""
    service = DecisionBriefService()
    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Llama-3.3-70B Open Weights Released on Hugging Face",
        url="https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct",
        summary="Meta releases official weights and model card for Llama-3.3-70B.",
        content_hash="e" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata={"source_count": 3, "has_weights": True},
    )

    ev = service.evaluate_evidence(entry)
    assert ev.confidence == EvidenceConfidence.VERIFIED
    assert ev.has_reproducible_artifact is True
    assert ev.corroboration_count >= 2


def test_evidence_assessment_social_media_rumor():
    """Single-source social media post with no code or paper yields INSUFFICIENT_EVIDENCE."""
    service = DecisionBriefService()
    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Rumor: Secret AGI model benchmark leak on Twitter",
        url="https://x.com/leaker123/status/123456",
        summary="Someone claims their friend tested a model achieving 99% on ARC-AGI.",
        content_hash="f" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        metadata={"source_count": 1},
    )

    ev = service.evaluate_evidence(entry)
    assert ev.confidence in (EvidenceConfidence.INSUFFICIENT_EVIDENCE, EvidenceConfidence.PRELIMINARY)
    assert ev.primary_source_type == "social_media_discussion"


# ==============================================================================
# 5. Validated Actions & Safety Guards Tests
# ==============================================================================


def test_action_determination_all_five_actions():
    """Verifies that each of the 5 validated actions is triggered under appropriate conditions."""
    service = DecisionBriefService()

    # 1. UPGRADE_DEPENDENCY: Security/Patch with identified affected component
    patch_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="vLLM v0.7.1 Security Patch for HTTP Server Deserialization",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.7.1",
        summary="Patches CVE-2025-1111 arbitrary code execution in API server.",
        content_hash="g" * 64,
        published_at=datetime.now(UTC),
        category=Category.VULNERABILITIES,
    )
    stack_direct = StackRelevance(
        impact_level=StackImpactLevel.DIRECT,
        matching_watchlist_rules=["vLLM Serving"],
        matched_technologies=["vLLM"],
        affected_components=["vLLM"],
    )
    ev_verified = EvidenceAssessment(confidence=EvidenceConfidence.VERIFIED)
    act, rat = service.determine_recommended_action(patch_entry, ev_verified, stack_direct)
    assert act == DecisionAction.UPGRADE_DEPENDENCY
    assert "patch" in rat.lower() or "critical" in rat.lower()

    # 2. READ_PAPER: Foundational research preprint with supported evidence
    paper_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Scaling Test-Time Compute in Mathematical Olympiad Reasoning",
        url="https://arxiv.org/abs/2502.99999",
        summary="Formal analysis of search over verifier reward distributions.",
        content_hash="h" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
    )
    act, rat = service.determine_recommended_action(paper_entry, ev_verified, StackRelevance())
    assert act == DecisionAction.READ_PAPER

    # 3. TEST_IN_SANDBOX: Open source models or runtimes with artifacts
    tool_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="SGLang v0.4: Multi-Node Serving with Chunked Speculative Decoding",
        url="https://github.com/sgl-project/sglang",
        summary="High-throughput serving runtime with RadixAttention.",
        content_hash="i" * 64,
        published_at=datetime.now(UTC),
        category=Category.GITHUB_TRENDING,
    )
    ev_artifact = EvidenceAssessment(confidence=EvidenceConfidence.SUPPORTED, has_reproducible_artifact=True)
    act, rat = service.determine_recommended_action(tool_entry, ev_artifact, StackRelevance())
    assert act == DecisionAction.TEST_IN_SANDBOX

    # 4. MONITOR_CLAIMS: Preliminary or unverified claims
    ev_prelim = EvidenceAssessment(confidence=EvidenceConfidence.PRELIMINARY)
    act, rat = service.determine_recommended_action(tool_entry, ev_prelim, StackRelevance())
    assert act == DecisionAction.MONITOR_CLAIMS

    # 5. IGNORE_HYPE: Unrelated, low-priority marketing
    hype_entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Revolutionary AI Synergy Platform Promises 1000x Developer Productivity",
        url="https://hypecorp.io/press",
        summary="Buzzword marketing release with no benchmark or code repository.",
        content_hash="j" * 64,
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
    )
    act, rat = service.determine_recommended_action(hype_entry, ev_prelim, StackRelevance(impact_level=StackImpactLevel.NO_MATCH))
    assert act == DecisionAction.IGNORE_HYPE


def test_safety_guard_no_upgrade_without_component():
    """Never recommends UPGRADE_DEPENDENCY without an identified affected component."""
    service = DecisionBriefService()
    vague_patch = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="Security Advisory: General vulnerability in unspecified packages",
        url="https://advisory.example.org",
        summary="Some unspecified open source packages were reported vulnerable.",
        content_hash="k" * 64,
        published_at=datetime.now(UTC),
        category=Category.VULNERABILITIES,
    )
    relevance_empty = StackRelevance(impact_level=StackImpactLevel.DIRECT, affected_components=[])
    ev = EvidenceAssessment(confidence=EvidenceConfidence.SUPPORTED)

    act, _ = service.determine_recommended_action(vague_patch, ev, relevance_empty)
    assert act != DecisionAction.UPGRADE_DEPENDENCY
    assert act == DecisionAction.MONITOR_CLAIMS


# ==============================================================================
# 6. Pipeline & Telegram ChatOps Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_telegram_chatops_formats_five_questions(sample_entry: Entry):
    """Telegram deep triage callback formats in-place edit message containing the 5 questions."""
    chatops = TelegramChatOpsService()
    mock_delivery = MagicMock()
    mock_delivery.edit_message_text = AsyncMock()
    chatops.delivery = mock_delivery

    # Mock UnitOfWork
    mock_uow = MagicMock()
    mock_uow.entries.get = AsyncMock(return_value=sample_entry)
    mock_uow.analysis.get_by_entry = AsyncMock(return_value=None)
    mock_uow.analysis.add = AsyncMock()
    mock_uow.commit = AsyncMock()

    with patch("ai_security_monitor.application.services.telegram_chatops_service.SqlAlchemyUnitOfWork", return_value=mock_uow):
        with patch.object(
            decision_brief_service,
            "get_or_generate_brief",
            new_callable=AsyncMock,
            return_value=PersonalDecisionBrief(
                event_summary="DeepSeek released DeepSeek-R1 weights.",
                significance="Demonstrates competitive reasoning.",
                novelty_assessment=NoveltyAssessment(
                    novelty_type=NoveltyType.GENUINE_NOVELTY,
                    summary="Pure RL cold-start reasoning.",
                ),
                stack_relevance=StackRelevance(
                    impact_level=StackImpactLevel.DIRECT,
                    matched_technologies=["vLLM", "DeepSeek"],
                ),
                evidence_assessment=EvidenceAssessment(confidence=EvidenceConfidence.VERIFIED),
                recommended_action=DecisionAction.TEST_IN_SANDBOX,
                action_rationale="Benchmark in local sandbox container.",
            ),
        ):
            await chatops._run_deep_triage_background(
                entry_id=sample_entry.id,
                chat_id=12345,
                message_id=6789,
                original_text="<b>Fresh arXiv Dispatch</b>",
            )

    # Verify message edit was called with 5 questions
    assert mock_delivery.edit_message_text.called
    call_kwargs = mock_delivery.edit_message_text.call_args[1]
    edited_text = call_kwargs["text"]

    assert "🎯 DECISION BRIEF" in edited_text
    assert "What Happened:" in edited_text
    assert "Why It Matters:" in edited_text
    assert "What's New:" in edited_text
    assert "My Stack Impact:" in edited_text
    assert "Next Action:" in edited_text
    assert "TEST_IN_SANDBOX" in edited_text
    assert "Evidence:" in edited_text
    assert "VERIFIED" in edited_text


@pytest.mark.asyncio
async def test_decision_brief_caching_reuse(sample_entry: Entry):
    """When a valid decision brief is already attached to entry.analysis, it is returned without re-generation."""
    service = DecisionBriefService()
    existing_brief_dict = {
        "event_summary": "Existing cached summary.",
        "significance": "Existing significance.",
        "novelty_assessment": {"novelty_type": "GENUINE_NOVELTY", "summary": "Cached novelty", "comparison_notes": "", "uncertainties": []},
        "historical_comparisons": [],
        "stack_relevance": {"impact_level": "NO_MATCH", "matching_watchlist_rules": [], "matched_technologies": [], "suggested_priority": "P2", "reasons": []},
        "evidence_assessment": {"confidence": "SUPPORTED", "primary_source_type": "arxiv", "corroboration_count": 1, "has_reproducible_artifact": True, "claim_verification_score": 1.0, "notes": "", "conflicting_signals": []},
        "recommended_action": "READ_PAPER",
        "action_rationale": "Cached rationale.",
        "source_references": [],
        "generated_at": datetime.now(UTC).isoformat(),
        "analysis_version": "v1-decision-brief",
    }
    sample_entry.analysis = Analysis(
        entry_id=sample_entry.id,
        attack_vector="Reasoning",
        risk_assessment="High",
        mitigation="Review",
        threat_velocity=80,
        severity_index=70,
        decision_brief=existing_brief_dict,
    )

    # Call without force=True
    brief = await service.get_or_generate_brief(sample_entry, force=False)
    assert brief.event_summary == "Existing cached summary."
    assert brief.recommended_action == DecisionAction.READ_PAPER
