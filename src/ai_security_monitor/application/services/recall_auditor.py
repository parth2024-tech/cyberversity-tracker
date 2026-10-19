"""
Lincoln-Petersen / Chapman Capture-Recapture Recall Auditor.
Calculates empirical intelligence recall rates and coverage gaps across
dual-channel ingestion (RSS vs XML Sitemaps) within a rolling 14-day window.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry

logger = get_logger(__name__)


def calculate_chapman_estimate(
    n1_rss: int, n2_sitemap: int, overlap_m: int
) -> dict[str, Any]:
    """Calculate the Chapman-modified Lincoln-Petersen estimator for total universe size and recall.

    Formulas:
        N = ((n1 + 1)(n2 + 1) / (m + 1)) - 1
        Var(N) = ((n1 + 1)(n2 + 1)(n1 - m)(n2 - m)) / ((m + 1)^2 * (m + 2))
        SE = sqrt(Var(N))
        Empirical Recall R = (n1 + n2 - m) / N
        Coverage Gap = 1.0 - R
    """
    if n1_rss < 0 or n2_sitemap < 0 or overlap_m < 0:
        raise ValueError("Item counts must be non-negative integers")

    # Guard: overlap cannot exceed the smaller sample
    m = min(overlap_m, min(n1_rss, n2_sitemap))

    total_captured = n1_rss + n2_sitemap - m

    if n1_rss == 0 and n2_sitemap == 0:
        return {
            "n1_rss": 0,
            "n2_sitemap": 0,
            "overlap_m": 0,
            "total_captured": 0,
            "estimated_universe_N": 0,
            "standard_error": 0.0,
            "ci_95": [0, 0],
            "empirical_recall_pct": 100.0,
            "coverage_gap_pct": 0.0,
            "status": "idle",
        }

    # If only one channel has data, provide baseline estimates
    if n2_sitemap == 0:
        return {
            "n1_rss": n1_rss,
            "n2_sitemap": 0,
            "overlap_m": 0,
            "total_captured": n1_rss,
            "estimated_universe_N": n1_rss,
            "standard_error": 0.0,
            "ci_95": [n1_rss, n1_rss],
            "empirical_recall_pct": 100.0,
            "coverage_gap_pct": 0.0,
            "status": "single_channel_rss_only",
        }

    if n1_rss == 0:
        return {
            "n1_rss": 0,
            "n2_sitemap": n2_sitemap,
            "overlap_m": 0,
            "total_captured": n2_sitemap,
            "estimated_universe_N": n2_sitemap,
            "standard_error": 0.0,
            "ci_95": [n2_sitemap, n2_sitemap],
            "empirical_recall_pct": 100.0,
            "coverage_gap_pct": 0.0,
            "status": "single_channel_sitemap_only",
        }

    # Chapman's unbiased estimator
    estimated_universe = int(
        math.floor(((n1_rss + 1) * (n2_sitemap + 1)) / (m + 1) - 1)
    )
    estimated_universe = max(total_captured, estimated_universe)

    var_n = ((n1_rss + 1) * (n2_sitemap + 1) * (n1_rss - m) * (n2_sitemap - m)) / (
        ((m + 1) ** 2) * (m + 2)
    )
    se = math.sqrt(max(0.0, var_n))

    ci_low = int(max(total_captured, estimated_universe - 1.96 * se))
    ci_high = int(math.ceil(estimated_universe + 1.96 * se))

    recall = (total_captured / estimated_universe) if estimated_universe > 0 else 1.0
    recall = max(0.0, min(1.0, recall))
    gap = max(0.0, 1.0 - recall)

    return {
        "n1_rss": n1_rss,
        "n2_sitemap": n2_sitemap,
        "overlap_m": m,
        "total_captured": total_captured,
        "estimated_universe_N": estimated_universe,
        "standard_error": round(se, 2),
        "ci_95": [ci_low, ci_high],
        "empirical_recall_pct": round(recall * 100.0, 2),
        "coverage_gap_pct": round(gap * 100.0, 2),
        "status": "dual_channel_verified",
    }


class RecallAuditorService:
    """Audits intelligence recall across dual channels over a 14-day rolling window."""

    def __init__(self, window_days: int = 14):
        self.window_days = window_days

    def audit_entries(self, entries: list[Entry]) -> dict[str, Any]:
        """Audit sample of entries within the active freshness window."""
        cutoff = datetime.now(UTC) - timedelta(days=self.window_days)

        rss_urls: set[str] = set()
        sitemap_urls: set[str] = set()

        for e in entries:
            pub = e.published_at
            if pub and pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if pub and pub < cutoff:
                continue

            channel = (e.metadata or {}).get("channel")
            norm_url = (e.url or "").strip().lower()
            if not norm_url:
                continue

            if channel == "sitemap":
                sitemap_urls.add(norm_url)
            else:
                rss_urls.add(norm_url)

        n1 = len(rss_urls)
        n2 = len(sitemap_urls)
        overlap = len(rss_urls & sitemap_urls)

        estimate = calculate_chapman_estimate(n1, n2, overlap)
        estimate["window_days"] = self.window_days
        estimate["timestamp"] = datetime.now(UTC).isoformat()
        return estimate


# Global singleton auditor
recall_auditor = RecallAuditorService()
