# NVD CVE API fetcher implementation.

import httpx
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from ai_security_monitor.domain.entities import Entry, Source, Category
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import BaseFetcher, fetcher_registry
from ai_security_monitor.config.settings import settings


class NVDFetcher(BaseFetcher):
    """Fetcher for NVD CVE API."""

    @property
    def fetcher_type(self) -> str:
        return "nvd_api"

    async def _fetch_raw(self) -> list[dict]:
        """Fetch recent CVEs from NVD API."""
        # Last 24 hours by default
        pub_start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000")
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        params = {
            "pubStartDate": pub_start,
            "resultsPerPage": 100,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": settings.fetch.user_agent},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        entries = []

        for vuln in data.get("vulnerabilities", []):
            cve = vuln.get("cve", {})
            cve_id = cve.get("id", "")
            descriptions = cve.get("descriptions", [])
            description = next((d["value"] for d in descriptions if d["lang"] == "en"), "")

            # Get CVSS score
            cvss_score = 0.0
            severity = "UNKNOWN"
            metrics = cve.get("metrics", {})
            for metric_list in metrics.values():
                for metric in metric_list:
                    cvss = metric.get("cvssData", {})
                    if cvss.get("baseScore", 0) > cvss_score:
                        cvss_score = cvss["baseScore"]
                        severity = cvss.get("baseSeverity", "UNKNOWN")

            entries.append({
                "title": f"{cve_id}: {description[:200]}",
                "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                "content": description,
                "published_at": datetime.fromisoformat(cve.get("published", "").replace("Z", "+00:00")) if cve.get("published") else datetime.utcnow(),
                "tags": ["cve", "nvd", severity.lower()],
                "metadata": {
                    "cve_id": cve_id,
                    "cvss_score": cvss_score,
                    "severity": severity,
                    "references": [ref["url"] for ref in cve.get("references", [])],
                }
            })

        return entries

    def _parse_entry(self, raw: dict) -> Entry:
        content_hash = ContentHash.from_content(
            raw["title"],
            raw["url"],
            str(raw["published_at"]),
        )

        return Entry(
            source_id=self.source.id,
            title=raw["title"],
            url=raw["url"],
            content_hash=str(content_hash),
            summary=raw["content"][:500] if raw["content"] else "",
            published_at=raw["published_at"],
            category=self.source.category,
            tags=raw.get("tags", []),
            metadata=raw.get("metadata", {}),
        )


fetcher_registry.register("nvd_api", NVDFetcher)
