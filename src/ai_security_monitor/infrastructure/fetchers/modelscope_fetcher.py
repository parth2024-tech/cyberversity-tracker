"""
ModelScope Open Source AI Hub Models & Repositories Fetcher.

Fetches newly released and high-momentum open-source models directly
from the Alibaba ModelScope Hub OpenAPI (modelscope.cn/openapi/v1/models).
Extracts deterministic model specifications (parameter counts, licenses, tasks)
without authentication requirements.
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


class ModelScopeFetcher(BaseFetcher):
    """Fetcher for open-source foundation models from Alibaba ModelScope Hub."""

    BASE_URL = "https://modelscope.cn/openapi/v1/models"

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout=timeout or 30, max_retries=max_retries)

    @property
    def fetcher_type(self) -> str:
        return "modelscope"

    @staticmethod
    def _format_param_count(param_val: Any) -> str:
        """Format raw parameter count integer into readable string (e.g. 7.2B, 70B)."""
        if not param_val:
            return "N/A"
        try:
            num = int(param_val)
            if num >= 1_000_000_000:
                val = num / 1_000_000_000
                return f"{val:.1f}B".replace(".0B", "B")
            elif num >= 1_000_000:
                val = num / 1_000_000
                return f"{val:.1f}M".replace(".0M", "M")
            elif num >= 1_000:
                val = num / 1_000
                return f"{val:.1f}K".replace(".0K", "K")
            return str(num)
        except (ValueError, TypeError):
            return str(param_val)

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch models from ModelScope OpenAPI."""
        cfg = self.source.config or {}
        search_query = cfg.get("search", "")
        page_size = min(int(cfg.get("limit", 15)), 25)
        sort_by = cfg.get("sort", "last_modified")

        params: dict[str, Any] = {
            "page_size": page_size,
        }
        if search_query:
            params["search"] = search_query
        if sort_by:
            params["sort"] = sort_by

        headers = {
            "User-Agent": settings.fetch.user_agent,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0,
            headers=headers,
            follow_redirects=True,
        ) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        models_list = data.get("data", {}).get("models", [])
        if not models_list and isinstance(data.get("models"), list):
            models_list = data["models"]

        return models_list

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse ModelScope model entry into domain Entry entity."""
        model_id = raw.get("id") or raw.get("name") or "unknown/model"
        display_name = raw.get("display_name") or model_id
        description = raw.get("description", "").strip()

        def _to_int(val: Any) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        downloads = _to_int(raw.get("downloads"))
        likes = _to_int(raw.get("likes"))
        license_name = raw.get("license") or "open"
        tasks = raw.get("tasks", [])
        task_str = ", ".join(tasks) if tasks else "foundation-model"
        raw_params = raw.get("params")
        param_str = self._format_param_count(raw_params)
        tags = raw.get("tags", [])

        url = f"https://modelscope.cn/models/{model_id}/summary"
        title = f"[ModelScope] {display_name} ({param_str} Params) - {task_str}"

        # Parse publication date
        published_at = datetime.now(UTC)
        created_at_str = raw.get("created_at") or raw.get("last_modified")
        if created_at_str:
            try:
                published_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )
            except Exception:
                pass

        # Build structured markdown body
        formatted_param_detail = (
            f"- **Parameter Count**: {param_str} ({raw_params:,} parameters)"
            if isinstance(raw_params, int) and raw_params > 0
            else f"- **Parameter Count**: {param_str}"
        )
        content_lines = [
            f"**ModelScope Open-Source Model Release**: `{model_id}`",
            f"- **Display Name**: {display_name}",
            formatted_param_detail,
            f"- **Tasks / Capabilities**: {task_str}",
            f"- **License**: `{license_name}`",
            f"- **Community Signals**: {likes:,} likes | {downloads:,} downloads",
            f"- **Model Hub URL**: {url}",
        ]
        if description:
            content_lines.append(f"\n**Overview**:\n{description}")

        content = "\n".join(content_lines)
        summary = f"{display_name} ({param_str}) published on ModelScope for {task_str}. Licensed under {license_name} with {downloads:,} downloads."

        metadata = {
            "region": "china",
            "country": "CN",
            "theatre": "china",
            "model_id": model_id,
            "platform": "modelscope",
            "parameters": param_str,
            "license": license_name,
            "tasks": tasks,
            "likes": likes,
            "downloads": downloads,
            "content": content,
            "original_title": display_name,
            "original_summary": description or summary,
        }

        category = (
            self.source.category
            if self.source and self.source.category
            else Category.AI_TECH
        )
        content_hash = ContentHash.from_content(
            "modelscope", model_id.lower().strip(), url.lower().strip()
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
            tags=tags or ["modelscope", "open-model", "china"],
            metadata=metadata,
        )


# Register in global fetcher registry
fetcher_registry.register("modelscope", ModelScopeFetcher)
