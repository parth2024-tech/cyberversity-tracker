# CISA Known Exploited Vulnerabilities fetcher.

from datetime import datetime

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)


class CISAFetcher(BaseFetcher):
    """Fetcher for CISA Known Exploited Vulnerabilities catalog."""

    @property
    def fetcher_type(self) -> str:
        return "cisa_kev_json"

    async def _fetch_raw(self) -> list[dict]:
        url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
        headers = {"User-Agent": settings.fetch.user_agent}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        data = response.json()
        vulns = data.get("vulnerabilities", [])
        entries = []

        for vuln in vulns:
            cve_id = vuln.get("cveID", "")
            vuln_name = vuln.get("vulnerabilityName", "")
            short_desc = vuln.get("shortDescription", "")
            required_action = vuln.get("requiredAction", "")
            due_date = vuln.get("dueDate", "")

            content = f"{short_desc}\n\nRequired Action: {required_action}"
            if due_date:
                content += f"\nDue Date: {due_date}"

            entries.append({
                "title": f"CISA KEV: {cve_id} - {vuln_name}",
                "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                "content": content,
                "published_at": datetime.fromisoformat(vuln.get("dateAdded", "").replace("Z", "+00:00")) if vuln.get("dateAdded") else datetime.utcnow(),
                "tags": ["cisa", "kev", "exploited", "critical"],
                "metadata": {
                    "cve_id": cve_id,
                    "vendor": vuln.get("vendorProject", ""),
                    "product": vuln.get("product", ""),
                    "vulnerability_name": vuln_name,
                    "required_action": required_action,
                    "due_date": due_date,
                    "notes": vuln.get("notes", ""),
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


fetcher_registry.register("cisa_kev_json", CISAFetcher)
