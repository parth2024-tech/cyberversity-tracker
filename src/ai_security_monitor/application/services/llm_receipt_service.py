"""
Service for idempotent LLM inference receipts and retry capping.
Ensures zero repeat spend on identical inputs and halts poison entries after retry threshold.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry, LLMReceipt
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)


def compute_receipt_logical_key(
    entry_id: str | UUID,
    content_hash: str,
    provider: str,
    model: str,
    prompt_version: str | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Compute stable, collision-resistant logical key for an LLM execution attempt.

    Changing prompt_version deliberately invalidates receipts across all models.
    """
    version: str = str(
        prompt_version or getattr(settings.analyzer, "prompt_version", "v1.0") or "v1.0"
    )
    opts_str = json.dumps(options or {}, sort_keys=True)
    payload = f"{str(entry_id).strip()}:{content_hash.strip()}:{provider.strip()}:{model.strip()}:{version.strip()}:{opts_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMReceiptService:
    """High-level service orchestrating idempotent receipts and retry guards."""

    def __init__(self, uow_factory: Any | None = None):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())

    async def get_receipt(self, logical_key: str) -> LLMReceipt | None:
        """Lookup an existing receipt by logical key."""
        async with self._uow_factory() as uow:
            return await uow.receipts.get_by_key(logical_key)

    async def check_or_record_attempt(
        self,
        entry: Entry,
        provider: str,
        model: str,
        prompt_version: str | None = None,
        max_attempts: int | None = None,
    ) -> tuple[str, LLMReceipt, bool]:
        """Check receipt status and record execution attempt if eligible.

        Returns:
            (logical_key, receipt, should_call_llm)
        """
        version: str = str(
            prompt_version
            or getattr(settings.analyzer, "prompt_version", "v1.0")
            or "v1.0"
        )
        max_retries: int = int(
            max_attempts or getattr(settings.analyzer, "receipt_max_retries", 3) or 3
        )
        logical_key = compute_receipt_logical_key(
            entry_id=entry.id,
            content_hash=entry.content_hash,
            provider=provider,
            model=model,
            prompt_version=version,
        )

        async with self._uow_factory() as uow:
            receipt, should_execute = await uow.receipts.record_attempt(
                logical_key=logical_key,
                provider=provider,
                model=model,
                prompt_version=version,
                entry_id=entry.id,
                max_attempts=max_retries,
            )
            await uow.commit()

        return logical_key, receipt, should_execute

    async def record_success(
        self,
        logical_key: str,
        response_json: dict[str, Any],
        execution_tier: str | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> LLMReceipt:
        """Record successful execution response for instant future reuse with tier and cache stats."""
        async with self._uow_factory() as uow:
            receipt = await uow.receipts.record_success(
                logical_key=logical_key,
                response_json=response_json,
                execution_tier=execution_tier,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
            )
            await uow.commit()
            return receipt

    async def get_cost_savings_telemetry(self) -> dict[str, Any]:
        """Aggregate token cache hits, SLM tier breakdown, and estimated cost avoided."""
        async with self._uow_factory() as uow:
            stats = await uow.receipts.get_tier_stats()

        # Estimated cost savings calculation:
        # Standard cloud input pricing: ~$3.00 per 1M tokens ($0.000003/token)
        # Anthropic cache read discount: 90% savings ($0.30 vs $3.00/M) -> $0.0000027 saved per token
        # Local SLM avoided cloud calls: ~400 tokens per analysis avoided @ $3.00/M -> ~$0.0012 per local call
        local_slm_calls = stats.get("local_slm_count", 0)
        cache_read_tokens = stats.get("total_cache_read_tokens", 0)

        saved_from_slm = local_slm_calls * (400 * 0.000003)
        saved_from_prompt_cache = cache_read_tokens * 0.0000027
        total_estimated_savings_usd = round(saved_from_slm + saved_from_prompt_cache, 4)

        return {
            "tier_counts": stats.get("tier_counts", {}),
            "local_slm_count": local_slm_calls,
            "cloud_cached_count": stats.get("cloud_cached_count", 0),
            "cloud_uncached_count": stats.get("cloud_uncached_count", 0),
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": stats.get("total_cache_creation_tokens", 0),
            "estimated_dollars_saved": total_estimated_savings_usd,
        }

    async def record_failure(self, logical_key: str, error_message: str) -> LLMReceipt:
        """Record execution failure, incrementing failure count against retry threshold."""
        async with self._uow_factory() as uow:
            receipt = await uow.receipts.record_failure(logical_key, error_message)
            await uow.commit()
            return receipt

    async def is_poison_entry(self, entry: Entry, provider: str, model: str) -> bool:
        """Check if an entry has exhausted max retries and is classified as poisoned."""
        logical_key = compute_receipt_logical_key(
            entry_id=entry.id,
            content_hash=entry.content_hash,
            provider=provider,
            model=model,
        )
        receipt = await self.get_receipt(logical_key)
        if receipt and receipt.status == "failed" and not receipt.is_retryable:
            return True
        return False
