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
        self, logical_key: str, response_json: dict[str, Any]
    ) -> LLMReceipt:
        """Record successful execution response for instant future reuse."""
        async with self._uow_factory() as uow:
            receipt = await uow.receipts.record_success(logical_key, response_json)
            await uow.commit()
            return receipt

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
