"""
Hugging Face Chinese Frontier AI Labs Fetcher.

Directly tracks open-weight model releases, weights, and inference checkpoints
from top Chinese AI research laboratories:
- DeepSeek AI (deepseek-ai)
- Alibaba Cloud Qwen (Qwen)
- Shanghai AI Lab (internlm)
- Tsinghua / Zhipu AI (THUDM)
- 01.AI (01-ai)
- Baichuan AI (baichuan-inc)
- Moonshot AI / Kimi (MoonshotAI)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, Source
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)


class HuggingFaceChinaFetcher(BaseFetcher):
    """Fetcher for Hugging Face model repositories authored by Chinese AI labs."""

    BASE_URL = "https://huggingface.co/api/models"
    DEFAULT_AUTHORS: list[str] = [
        "deepseek-ai",
        "Qwen",
        "internlm",
        "zai-org",
        "THUDM",
        "moonshotai",
        "MiniMaxAI",
        "stepfun-ai",
        "01-ai",
        "baichuan-inc",
        "ByteDance-Seed",
        "Alibaba-NLP",
    ]

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout=timeout or 30, max_retries=max_retries)

    @property
    def fetcher_type(self) -> str:
        return "huggingface_china"

    @staticmethod
    def _is_derivative_or_quantization(model_id: str) -> bool:
        """Detect if model repository is a quantization/adapter/format derivative."""
        low = model_id.lower()
        quant_suffixes = (
            "-gguf",
            "-awq",
            "-gptq",
            "-fp8",
            "-int4",
            "-int8",
            "-nf4",
            "-bnb-4bit",
            "-bnb-8bit",
            "-exl2",
            "-mlx",
            "-onnx",
            "-openvino",
            "-diffusers",
        )
        return any(
            low.endswith(s) or f"{s}-" in low or f"{s}." in low for s in quant_suffixes
        )

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch models for target Chinese authors from Hugging Face public Hub API."""
        cfg = self.source.config or {}
        configured_author = cfg.get("author")
        configured_authors = cfg.get("authors")

        if configured_author:
            authors = [configured_author]
        elif configured_authors and isinstance(configured_authors, list):
            authors = configured_authors
        else:
            authors = self.DEFAULT_AUTHORS

        limit_per_author = min(int(cfg.get("limit_per_author", 5)), 15)
        filter_quantizations = bool(cfg.get("filter_quantizations", True))

        headers = {
            "User-Agent": settings.fetch.user_agent,
            "Accept": "application/json",
        }

        all_models: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0,
            headers=headers,
            follow_redirects=True,
        ) as client:
            for author in authors:
                params: dict[str, Any] = {
                    "author": author,
                    "sort": "createdAt",
                    "direction": -1,
                    "limit": limit_per_author,
                }
                try:
                    resp = await client.get(self.BASE_URL, params=params)
                    if resp.status_code == 200:
                        items = resp.json()
                        if isinstance(items, list):
                            for it in items:
                                m_id = it.get("id") or it.get("modelId") or ""
                                if (
                                    filter_quantizations
                                    and self._is_derivative_or_quantization(m_id)
                                ):
                                    continue
                                it["_tracked_author"] = author
                                all_models.append(it)
                except Exception as e:
                    logger.debug(
                        f"Failed to fetch models for Chinese lab {author}: {e}"
                    )
                    continue

        return all_models

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse Hugging Face model entry into domain Entry entity."""
        model_id = raw.get("id") or raw.get("modelId") or "unknown/model"
        author = raw.get("_tracked_author") or (
            model_id.split("/")[0] if "/" in model_id else "China-Lab"
        )

        def _to_int(val: Any) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        downloads = _to_int(raw.get("downloads"))
        likes = _to_int(raw.get("likes"))
        pipeline_tag = raw.get("pipeline_tag") or "foundation-model"
        tags = raw.get("tags", [])

        # Extract license from tags (e.g. "license:mit", "license:apache-2.0")
        license_str = "open-weight"
        for tag in tags:
            if tag.startswith("license:"):
                license_str = tag.split(":", 1)[1]
                break

        url = f"https://huggingface.co/{model_id}"
        title = f"[{author}] {model_id} ({pipeline_tag.replace('-', ' ').title()})"

        published_at = datetime.now(UTC)
        created_at_str = raw.get("createdAt")
        if created_at_str:
            try:
                published_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )
            except Exception:
                pass

        content_lines = [
            f"**Chinese Frontier Lab Foundation Model Release**: `{model_id}`",
            f"- **Author / Organization**: {author}",
            f"- **Task Architecture**: `{pipeline_tag}`",
            f"- **License**: `{license_str}`",
            f"- **Momentum**: {likes:,} likes | {downloads:,} monthly downloads",
            f"- **Hugging Face Hub URL**: {url}",
        ]
        content = "\n".join(content_lines)
        summary = f"{model_id} released by {author} for {pipeline_tag}. Licensed under {license_str} with {likes:,} likes."

        metadata = {
            "region": "china",
            "country": "CN",
            "theatre": "china",
            "author": author,
            "model_id": model_id,
            "pipeline_tag": pipeline_tag,
            "license": license_str,
            "likes": likes,
            "downloads": downloads,
            "platform": "huggingface",
            "content": content,
            "original_title": model_id,
            "original_summary": summary,
        }

        category = (
            self.source.category
            if self.source and self.source.category
            else Category.AI_MODELS
        )
        content_hash = ContentHash.from_content(
            "huggingface_china", model_id.lower().strip(), url.lower().strip()
        )

        from uuid import uuid4

        return Entry(
            source_id=self.source.id if self.source and self.source.id else uuid4(),
            title=title,
            url=url,
            content_hash=str(content_hash),
            summary=summary,
            published_at=published_at,
            category=category,
            tags=tags or ["huggingface", "chinese-lab", "open-model"],
            metadata=metadata,
        )


# Register in global fetcher registry
fetcher_registry.register("huggingface_china", HuggingFaceChinaFetcher)
