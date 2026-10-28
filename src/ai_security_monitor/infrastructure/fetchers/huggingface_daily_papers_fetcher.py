"""
Hugging Face Daily Papers Fetcher.

Tracks top curated research breakthroughs and preprints from the Hugging Face
Daily Papers API (https://huggingface.co/api/daily_papers). Captures community upvotes,
abstracts, author discussions, and direct arXiv paper links with strict age filtering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)


class HuggingFaceDailyPapersFetcher(BaseFetcher):
    """Fetcher for Hugging Face community-curated Daily Papers."""

    BASE_URL = "https://huggingface.co/api/daily_papers"
    MIRROR_URL = "https://hf-mirror.com/api/daily_papers"

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout=timeout or 30, max_retries=max_retries)

    @property
    def fetcher_type(self) -> str:
        return "huggingface_daily_papers"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch papers from Hugging Face Daily Papers API with mirror fallback."""
        limit = min(int((self.source.config or {}).get("limit", 25)), 50)
        params: dict[str, Any] = {"limit": limit}

        headers = {
            "User-Agent": settings.fetch.user_agent,
            "Accept": "application/json",
        }

        urls_to_try = [self.BASE_URL, self.MIRROR_URL]
        raw_papers: list[dict[str, Any]] = []

        for target_url in urls_to_try:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout or 25.0,
                    headers=headers,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(target_url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list):
                            raw_papers = data
                            break
                        elif isinstance(data, dict) and "papers" in data:
                            raw_papers = data["papers"]
                            break
            except Exception as e:
                logger.debug(
                    f"Hugging Face daily papers request to {target_url} failed: {e}"
                )
                continue

        return raw_papers

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw Hugging Face paper record into normalized Entry."""
        # Structure may be {"paper": {...}} or top-level paper object
        paper = raw.get("paper", raw)
        paper_id = paper.get("id") or raw.get("id")
        title = paper.get("title") or raw.get("title")
        if not title or not paper_id:
            raise ValueError("Missing title or paper_id in Hugging Face daily paper")

        summary = paper.get("summary") or raw.get("summary") or ""
        # Truncate summary cleanly
        if len(summary) > 800:
            summary = summary[:797] + "..."

        url = f"https://huggingface.co/papers/{paper_id}"

        # Parse publication date
        pub_str = paper.get("publishedAt") or raw.get("publishedAt")
        published_at = datetime.now(UTC)
        if pub_str:
            try:
                dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                published_at = dt.astimezone(UTC)
            except Exception:
                pass

        # Ingestion Freshness Guard: Max 14 days old
        max_age_days = getattr(settings.database, "max_ingest_age_days", 14)
        age_days = (datetime.now(UTC) - published_at).total_seconds() / 86400
        if age_days > max_age_days:
            raise ValueError(
                f"Discarding stale research paper '{title}' (published {age_days:.1f}d ago > {max_age_days}d)"
            )

        # Authors and upvotes
        # Authors and upvotes
        authors_data = paper.get("authors") or []
        authors: list[str] = []
        for a in authors_data:
            if isinstance(a, dict) and a.get("name"):
                authors.append(str(a["name"]))
            elif isinstance(a, str) and a.strip():
                authors.append(a.strip())
        authors = authors[:5]

        upvotes = paper.get("upvotes") or raw.get("upvotes") or 0

        tags = ["ai_research", "arxiv", "huggingface", "paper"]
        for a_name in authors[:3]:
            tags.append(a_name.lower().replace(" ", "_"))

        content_hash = str(
            ContentHash.from_content("huggingface_daily_papers", paper_id, url)
        )

        metadata = {
            "arxiv_id": paper_id,
            "authors": authors,
            "upvotes": upvotes,
            "source_platform": "huggingface_daily_papers",
            "arxiv_url": f"https://arxiv.org/abs/{paper_id}",
            "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
            "region": (self.source.config or {}).get("region", "global"),
            "is_triaged": True,
        }

        return Entry(
            source_id=self.source.id,
            title=title,
            url=url,
            content_hash=content_hash,
            summary=summary,
            published_at=published_at,
            category=Category.AI_RESEARCH,
            tags=tags,
            metadata=metadata,
        )


fetcher_registry.register(
    SourceType.HUGGINGFACE_DAILY_PAPERS
    if hasattr(SourceType, "HUGGINGFACE_DAILY_PAPERS")
    else "huggingface_daily_papers",  # type: ignore[arg-type]
    HuggingFaceDailyPapersFetcher,
)
