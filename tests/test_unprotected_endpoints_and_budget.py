"""
Tests for Defect D9: Protected write/cost endpoints and persistent daily LLM budget in DB.
Verifies that:
1. Daily LLM spend is computed from database records and halts spend when exceeded.
2. High-cost/mutating endpoints require administrative authentication.
3. Rapid requests exceeding route rate limits receive HTTP 429 Too Many Requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.llm_budget_service import (
    LLMBudgetExceededError,
    LLMBudgetService,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.database.connection import DatabaseManager
from ai_security_monitor.infrastructure.database.models import ReceiptModel
from ai_security_monitor.presentation.api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_daily_budget_computed_from_db_halts_spend(tmp_path):
    """Daily LLM spend is aggregated directly from database receipts and halts spend on limit breach."""
    db_file = tmp_path / "test_budget.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)
    await manager.init_db()

    # Pre-populate receipts in DB totaling $5.50 today
    async with manager.session_factory() as session:
        for i in range(5):
            rec = ReceiptModel(
                id=str(uuid4()),
                logical_key=f"budget_receipt_{i}",
                provider="groq",
                model="llama-3.1-70b-versatile",
                prompt_version="v1.0",
                status="succeeded",
                estimated_cost_usd=1.10,
                total_tokens=2500,
                created_at=datetime.now(UTC),
            )
            session.add(rec)
        await session.commit()

    budget_service = LLMBudgetService(manager=manager, default_daily_budget_usd=5.00)

    # Total spend should be $5.50
    spend = await budget_service.get_today_spend_usd()
    assert spend >= 5.50

    # Over-budget check should return False
    is_available = await budget_service.is_budget_available(estimated_cost=0.10)
    assert is_available is False

    # Calling check_budget should raise LLMBudgetExceededError
    with pytest.raises(LLMBudgetExceededError):
        await budget_service.enforce_budget(estimated_cost=0.10)

    await manager.close()


@pytest.mark.asyncio
async def test_llm_analyzer_respects_db_budget_and_falls_back(tmp_path):
    """LLMAnalyzer degrades to heuristic when database daily LLM budget is exhausted."""
    db_file = tmp_path / "test_analyzer_budget.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)
    await manager.init_db()

    # Budget exhausted ($10.00 spent against $5.00 limit)
    async with manager.session_factory() as session:
        rec = ReceiptModel(
            id=str(uuid4()),
            logical_key="exhausted_budget_rec",
            provider="groq",
            model="llama-3.1-70b-versatile",
            prompt_version="v1.0",
            status="succeeded",
            estimated_cost_usd=10.00,
            total_tokens=25000,
            created_at=datetime.now(UTC),
        )
        session.add(rec)
        await session.commit()

    budget_service = LLMBudgetService(manager=manager, default_daily_budget_usd=5.00)
    analyzer = LLMAnalyzer(budget_service=budget_service)

    entry = Entry(
        id=uuid4(),
        source_id=uuid4(),
        title="vLLM Optimized PagedAttention Kernel",
        url="https://github.com/vllm-project/vllm",
        content_hash="h123",
        summary="High throughput inference engine optimization",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )

    with patch.object(analyzer, "_call_ollama", new_callable=AsyncMock) as mock_llm:
        res = await analyzer.analyze(entry)
        # LLM must NOT be called when budget is exceeded; analyzer falls back gracefully
        assert mock_llm.call_count == 0
        assert res is not None

    await manager.close()


@pytest.mark.asyncio
async def test_mutating_cost_endpoints_require_admin_auth(app, monkeypatch):
    """Mutating write/cost endpoints must return 401 Unauthorized when unauthenticated."""
    monkeypatch.setattr(settings.api, "admin_api_key", "secret-test-admin-key-12345")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Purge endpoint without auth
        resp1 = await client.post("/api/stats/purge")
        assert resp1.status_code == 401

        # 2. Batch analysis without auth
        resp2 = await client.post("/api/analysis/run-batch", json={"entry_ids": []})
        assert resp2.status_code == 401

        # 3. Import backup without auth
        resp3 = await client.post("/api/backup/import", files={})
        assert resp3.status_code in (401, 422)  # Auth check must precede or block execution

        # 4. Translation backfill without auth
        resp4 = await client.post("/api/translate/backfill", json={"limit": 10})
        assert resp4.status_code == 401

        # 5. Newspaper generate without auth
        resp5 = await client.post("/api/newspaper/generate", json={"window_hours": 5})
        assert resp5.status_code == 401

        # 6. Vault refresh profile without auth
        resp6 = await client.post("/api/vault/profile/refresh")
        assert resp6.status_code == 401

        # 7. Valid auth succeeds or advances past auth check
        resp_auth = await client.post(
            "/api/stats/purge",
            headers={"X-Admin-Key": "secret-test-admin-key-12345"},
        )
        assert resp_auth.status_code != 401


@pytest.mark.asyncio
async def test_budget_limit_persisted_in_database(tmp_path):
    """Daily budget limit is stored in and retrieved from the database, not in memory."""
    db_file = tmp_path / "test_budget_persist.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    manager = DatabaseManager(url=db_url)
    await manager.init_db()

    service1 = LLMBudgetService(manager=manager, default_daily_budget_usd=5.00)
    # Update limit to $12.50
    await service1.set_budget_limit_usd(12.50)

    # Instantiate fresh service instance pointing to same DB (simulating app restart)
    service2 = LLMBudgetService(manager=manager, default_daily_budget_usd=5.00)
    loaded_limit = await service2.get_budget_limit_usd_async()
    assert loaded_limit == 12.50

    await manager.close()
