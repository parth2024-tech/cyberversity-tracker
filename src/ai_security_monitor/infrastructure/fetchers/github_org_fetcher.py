"""
GitHub Organization Repositories Fetcher (Defect D5).

Polls active repositories at the organization level rather than stale single repos,
capturing recent releases, tooling updates, and model codebases directly from frontier labs:
- DeepSeek AI (deepseek-ai)
- Alibaba Cloud Qwen (QwenLM)
- Zhipu AI / Tsinghua (zai-org / THUDM)
- Moonshot AI / Kimi (MoonshotAI)
- Shanghai AI Lab (InternLM)

Guards against organization renames, respects the 14-day freshness window, and
tracks ETag validators safely.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    FetchStatus,
    Source,
)
from ai_security_monitor.domain.exceptions import FetchNotModifiedError
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    FetchResult,
    fetcher_registry,
)

logger = get_logger(__name__)


class GitHubOrgFetcher(BaseFetcher):
    """Fetcher for active GitHub repositories across an entire organization."""

    KNOWN_ORG_RENAMES: dict[str, str] = {
        "THUDM": "zai-org",
        "QwenLM": "Qwen",
    }

    def __init__(
        self, source: Source, timeout: int | None = None, max_retries: int | None = None
    ):
        super().__init__(source, timeout=timeout or 30, max_retries=max_retries)
        self.org_rename_alerts: list[str] = []

    @property
    def fetcher_type(self) -> str:
        return "github_org"

    def _get_target_org(self) -> str:
        """Extract organization name from config or URL."""
        cfg = self.source.config or {}
        if cfg.get("org"):
            return str(cfg["org"]).strip()

        # Parse from URL (e.g., https://api.github.com/orgs/deepseek-ai/repos or https://github.com/deepseek-ai)
        parsed = urlparse(self.source.url)
        parts = [p for p in parsed.path.split("/") if p]
        if "orgs" in parts:
            idx = parts.index("orgs")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        elif parts:
            return parts[0]
        return "unknown"

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch repositories from GitHub Organization API with rename alerting."""
        org = self._get_target_org()
        target_org = org

        if org in self.KNOWN_ORG_RENAMES:
            target_org = self.KNOWN_ORG_RENAMES[org]
            alert_msg = f"ALERT: GitHub Org rename detected: {org} has migrated to {target_org}"
            self.org_rename_alerts.append(alert_msg)
            logger.warning(alert_msg)

        headers: dict[str, str] = {
            "User-Agent": settings.fetch.user_agent,
            "Accept": "application/vnd.github.v3+json",
        }

        # Optional GitHub Personal Access Token to avoid unauthenticated rate limits
        token = os.environ.get("GITHUB_TOKEN") or getattr(
            settings.fetch, "github_token", None
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Safe ETag validator (Defects D3, D4)
        etag = self.source.config.get("etag")
        stored_entries_count = self.source.config.get("stored_entries_count", 0)
        if etag and stored_entries_count >= 3:
            headers["If-None-Match"] = etag

        api_url = f"https://api.github.com/orgs/{target_org}/repos"
        params: dict[str, str | int] = {
            "sort": "pushed",
            "direction": "desc",
            "per_page": min(int(self.source.config.get("limit", 15)), 30),
        }

        async with httpx.AsyncClient(
            timeout=self.timeout or 25.0,
            headers=headers,
            follow_redirects=True,
        ) as client:
            resp = await client.get(api_url, params=params)

            if resp.status_code == 304:
                raise FetchNotModifiedError(
                    f"GitHub org {target_org} unchanged (HTTP 304 Not Modified)"
                )

            # Fallback guard on 404 or empty response: check known renames
            if resp.status_code == 404 and org in self.KNOWN_ORG_RENAMES:
                target_org = self.KNOWN_ORG_RENAMES[org]
                logger.warning(
                    "ALERT: GitHub Org rename detected: %s returned 404; querying %s",
                    org,
                    target_org,
                )
                api_url = f"https://api.github.com/orgs/{target_org}/repos"
                resp = await client.get(api_url, params=params)

            if resp.status_code != 200:
                logger.warning(
                    "GitHub Org API error %s for org %s: %s",
                    resp.status_code,
                    target_org,
                    resp.text[:200],
                )
                return []

            # Store fresh ETag validator
            new_etag = resp.headers.get("etag")
            if new_etag:
                self.source.config["etag"] = new_etag

            items = resp.json()
            if not isinstance(items, list):
                return []

            # Tag items with active org
            for it in items:
                it["_active_org"] = target_org
            return items

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse GitHub repo object into domain Entry entity."""
        org = raw.get("_active_org") or self._get_target_org()
        name = raw.get("name") or "repo"
        html_url = raw.get("html_url") or f"https://github.com/{org}/{name}"
        desc = (raw.get("description") or "").strip()
        stars = raw.get("stargazers_count", 0)
        language = raw.get("language") or "Codebase"
        is_fork = bool(raw.get("fork", False))

        pushed_at_str = raw.get("pushed_at") or raw.get("updated_at")
        published_at = datetime.now(UTC)
        if pushed_at_str:
            try:
                clean_str = pushed_at_str.rstrip("Z").replace("+00:00", "")
                published_at = datetime.fromisoformat(clean_str).replace(tzinfo=UTC)
            except Exception:
                pass

        title = f"[{org}] {name}: {desc or 'Open Source AI Codebase'}"
        summary = (
            f"Active repository {name} maintained by {org} ({language}, {stars:,} stars)."
            + (f" {desc}" if desc else "")
        )

        content_hash = hashlib.sha256(
            f"{html_url}:{pushed_at_str}".encode()
        ).hexdigest()

        return Entry(
            source_id=self.source.id,
            title=title,
            url=html_url,
            content_hash=content_hash,
            summary=summary,
            published_at=published_at,
            category=self.source.category or Category.GITHUB_TRENDING,
            tags=[org.lower(), name.lower(), language.lower()],
            metadata={
                "org": org,
                "stars": stars,
                "language": language,
                "is_fork": is_fork,
                "region": self.source.config.get("region", "global"),
                "country": self.source.config.get("country", "GLOBAL"),
            },
        )

    async def fetch(self) -> FetchResult:
        """Execute fetch with 14-day freshness guard."""
        start_time = datetime.now(UTC)
        try:
            raw_items = await self._fetch_raw()
        except FetchNotModifiedError:
            duration_ms = int(
                (datetime.now(UTC) - start_time).total_seconds() * 1000
            )
            return FetchResult(
                entries=[],
                entries_new=0,
                entries_total=0,
                status=FetchStatus.NOT_MODIFIED,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int(
                (datetime.now(UTC) - start_time).total_seconds() * 1000
            )
            return FetchResult(
                entries=[],
                entries_new=0,
                entries_total=0,
                status=FetchStatus.ERROR,
                error_message=str(e),
                duration_ms=duration_ms,
            )

        entries: list[Entry] = []
        now = datetime.now(UTC)
        max_age_cutoff = now - timedelta(days=14)

        for raw in raw_items:
            try:
                entry = self._parse_entry(raw)
                # Freshness Guard: Max 14 days old
                pub = (
                    entry.published_at.replace(tzinfo=UTC)
                    if entry.published_at.tzinfo is None
                    else entry.published_at
                )
                if pub < max_age_cutoff:
                    continue
                entries.append(entry)
            except Exception as e:
                logger.debug("Failed to parse GitHub repo: %s", e)
                continue

        duration_ms = int(
            (datetime.now(UTC) - start_time).total_seconds() * 1000
        )
        return FetchResult(
            entries=entries,
            entries_total=len(entries),
            entries_new=len(entries),
            status=FetchStatus.SUCCESS,
            duration_ms=duration_ms,
        )


fetcher_registry.register("github_org", GitHubOrgFetcher)
