"""
Persistent Daily LLM Budget Service (Defect D9).

Aggregates daily LLM inference spend directly from database receipt records (`llm_receipts`),
preventing cost overruns and enforcing hard budgetary caps across restarts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.exceptions import DomainError
from ai_security_monitor.infrastructure.database.connection import (
    DatabaseManager,
    db_manager,
)
from ai_security_monitor.infrastructure.database.models import (
    LLMBudgetModel,
    ReceiptModel,
)

logger = get_logger(__name__)


class LLMBudgetExceededError(DomainError):
    """Raised when the daily LLM spend exceeds the configured budgetary limit."""

    def __init__(self, current_spend: float, budget_limit: float):
        super().__init__(
            f"Daily LLM budget exhausted: spent ${current_spend:.2f} of ${budget_limit:.2f} limit",
            code="LLM_BUDGET_EXCEEDED",
            details={"current_spend_usd": current_spend, "budget_limit_usd": budget_limit},
        )


class LLMBudgetService:
    """Service tracking and enforcing daily LLM expenditure backed by SQLite database."""

    def __init__(
        self,
        manager: DatabaseManager | None = None,
        default_daily_budget_usd: float | None = None,
    ):
        self._manager = manager or db_manager
        self._default_budget: float = float(
            default_daily_budget_usd
            if default_daily_budget_usd is not None
            else getattr(settings.analyzer, "daily_budget_usd", 5.0) or 5.0
        )

    def get_budget_limit_usd(self) -> float:
        """Get the cached daily budget limit in USD."""
        return self._default_budget

    async def get_budget_limit_usd_async(self) -> float:
        """Get the configured daily budget limit in USD from database."""
        try:
            async with self._manager.session_factory() as session:
                stmt = select(LLMBudgetModel).where(LLMBudgetModel.key == "default")
                res = await session.execute(stmt)
                model = res.scalar_one_or_none()
                if model:
                    self._default_budget = float(model.daily_budget_usd)
                    return self._default_budget
        except Exception as e:
            logger.debug("Database budget query fallback to in-memory default: %s", e)
        return self._default_budget

    async def set_budget_limit_usd(self, limit_usd: float) -> None:
        """Persist the daily LLM budget limit in the database."""
        try:
            async with self._manager.session_factory() as session:
                stmt = select(LLMBudgetModel).where(LLMBudgetModel.key == "default")
                res = await session.execute(stmt)
                model = res.scalar_one_or_none()
                if model:
                    model.daily_budget_usd = float(limit_usd)
                    model.updated_at = datetime.now(UTC)
                else:
                    model = LLMBudgetModel(
                        id=str(uuid4()),
                        key="default",
                        daily_budget_usd=float(limit_usd),
                        updated_at=datetime.now(UTC),
                    )
                    session.add(model)
                await session.commit()
                self._default_budget = float(limit_usd)
        except Exception as e:
            logger.warning("Failed to persist daily LLM budget limit to database: %s", e)
            self._default_budget = float(limit_usd)

    async def get_today_spend_usd(self) -> float:
        """Aggregate total USD spend across all LLM inference receipts since midnight UTC."""
        midnight_utc = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        try:
            async with self._manager.session_factory() as session:
                stmt = select(
                    func.coalesce(func.sum(ReceiptModel.estimated_cost_usd), 0.0)
                ).where(ReceiptModel.created_at >= midnight_utc)
                res = await session.execute(stmt)
                spend = float(res.scalar() or 0.0)
                return spend
        except Exception as e:
            logger.warning("Failed to aggregate daily LLM spend from database: %s", e)
            return 0.0

    async def is_budget_available(self, estimated_cost: float = 0.0) -> bool:
        """Check whether budget is available for an execution costing estimated_cost."""
        spend = await self.get_today_spend_usd()
        limit = await self.get_budget_limit_usd_async()
        return (spend + estimated_cost) <= limit

    async def enforce_budget(self, estimated_cost: float = 0.0) -> None:
        """Raise LLMBudgetExceededError if budget limit is exceeded."""
        spend = await self.get_today_spend_usd()
        limit = await self.get_budget_limit_usd_async()
        if (spend + estimated_cost) > limit:
            raise LLMBudgetExceededError(current_spend=spend, budget_limit=limit)


# Global singleton instance
llm_budget_service = LLMBudgetService()
