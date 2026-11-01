"""
Language-Parity Service and SLO Telemetry.

Governs language parity between Chinese and English intelligence intake:
- Capture parity (7d / 30d yield)
- Latency parity (median & p90 hours from publication to ingestion)
- Target SLO: Chinese latency <= 1.25x English latency, with active native capture.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_security_monitor.application.services.language_detection_service import (
    language_detector,
)
from ai_security_monitor.infrastructure.database.models import (
    DocumentModel,
    EntryModel,
    ParitySnapshotModel,
    SourceModel,
)

logger = structlog.get_logger(__name__)


@dataclass
class SourceYieldStat:
    """Per-source yield and latency statistics."""

    source_id: str
    source_name: str
    category: str
    total_count: int
    zh_count: int
    en_count: int
    median_latency_h: float
    last_fetched_at: str | None


@dataclass
class LanguageParityMetrics:
    """Comprehensive language-parity SLO telemetry."""

    timestamp: datetime
    period_days: int
    data_source: str  # 'documents' (native) or 'entries' (baseline)
    zh_count: int
    en_count: int
    other_count: int
    total_count: int
    capture_rate_ratio: float  # zh_count / max(en_count, 1)
    zh_share_pct: float  # zh_count / total * 100
    zh_median_latency_h: float
    zh_p90_latency_h: float
    en_median_latency_h: float
    en_p90_latency_h: float
    latency_ratio: float  # zh_median / en_median
    slo_latency_met: bool  # latency_ratio <= 1.25
    slo_capture_active: bool  # zh_count > 0
    sources: list[SourceYieldStat] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class LanguageParityService:
    """Evaluates and records multilingual capture and latency parity SLOs."""

    def __init__(self, target_latency_ratio: float = 1.25) -> None:
        self._target_latency_ratio = target_latency_ratio

    async def compute_parity_metrics(
        self, session: AsyncSession, days: int = 7
    ) -> LanguageParityMetrics:
        """Compute language-parity metrics over the specified trailing time window."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days)

        # First check if native documents table has entries
        doc_count_stmt = select(func.count(DocumentModel.id))
        doc_count = (await session.execute(doc_count_stmt)).scalar() or 0

        if doc_count > 0:
            return await self._compute_from_documents(session, cutoff, now, days)
        else:
            return await self._compute_from_entries_baseline(session, cutoff, now, days)

    async def _compute_from_documents(
        self, session: AsyncSession, cutoff: datetime, now: datetime, days: int
    ) -> LanguageParityMetrics:
        """Compute metrics using native documents table."""
        stmt = (
            select(
                DocumentModel.lang,
                DocumentModel.published_at,
                DocumentModel.fetched_at,
                DocumentModel.source_id,
                SourceModel.name.label("source_name"),
                SourceModel.category,
            )
            .join(SourceModel, DocumentModel.source_id == SourceModel.id, isouter=True)
            .where(DocumentModel.published_at >= cutoff)
        )
        result = await session.execute(stmt)
        rows = result.all()

        zh_latencies: list[float] = []
        en_latencies: list[float] = []
        other_count = 0
        source_stats_map: dict[str, dict[str, Any]] = {}

        for row in rows:
            lang = row.lang
            pub = row.published_at
            fet = row.fetched_at
            sid = row.source_id or "unknown"
            sname = row.source_name or "Unknown Source"
            cat = row.category or "unknown"

            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if fet.tzinfo is None:
                fet = fet.replace(tzinfo=UTC)

            latency_h = max(0.0, (fet - pub).total_seconds() / 3600.0)
            if latency_h > 24 * 30:  # ignore historical outliers
                latency_h = 24 * 30

            if sid not in source_stats_map:
                source_stats_map[sid] = {
                    "source_id": sid,
                    "source_name": sname,
                    "category": cat,
                    "total_count": 0,
                    "zh_count": 0,
                    "en_count": 0,
                    "latencies": [],
                    "last_fetched_at": None,
                }

            smap = source_stats_map[sid]
            smap["total_count"] += 1
            smap["latencies"].append(latency_h)

            if lang == "zh":
                zh_latencies.append(latency_h)
                smap["zh_count"] += 1
            elif lang == "en":
                en_latencies.append(latency_h)
                smap["en_count"] += 1
            else:
                other_count += 1

        zh_count = len(zh_latencies)
        en_count = len(en_latencies)
        total_count = zh_count + en_count + other_count

        zh_med = statistics.median(zh_latencies) if zh_latencies else 0.0
        zh_p90 = self._percentile(zh_latencies, 90) if zh_latencies else 0.0
        en_med = statistics.median(en_latencies) if en_latencies else 0.0
        en_p90 = self._percentile(en_latencies, 90) if en_latencies else 0.0

        capture_ratio = zh_count / max(en_count, 1)
        zh_share_pct = (zh_count / max(total_count, 1)) * 100.0
        latency_ratio = zh_med / max(en_med, 0.1) if zh_count > 0 else 0.0

        sources_list = self._build_source_yield_list(source_stats_map)

        return LanguageParityMetrics(
            timestamp=now,
            period_days=days,
            data_source="documents",
            zh_count=zh_count,
            en_count=en_count,
            other_count=other_count,
            total_count=total_count,
            capture_rate_ratio=round(capture_ratio, 4),
            zh_share_pct=round(zh_share_pct, 2),
            zh_median_latency_h=round(zh_med, 2),
            zh_p90_latency_h=round(zh_p90, 2),
            en_median_latency_h=round(en_med, 2),
            en_p90_latency_h=round(en_p90, 2),
            latency_ratio=round(latency_ratio, 4),
            slo_latency_met=latency_ratio <= self._target_latency_ratio if zh_count > 0 else False,
            slo_capture_active=zh_count > 0,
            sources=sources_list,
        )

    async def _compute_from_entries_baseline(
        self, session: AsyncSession, cutoff: datetime, now: datetime, days: int
    ) -> LanguageParityMetrics:
        """Compute metrics using entries table baseline with deterministic language detector."""
        stmt = (
            select(
                EntryModel.title,
                EntryModel.summary,
                EntryModel.published_at,
                EntryModel.fetched_at,
                EntryModel.source_id,
                SourceModel.name.label("source_name"),
                SourceModel.category,
                SourceModel.last_fetched_at.label("src_last_fetched"),
            )
            .join(SourceModel, EntryModel.source_id == SourceModel.id, isouter=True)
            .where(
                EntryModel.is_purged.is_(False),
                EntryModel.published_at >= cutoff,
            )
        )
        result = await session.execute(stmt)
        rows = result.all()

        zh_latencies: list[float] = []
        en_latencies: list[float] = []
        other_count = 0
        source_stats_map: dict[str, dict[str, Any]] = {}

        for row in rows:
            text = f"{row.title or ''} {row.summary or ''}"
            detected = language_detector.detect(text)
            lang = detected.lang

            pub = row.published_at
            fet = row.fetched_at
            sid = row.source_id or "unknown"
            sname = row.source_name or "Unknown Source"
            cat = row.category or "unknown"

            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if fet.tzinfo is None:
                fet = fet.replace(tzinfo=UTC)

            latency_h = max(0.0, (fet - pub).total_seconds() / 3600.0)
            if latency_h > 24 * 30:
                latency_h = 24 * 30

            if sid not in source_stats_map:
                source_stats_map[sid] = {
                    "source_id": sid,
                    "source_name": sname,
                    "category": cat,
                    "total_count": 0,
                    "zh_count": 0,
                    "en_count": 0,
                    "latencies": [],
                    "last_fetched_at": row.src_last_fetched.isoformat()
                    if row.src_last_fetched
                    else None,
                }

            smap = source_stats_map[sid]
            smap["total_count"] += 1
            smap["latencies"].append(latency_h)

            if lang == "zh":
                zh_latencies.append(latency_h)
                smap["zh_count"] += 1
            elif lang == "en":
                en_latencies.append(latency_h)
                smap["en_count"] += 1
            else:
                other_count += 1

        zh_count = len(zh_latencies)
        en_count = len(en_latencies)
        total_count = zh_count + en_count + other_count

        zh_med = statistics.median(zh_latencies) if zh_latencies else 0.0
        zh_p90 = self._percentile(zh_latencies, 90) if zh_latencies else 0.0
        en_med = statistics.median(en_latencies) if en_latencies else 0.0
        en_p90 = self._percentile(en_latencies, 90) if en_latencies else 0.0

        capture_ratio = zh_count / max(en_count, 1)
        zh_share_pct = (zh_count / max(total_count, 1)) * 100.0
        latency_ratio = zh_med / max(en_med, 0.1) if zh_count > 0 else 0.0

        sources_list = self._build_source_yield_list(source_stats_map)

        return LanguageParityMetrics(
            timestamp=now,
            period_days=days,
            data_source="entries (baseline)",
            zh_count=zh_count,
            en_count=en_count,
            other_count=other_count,
            total_count=total_count,
            capture_rate_ratio=round(capture_ratio, 4),
            zh_share_pct=round(zh_share_pct, 2),
            zh_median_latency_h=round(zh_med, 2),
            zh_p90_latency_h=round(zh_p90, 2),
            en_median_latency_h=round(en_med, 2),
            en_p90_latency_h=round(en_p90, 2),
            latency_ratio=round(latency_ratio, 4),
            slo_latency_met=latency_ratio <= self._target_latency_ratio if zh_count > 0 else False,
            slo_capture_active=zh_count > 0,
            sources=sources_list,
        )

    def _percentile(self, values: list[float], percent: float) -> float:
        if not values:
            return 0.0
        sorted_val = sorted(values)
        k = (len(sorted_val) - 1) * (percent / 100.0)
        f = int(k)
        c = f + 1
        if c < len(sorted_val):
            d0 = sorted_val[f] * (c - k)
            d1 = sorted_val[c] * (k - f)
            return round(d0 + d1, 2)
        return round(sorted_val[-1], 2)

    def _build_source_yield_list(
        self, source_stats_map: dict[str, dict[str, Any]]
    ) -> list[SourceYieldStat]:
        result = []
        for sid, d in source_stats_map.items():
            lats = d["latencies"]
            med_lat = statistics.median(lats) if lats else 0.0
            result.append(
                SourceYieldStat(
                    source_id=sid,
                    source_name=d["source_name"],
                    category=d["category"],
                    total_count=d["total_count"],
                    zh_count=d["zh_count"],
                    en_count=d["en_count"],
                    median_latency_h=round(med_lat, 2),
                    last_fetched_at=d["last_fetched_at"],
                )
            )
        result.sort(key=lambda s: s.total_count, reverse=True)
        return result

    async def record_snapshot(
        self, session: AsyncSession, metrics: LanguageParityMetrics
    ) -> ParitySnapshotModel:
        """Persist a parity snapshot to the database."""
        snapshot = ParitySnapshotModel(
            id=str(uuid4()),
            timestamp=metrics.timestamp,
            zh_count_7d=metrics.zh_count,
            en_count_7d=metrics.en_count,
            capture_rate_ratio=metrics.capture_rate_ratio,
            zh_median_latency_h=metrics.zh_median_latency_h,
            en_median_latency_h=metrics.en_median_latency_h,
            latency_ratio=metrics.latency_ratio,
            details=metrics.to_dict(),
        )
        session.add(snapshot)
        await session.commit()
        return snapshot

    def format_markdown_report(self, metrics: LanguageParityMetrics) -> str:
        """Render metrics as an executive markdown report."""
        status_capture = "🟢 ACTIVE" if metrics.slo_capture_active else "🔴 ZERO YIELD (FAIL)"
        status_latency = (
            "🟢 COMPLIANT"
            if metrics.slo_latency_met
            else ("🔴 EXCEEDED" if metrics.zh_count > 0 else "⚪ N/A (No ZH data)")
        )

        md = [
            f"# Multilingual Language-Parity SLO Report ({metrics.period_days}-Day Window)",
            f"- **Timestamp**: `{metrics.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            f"- **Telemetry Mode**: `{metrics.data_source}`",
            f"- **Target SLO**: Chinese Ingestion Latency $\\le {self._target_latency_ratio}\\times$ English Latency",
            "",
            "## Executive SLO Dashboard",
            "| Metric | Value | SLO Target | Status |",
            "|---|---|---|---|",
            f"| **Chinese Capture (7d)** | {metrics.zh_count} docs ({metrics.zh_share_pct}%) | Active (> 0) | {status_capture} |",
            f"| **English Capture (7d)** | {metrics.en_count} docs | Baseline | 🟢 NORMAL |",
            f"| **Total Processed (7d)** | {metrics.total_count} docs | — | — |",
            f"| **Capture Ratio (ZH/EN)** | {metrics.capture_rate_ratio:.4f} | Lab Parity | {status_capture} |",
            f"| **Chinese Median Latency** | {metrics.zh_median_latency_h:.2f} h (p90: {metrics.zh_p90_latency_h:.2f} h) | $\\le 1.25\\times$ EN | {status_latency} |",
            f"| **English Median Latency** | {metrics.en_median_latency_h:.2f} h (p90: {metrics.en_p90_latency_h:.2f} h) | Reference | 🟢 BASELINE |",
            f"| **Latency Ratio (ZH / EN)** | {metrics.latency_ratio:.2f}x | $\\le {self._target_latency_ratio:.2f}\\times$ | {status_latency} |",
            "",
            "## Top Yielding Sources",
            "| Source Name | Category | Total (7d) | ZH | EN | Median Latency |",
            "|---|---|---|---|---|---|",
        ]

        for s in metrics.sources[:15]:
            md.append(
                f"| {s.source_name} | `{s.category}` | {s.total_count} | {s.zh_count} | {s.en_count} | {s.median_latency_h:.2f} h |"
            )

        if not metrics.slo_capture_active:
            md.extend([
                "",
                "> [!IMPORTANT]",
                "> **Phase A Baseline Finding**: The current pipeline routes Chinese sources through 'translate-first' or relies on dormant single-repo GitHub Atom feeds. Native Chinese document capture is at **0 docs**, confirming the imperative for native-language acquisition and entity extraction without English translation dependency.",
            ])

        return "\n".join(md)


language_parity_service = LanguageParityService()
