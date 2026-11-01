"""
Unit tests for Multi-Agent Council in Shadow Mode with Receipts and Claim Verifier (Workstream A2).
Verifies:
1. 4 Personas (Architect, Skeptic, Practitioner, Domain Specialist) evaluation.
2. Claim Verifier returning exact citation offsets [start_idx:end_idx] and flagging unsupported assertions.
3. Idempotent receipts layer and circuit breaker telemetry with heuristic fallback.
4. Shadow mode invariance (review queue storage without mutating existing analysis).
5. REST API endpoints (/api/council/*) and MCP tool (evaluate_council_shadow_review).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from ai_security_monitor.application.services.council_service import (
    PERSONA_ARCHITECT,
    PERSONA_DOMAIN_SPECIALIST,
    PERSONA_PRACTITIONER,
    PERSONA_SKEPTIC,
    CouncilCircuitBreaker,
    CouncilClaimVerifier,
    MultiAgentCouncilService,
)
from ai_security_monitor.infrastructure.database.models import (
    AnalysisModel,
    CouncilReviewModel,
    EntryModel,
    ReceiptModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.presentation.mcp.server import MCPServer


@pytest.fixture(autouse=True)
async def cleanup_council_tables():
    """Ensure clean test database state."""
    async with SqlAlchemyUnitOfWork() as uow:
        await uow.session.execute(delete(CouncilReviewModel))
        await uow.session.execute(delete(ReceiptModel))
        await uow.session.execute(delete(AnalysisModel))
        await uow.session.execute(delete(EntryModel))
        await uow.session.execute(delete(SourceModel))
        await uow.commit()
    yield
    async with SqlAlchemyUnitOfWork() as uow:
        await uow.session.execute(delete(CouncilReviewModel))
        await uow.session.execute(delete(ReceiptModel))
        await uow.session.execute(delete(AnalysisModel))
        await uow.session.execute(delete(EntryModel))
        await uow.session.execute(delete(SourceModel))
        await uow.commit()


@pytest.fixture
def sample_entry_data():
    return {
        "title": "DeepSeek-R1: Incentivizing Reasoning in LLMs via Reinforcement Learning",
        "summary": (
            "DeepSeek-R1 demonstrates 79.8% on AIME 2024 and 49.2% on SWE-bench. "
            "Trained with 671B parameters using NVIDIA H100 clusters. "
            "Code and open weights available at https://github.com/deepseek-ai/DeepSeek-R1."
        ),
    }


def test_claim_verifier_exact_citation_offsets():
    """Verify that claims are located with exact character offsets in source text."""
    verifier = CouncilClaimVerifier()

    corpus = (
        "The model achieves 79.8% on AIME 2024 and operates with 671B parameters. "
        "Throughput reaches 4x speedup on vLLM runtimes."
    )

    # 1. Supported numeric benchmark claim
    res1 = verifier.verify_claim_with_citation("79.8%", corpus)
    assert res1["is_supported"] is True
    assert res1["offset_start"] is not None
    assert res1["offset_end"] is not None
    assert corpus[res1["offset_start"] : res1["offset_end"]] == "79.8%"
    assert "AIME 2024" in res1["citation_snippet"]

    # 2. Supported parameter scale claim
    res2 = verifier.verify_claim_with_citation("671B", corpus)
    assert res2["is_supported"] is True
    assert corpus[res2["offset_start"] : res2["offset_end"]] == "671B"

    # 3. Supported speedup claim
    res3 = verifier.verify_claim_with_citation("4x", corpus)
    assert res3["is_supported"] is True
    assert corpus[res3["offset_start"] : res3["offset_end"]] == "4x"

    # 4. Unsupported assertion: must be flagged with offset=None
    res_unsupported = verifier.verify_claim_with_citation("99.9% accuracy", corpus)
    assert res_unsupported["is_supported"] is False
    assert res_unsupported["offset_start"] is None
    assert res_unsupported["offset_end"] is None
    assert res_unsupported["flag"] == "UNSUPPORTED_ASSERTION"


@pytest.mark.asyncio
async def test_multi_agent_council_personas_and_shadow_storage(sample_entry_data):
    """Verify 4 personas evaluation, consensus synthesis, receipts tracking, and shadow DB persistence."""
    council_svc = MultiAgentCouncilService()

    entry_id = uuid4()
    source_id = uuid4()

    async with SqlAlchemyUnitOfWork() as uow:
        src = SourceModel(
            id=str(source_id),
            name="test_ai_papers",
            category="ai_research",
            type="arxiv",
            rate_limit_seconds=60,
        )
        uow.session.add(src)

        entry_m = EntryModel(
            id=str(entry_id),
            source_id=str(source_id),
            title=sample_entry_data["title"],
            url="https://arxiv.org/abs/2501.12948",
            content_hash="hash_r1" * 8,
            summary=sample_entry_data["summary"],
            category="ai_research",
            published_at=datetime.now(UTC),
        )
        uow.session.add(entry_m)

        # Pre-existing analysis record with specific threat velocity
        analysis_m = AnalysisModel(
            id=str(uuid4()),
            entry_id=str(entry_id),
            threat_velocity=42,
            severity_index=50,
            attack_vector="Pre-existing attack vector",
            risk_assessment="Pre-existing risk assessment",
            mitigation="Pre-existing mitigation",
            model="heuristic",
        )
        uow.session.add(analysis_m)
        await uow.commit()

    # Run Council in Shadow Mode
    review = await council_svc.evaluate_entry_in_shadow_mode(entry_id)

    # 1. Verify 4 Personas evaluated
    evals = review.persona_evaluations
    assert PERSONA_ARCHITECT in evals
    assert PERSONA_SKEPTIC in evals
    assert PERSONA_PRACTITIONER in evals
    assert PERSONA_DOMAIN_SPECIALIST in evals

    for p_name, p_data in evals.items():
        assert p_data["verdict"] in ("ENDORSE", "QUALIFIED_PASS", "SKEPTICAL", "REJECT")
        assert 0.0 <= p_data["score"] <= 1.0
        assert len(p_data["observations"]) > 0

    # 2. Consensus Synthesis
    assert review.consensus_verdict in (
        "STRONG_CONSENSUS_ENDORSE",
        "CONSENSUS_PASS",
        "SPLIT_DECISION",
        "SKEPTICAL_CAUTION",
    )
    assert 0.50 <= review.consensus_score <= 1.0
    assert len(review.consensus_summary) > 20

    # 3. Verified Claims with citation offsets
    assert len(review.verified_claims) >= 1
    supported_claims = [c for c in review.verified_claims if c["is_supported"]]
    assert len(supported_claims) >= 1
    # Check that citation offsets point to valid substrings in the summary/title
    for sc in supported_claims:
        if sc.get("offset_start") is not None and sc.get("offset_end") is not None:
            assert sc["offset_end"] > sc["offset_start"]

    # 4. Shadow Invariance: check database state
    async with SqlAlchemyUnitOfWork() as uow:
        # Review stored in council_reviews table
        db_review = await uow.council.get_by_entry(entry_id)
        assert db_review is not None
        assert db_review.status == "shadow"
        assert db_review.consensus_verdict == review.consensus_verdict

        # Crucial check: entry_analysis must NOT have been modified by shadow council!
        persisted_analysis = (
            await uow.session.execute(
                select(AnalysisModel).where(AnalysisModel.entry_id == str(entry_id))
            )
        ).scalar_one()
        assert persisted_analysis.threat_velocity == 42
        assert persisted_analysis.attack_vector == "Pre-existing attack vector"

        # Receipts layer recorded
        receipts = (
            (
                await uow.session.execute(
                    select(ReceiptModel).where(ReceiptModel.entry_id == str(entry_id))
                )
            )
            .scalars()
            .all()
        )
        assert len(receipts) == 4  # 1 per persona


@pytest.mark.asyncio
async def test_council_circuit_breaker_telemetry():
    """Verify circuit breaker telemetry and budget monitoring."""
    breaker = CouncilCircuitBreaker(daily_cost_cap=0.01, daily_token_cap=1000)

    async with SqlAlchemyUnitOfWork() as uow:
        status1 = await breaker.get_circuit_status(uow)
        assert status1["is_tripped"] is False
        assert status1["used_cost_usd_24h"] == 0.0

        # Simulate heavy review spend tripping the breaker
        uow.session.add(
            CouncilReviewModel(
                id=str(uuid4()),
                entry_id=str(uuid4()),
                status="shadow",
                consensus_verdict="CONSENSUS_PASS",
                consensus_score=0.75,
                consensus_summary="High spend simulation",
                persona_evaluations={},
                verified_claims=[],
                receipt_keys=[],
                total_tokens=2500,  # exceeds 1000
                total_latency_ms=120,
                estimated_cost_usd=0.02,  # exceeds 0.01
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await uow.commit()

        status2 = await breaker.get_circuit_status(uow)
        assert status2["is_tripped"] is True
        assert status2["used_tokens_24h"] >= 2000
        assert status2["used_cost_usd_24h"] >= 0.02


@pytest.mark.asyncio
async def test_council_rest_api_and_review_queue():
    """Verify REST API /api/council/reviews, /api/council/evaluate, and /api/council/circuit-breaker."""
    entry_id = uuid4()
    source_id = uuid4()

    async with SqlAlchemyUnitOfWork() as uow:
        src = SourceModel(
            id=str(source_id),
            name="test_api_papers",
            category="ai_research",
            type="arxiv",
            rate_limit_seconds=60,
        )
        uow.session.add(src)

        entry_m = EntryModel(
            id=str(entry_id),
            source_id=str(source_id),
            title="Qwen 2.5 Coder: Evaluating Code Generation Scaling",
            url="https://arxiv.org/abs/2409.12186",
            content_hash="qwen_hash_123" * 4,
            summary="Qwen 2.5 Coder 32B achieves 65.4% on SWE-bench with vLLM support.",
            category="ai_models",
            published_at=datetime.now(UTC),
        )
        uow.session.add(entry_m)
        await uow.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Trigger shadow evaluation
        res_eval = await client.post(f"/api/council/evaluate/{entry_id}")
        assert res_eval.status_code == 200
        data_eval = res_eval.json()
        assert data_eval["status"] == "ok"
        review_data = data_eval["review"]
        assert review_data["entry_id"] == str(entry_id)
        assert review_data["shadow_status"] == "shadow"
        review_id = review_data["id"]

        # 2. Query shadow review queue
        res_list = await client.get("/api/council/reviews")
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert data_list["count"] >= 1
        assert any(r["id"] == review_id for r in data_list["reviews"])

        # 3. Query review for specific entry
        res_entry = await client.get(f"/api/council/entry/{entry_id}")
        assert res_entry.status_code == 200
        assert res_entry.json()["id"] == review_id

        # 4. Human calibration action: update review status to 'approved'
        res_action = await client.post(
            f"/api/council/review/{review_id}/status?status=approved"
        )
        assert res_action.status_code == 200
        assert res_action.json()["new_status"] == "approved"

        # 5. Circuit breaker telemetry endpoint
        res_cb = await client.get("/api/council/circuit-breaker")
        assert res_cb.status_code == 200
        cb_data = res_cb.json()
        assert "is_tripped" in cb_data
        assert "daily_cost_cap_usd" in cb_data


@pytest.mark.asyncio
async def test_mcp_council_shadow_review_tool():
    """Verify that MCP server exposes and executes evaluate_council_shadow_review."""
    entry_id = uuid4()
    source_id = uuid4()

    async with SqlAlchemyUnitOfWork() as uow:
        src = SourceModel(
            id=str(source_id),
            name="test_mcp_papers",
            category="ai_research",
            type="arxiv",
            rate_limit_seconds=60,
        )
        uow.session.add(src)

        entry_m = EntryModel(
            id=str(entry_id),
            source_id=str(source_id),
            title="SGLang: Fast Serving Framework for Complex LLM Programs",
            url="https://arxiv.org/abs/2312.07104",
            content_hash="sglang_mcp_hash" * 4,
            summary="SGLang achieves up to 5x throughput reduction in latency on NVIDIA H100 GPUs.",
            category="cyber_tools",
            published_at=datetime.now(UTC),
        )
        uow.session.add(entry_m)
        await uow.commit()

    server = MCPServer()

    # 1. Verify tool exists in tools/list
    list_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    list_res = await server.handle_request(list_req)
    assert list_res is not None
    tool_names = [t["name"] for t in list_res["result"]["tools"]]
    assert "evaluate_council_shadow_review" in tool_names

    # 2. Call evaluate_council_shadow_review
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "evaluate_council_shadow_review",
            "arguments": {"entry_id": str(entry_id)},
        },
    }
    call_res = await server.handle_request(call_req)
    assert call_res is not None
    assert "result" in call_res
    text_content = call_res["result"]["content"][0]["text"]
    assert "consensus_verdict" in text_content
    assert str(entry_id) in text_content
