"""
Tests for Autonomous Triage Queue Push and Hold-Until-Sweep functionality.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.autonomous_triage_service import (
    AutonomousTriageService,
)
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    Source,
    SourceType,
)
from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_queue_hold_mode_keeps_items_queued(test_uow):
    """Verify that when hold_until_sweep is True, worker does not auto-consume entries."""
    service = AutonomousTriageService(uow_factory=lambda: test_uow)
    assert service._hold_until_sweep is True

    src = Source(
        id=uuid4(),
        name="Test arXiV Feed",
        category=Category.AI_RESEARCH,
        type=SourceType.ARXIV,
        url="https://arxiv.org/test",
    )
    await test_uow.sources.add(src)

    ent = Entry(
        id=uuid4(),
        source_id=src.id,
        title="DeepSeek-V3 Reasoning Breakthrough in Frontier Models",
        url="https://arxiv.org/abs/2501.99999",
        content_hash="hash_" + uuid4().hex,
        summary="Novel test-time compute scaling for frontier reasoning.",
        published_at=datetime.now(UTC),
        category=Category.AI_RESEARCH,
        tags=["deepseek", "frontier", "reasoning"],
    )
    await test_uow.entries.add(ent)
    await test_uow.commit()

    await service.start(auto_hydrate=False)
    try:
        enqueued = await service.enqueue(ent.id, priority=0)
        assert enqueued is True
        assert service.queue_size == 1

        # Wait briefly to ensure worker does NOT pop entry while in hold mode
        await asyncio.sleep(0.05)
        assert service.queue_size == 1
        status = service.get_status()
        assert status["queue_size"] == 1
        assert status["hold_until_sweep"] is True
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_push_all_queued_clears_queue_and_updates_db(test_uow):
    """Verify push_all_queued processes all items, empties the queue, and enriches entries."""
    service = AutonomousTriageService(uow_factory=lambda: test_uow)

    src = Source(
        id=uuid4(),
        name="Test Trending Feed",
        category=Category.GITHUB_TRENDING,
        type=SourceType.GITHUB_TRENDING,
        url="https://github.com/test",
    )
    await test_uow.sources.add(src)

    entry1 = Entry(
        id=uuid4(),
        source_id=src.id,
        title="vLLM: High-Throughput and Memory-Efficient LLM Serving",
        url="https://github.com/vllm/vllm",
        content_hash="hash_" + uuid4().hex,
        summary="PagedAttention runtime for open-source LLM inference.",
        published_at=datetime.now(UTC),
        category=Category.GITHUB_TRENDING,
        tags=["vllm", "inference", "runtime"],
    )
    entry2 = Entry(
        id=uuid4(),
        source_id=src.id,
        title="Qwen2.5-Coder: 32B Code Intelligence Frontier Weights",
        url="https://github.com/qwen/qwen2.5-coder",
        content_hash="hash_" + uuid4().hex,
        summary="Open weights foundation model for automated coding workflows.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["qwen", "coding", "weights"],
    )
    await test_uow.entries.add(entry1)
    await test_uow.entries.add(entry2)
    await test_uow.commit()

    await service.enqueue(entry1.id, priority=1)
    await service.enqueue(entry2.id, priority=0)
    assert service.queue_size == 2

    pushed = await service.push_all_queued()
    assert pushed == 2
    assert service.queue_size == 0

    db_e1 = await test_uow.entries.get(entry1.id)
    assert db_e1 is not None
    assert db_e1.metadata.get("is_triaged") is True
    assert db_e1.metadata.get("triaged_by") == "fast_parallel_triage"
    assert "ai_architecture" in db_e1.metadata

    analysis1 = await test_uow.analyses.get_by_entry(entry1.id)
    assert analysis1 is not None
    assert analysis1.threat_velocity >= 0


@pytest.mark.asyncio
async def test_api_triage_push_all_endpoint():
    """Test POST /api/triage/push-all returns clean response and resets queue."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_q = await client.get("/api/triage/queue")
        assert resp_q.status_code == 200
        q_data = resp_q.json()
        assert "queue_size" in q_data
        assert "hold_until_sweep" in q_data

        resp_push = await client.post("/api/triage/push-all")
        assert resp_push.status_code == 200
        push_data = resp_push.json()
        assert push_data["status"] == "success"
        assert "pushed_count" in push_data
        assert push_data["queue_size"] == 0


@pytest.mark.asyncio
async def test_api_triage_mode_endpoint():
    """Test POST /api/triage/mode toggles hold mode cleanly."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/triage/mode?hold=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hold_until_sweep"] is False

        resp2 = await client.post("/api/triage/mode?hold=true")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["hold_until_sweep"] is True


@pytest.mark.asyncio
async def test_api_fetch_sweep_includes_queued_pushed(monkeypatch):
    """Test POST /api/fetch response includes queued_pushed count."""
    from ai_security_monitor.application.services.monitor_service import MonitorService

    async def _mock_fetch_all(self):
        return {"total_sources": 1, "success": 1, "failed": 0, "total_new": 0}

    monkeypatch.setattr(MonitorService, "fetch_all", _mock_fetch_all)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/fetch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "results" in data
        assert "queued_pushed" in data
        assert isinstance(data["queued_pushed"], int)

