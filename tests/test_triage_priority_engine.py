"""
Unit tests for AutonomousTriageService priority queue and telemetry.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.autonomous_triage_service import (
    AutonomousTriageService,
)
from ai_security_monitor.domain.entities import Category, Entry


@pytest.mark.asyncio
async def test_triage_priority_scoring():
    """Verify calculate_priority assigns P0 to frontier models and P1 to developer tools."""
    service = AutonomousTriageService()

    entry_p0 = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1 Open-Weights Release and Technical Report",
        url="https://github.com/deepseek-ai/DeepSeek-R1",
        content_hash="hash1",
        summary="A new reasoning model matching o1 performance.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["reasoning", "llm"],
    )

    entry_p1 = Entry(
        source_id=uuid4(),
        title="vLLM: High-Throughput and Memory-Efficient Inference Engine for LLMs",
        url="https://github.com/vllm-project/vllm",
        content_hash="hash2",
        summary="Inference runtime for production LLM serving.",
        published_at=datetime.now(UTC),
        category=Category.CYBER_TOOLS,
        tags=["inference", "gpu"],
    )

    entry_p2 = Entry(
        source_id=uuid4(),
        title="European AI Regulation Update",
        url="https://example.com/eu-ai",
        content_hash="hash3",
        summary="General policy updates.",
        published_at=datetime.now(UTC),
        category=Category.AI_TECH,
        tags=["policy"],
    )

    assert service.calculate_priority(entry_p0) == 0  # Frontier model
    assert service.calculate_priority(entry_p1) == 1  # Tool / runtime
    assert service.calculate_priority(entry_p2) == 2  # General news


@pytest.mark.asyncio
async def test_triage_queue_enqueue_and_clear():
    """Verify priority queue enqueues, reports telemetry, and flushes cleanly."""
    service = AutonomousTriageService()

    id1 = uuid4()
    id2 = uuid4()

    assert await service.enqueue(id1, priority=1) is True
    assert await service.enqueue(id1, priority=1) is False  # Deduplicated
    assert await service.enqueue(id2, priority=0) is True

    assert service.queue_size == 2
    status = service.get_status()
    assert status["queue_size"] == 2
    assert status["total_enqueued"] == 2

    # Verify queue ordering (P0 should pop first before P1)
    p_top, _, e_top = await service._queue.get()
    assert p_top == 0
    assert e_top == id2

    # Clear queue
    cleared = service.clear_queue()
    assert cleared == 1
    assert service.queue_size == 0


@pytest.mark.asyncio
async def test_brutal_reverse_order_heap_invariants_and_concurrency():
    """Brutally verify PriorityQueue heap ordering under adversarial reverse insertion and concurrency."""
    service = AutonomousTriageService()

    # Interleave priorities: insert P2s first, then P1s, then P0s
    p2_ids = [uuid4() for _ in range(10)]
    p1_ids = [uuid4() for _ in range(10)]
    p0_ids = [uuid4() for _ in range(10)]

    for uid in p2_ids:
        enq = await service.enqueue(uid, priority=2)
        assert enq is True
    for uid in p1_ids:
        enq = await service.enqueue(uid, priority=1)
        assert enq is True
    for uid in p0_ids:
        enq = await service.enqueue(uid, priority=0)
        assert enq is True

    # Attempt duplicate enqueues across all IDs - must all fail (return False)
    for uid in p0_ids + p1_ids + p2_ids:
        assert await service.enqueue(uid, priority=0) is False

    assert service.queue_size == 30
    assert service.get_status()["queue_size"] == 30

    # Pop all items and verify strict monotonic non-decreasing priority order
    dequeued_priorities = []
    dequeued_ids = []
    while service.queue_size > 0:
        p, _, item_id = await service._queue.get()
        dequeued_priorities.append(p)
        dequeued_ids.append(item_id)

    # Must be 10 zeros, then 10 ones, then 10 twos
    assert dequeued_priorities == [0] * 10 + [1] * 10 + [2] * 10
    assert set(dequeued_ids[:10]) == set(p0_ids)
    assert set(dequeued_ids[10:20]) == set(p1_ids)
    assert set(dequeued_ids[20:]) == set(p2_ids)

    # Concurrency test: Hammer enqueue concurrently with overlapping UUIDs
    shared_id = uuid4()
    results = await asyncio.gather(
        *(service.enqueue(shared_id, priority=0) for _ in range(25))
    )
    # Exactly one should have succeeded (True), all other 24 must be False
    assert results.count(True) == 1
    assert results.count(False) == 24
    assert service.queue_size == 1
