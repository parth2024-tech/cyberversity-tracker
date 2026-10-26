"""
Zero-Cost Security Signal Enrichment Service.

Provides:
1. In-memory CISA Known Exploited Vulnerabilities (KEV) cache with HTTP/2 ETag conditional polling.
2. Exploitation Prediction Scoring System (EPSS) lookup via FIRST.org API.
3. Deterministic NVD advisory cross-linking with zero external API key requirements.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class CisaEpssService:
    """Zero-quota security signal enrichment via CISA KEV and FIRST.org EPSS."""

    KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    EPSS_BASE_URL = "https://api.first.org/data/v1/epss"

    def __init__(self) -> None:
        self._kev_set: set[str] = set()
        self._kev_etag: str | None = None
        self._kev_last_synced: datetime | None = None
        self._epss_cache: dict[str, tuple[float | None, float | None, datetime]] = {}
        self._lock = asyncio.Lock()

    async def sync_cisa_kev(self, force: bool = False) -> int:
        """
        Synchronize CISA KEV catalog using HTTP conditional GET (ETag).
        Returns the number of known exploited CVEs cached.
        """
        now = datetime.now(UTC)
        if not force and self._kev_last_synced and (now - self._kev_last_synced) < timedelta(hours=6):
            return len(self._kev_set)

        headers: dict[str, str] = {
            "User-Agent": "AETHERGUARD-Intelligence-Radar/2.0 (Security-Research)",
            "Accept": "application/json",
        }
        if self._kev_etag:
            headers["If-None-Match"] = self._kev_etag

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(self.KEV_URL, headers=headers)
                if resp.status_code == 304:
                    self._kev_last_synced = now
                    return len(self._kev_set)

                if resp.status_code == 200:
                    data = resp.json()
                    cves: set[str] = set()
                    for item in data.get("vulnerabilities", []):
                        cve = item.get("cveID")
                        if cve:
                            cves.add(cve.strip().upper())

                    async with self._lock:
                        self._kev_set = cves
                        self._kev_etag = resp.headers.get("ETag")
                        self._kev_last_synced = now

                    logger.info(f"CISA KEV catalog refreshed: {len(cves)} active exploited CVEs cached.")
                    return len(self._kev_set)
        except Exception as e:
            logger.warning(f"Failed to synchronize CISA KEV feed: {e}")

        return len(self._kev_set)

    def is_known_exploited(self, cve_id: str) -> bool:
        """Instant O(1) in-memory check for CISA KEV catalog inclusion."""
        if not cve_id:
            return False
        return cve_id.strip().upper() in self._kev_set

    async def get_epss_score(self, cve_id: str) -> tuple[float | None, float | None]:
        """
        Query FIRST.org EPSS API for exploitation probability and percentile.
        Returns (epss_score, epss_percentile).
        """
        cve = cve_id.strip().upper()
        now = datetime.now(UTC)

        # Check in-memory cache (valid for 12 hours)
        if cve in self._epss_cache:
            score, pct, cached_at = self._epss_cache[cve]
            if (now - cached_at) < timedelta(hours=12):
                return score, pct

        try:
            params = {"cve": cve}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(self.EPSS_BASE_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    rows = data.get("data", [])
                    if rows:
                        first_row = rows[0]
                        epss_val = float(first_row["epss"]) if "epss" in first_row else None
                        pct_val = float(first_row["percentile"]) if "percentile" in first_row else None
                        self._epss_cache[cve] = (epss_val, pct_val, now)
                        return epss_val, pct_val
        except Exception as e:
            logger.debug(f"EPSS query failed for {cve}: {e}")

        return None, None

    @staticmethod
    def get_nvd_url(cve_id: str) -> str:
        """Generate deterministic NVD vulnerability URL without external API queries."""
        clean = cve_id.strip().upper()
        return f"https://nvd.nist.gov/vuln/detail/{clean}"

    async def enrich_cve(self, cve_id: str) -> dict[str, Any]:
        """Produce complete zero-cost threat enrichment payload for a given CVE ID."""
        cve = cve_id.strip().upper()
        is_kev = self.is_known_exploited(cve)
        epss, pct = await self.get_epss_score(cve)

        return {
            "cve": cve,
            "is_kev": is_kev,
            "epss": epss,
            "epss_percentile": pct,
            "nvd_url": self.get_nvd_url(cve),
            "threat_tier": "CRITICAL_EXPLOITED" if is_kev else ("HIGH_PROBABILITY" if (epss and epss > 0.3) else "MONITORED"),
        }


# Global singleton instance
cisa_epss_service = CisaEpssService()
