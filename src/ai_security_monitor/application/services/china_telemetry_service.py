"""
China Sources Telemetry & Signal-to-Noise Ratio (SNR) Service.

Provides per-source health, yield, and signal-to-noise analytics
for all Chinese intelligence sources configured in config/sources.yaml.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from ai_security_monitor.application.services.source_health_service import (
    source_health_service,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category
from ai_security_monitor.infrastructure.database.models import (
    EntryModel,
    FetchLogModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

# Keywords identifying high-value AI ecosystem developments
AI_SIGNAL_KEYWORDS = re.compile(
    r"\b("
    r"deepseek|qwen|glm|internlm|kimi|moonshot|baichuan|yi-34b|minimax|stepfun|"
    r"foundation model|open weights|weights released|moe|mixture-of-experts|"
    r"reasoning|test-time compute|chain-of-thought|cot|mcts|prm|"
    r"vllm|sglang|lmdeploy|llama\.cpp|ollama|triton|flashinfer|flashattention|"
    r"benchmark|swe-bench|eval|gpu|npu|ascend|kunlun|wafer|foundry|chip|"
    r"robotics|embodied|autonomous agent|swarm|multimodal|vlm"
    r")\b",
    re.IGNORECASE,
)

# Fluff / non-AI generic corporate patterns
GENERIC_FLUFF_KEYWORDS = re.compile(
    r"\b("
    r"real estate|property market|sales tax|car sales|quarterly profit|revenue jump|"
    r"stock dive|foreign exchange|bond yield|trade tariff|aviation|tourism|"
    r"diplomatic talks|spokesperson said|celebrity|entertainment|box office"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class ChinaSourceTelemetry:
    """Detailed telemetry record for a single Chinese intelligence source."""

    source_name: str
    category: str
    source_type: str
    url: str
    enabled: bool
    tier: int
    db_id: str | None
    health_status: (
        str  # healthy, operational, degraded, failing, stale, unpolled, disabled
    )
    last_fetch_status: str | None
    last_http_status: int | None
    total_sweeps: int
    error_sweeps: int
    zero_entry_streak: int
    total_entries_db: int
    entries_last_14d: int
    entries_last_7d: int
    signal_entries: int
    signal_to_noise_ratio_pct: float
    last_run_at: str | None
    last_productive_at: str | None
    last_error_message: str | None
    diagnosis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChinaTelemetryService:
    """Inspects health, yield, and signal-to-noise ratio per Chinese source in config/sources.yaml."""

    def __init__(self, config_path: Path | str = "config/sources.yaml"):
        self.config_path = Path(config_path)

    def load_china_sources_config(self) -> list[dict[str, Any]]:
        """Load and filter Chinese sources from sources.yaml."""
        if not self.config_path.exists():
            logger.warning(f"Configuration file not found: {self.config_path}")
            return []

        with open(self.config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        sources = cfg.get("sources", [])
        china_sources = [
            s
            for s in sources
            if s.get("region") == "china"
            or str(s.get("country", "")).upper() in ("CN", "HK")
        ]
        return china_sources

    async def get_telemetry(self) -> dict[str, Any]:
        """Generate comprehensive telemetry for all configured China sources."""
        configured = self.load_china_sources_config()
        now = datetime.now(UTC)
        cutoff_14d = now - timedelta(days=14)
        cutoff_7d = now - timedelta(days=7)

        telemetry_records: list[ChinaSourceTelemetry] = []

        async with SqlAlchemyUnitOfWork() as uow:
            session = uow.session

            for cfg_source in configured:
                name = cfg_source.get("name", "Unknown Source")
                cat = cfg_source.get("category", "ai_tech")
                stype = cfg_source.get("type", "rss")
                url = cfg_source.get("url", "")
                enabled = cfg_source.get("enabled", True)
                tier = cfg_source.get("tier", 2)

                # Match against SourceModel in DB
                src_stmt = select(SourceModel).where(SourceModel.name == name)
                src_res = await session.execute(src_stmt)
                db_source = src_res.scalar_one_or_none()

                if not db_source and url:
                    # Fallback URL match
                    url_stmt = select(SourceModel).where(SourceModel.url == url)
                    url_res = await session.execute(url_stmt)
                    db_source = url_res.scalar_one_or_none()

                # In-memory runtime telemetry
                runtime_health = source_health_service.get_source_health(name) or {}
                zero_streak = runtime_health.get("zero_entry_streak", 0)

                if not db_source:
                    rec = ChinaSourceTelemetry(
                        source_name=name,
                        category=cat,
                        source_type=stype,
                        url=url,
                        enabled=enabled,
                        tier=tier,
                        db_id=None,
                        health_status="unpolled" if enabled else "disabled",
                        last_fetch_status=None,
                        last_http_status=None,
                        total_sweeps=0,
                        error_sweeps=0,
                        zero_entry_streak=zero_streak,
                        total_entries_db=0,
                        entries_last_14d=0,
                        entries_last_7d=0,
                        signal_entries=0,
                        signal_to_noise_ratio_pct=0.0,
                        last_run_at=None,
                        last_productive_at=None,
                        last_error_message=None,
                        diagnosis="Source defined in YAML but not yet seeded in local DB.",
                    )
                    telemetry_records.append(rec)
                    continue

                s_id = str(db_source.id)

                # 1. Fetch Logs aggregation
                log_stmt = (
                    select(FetchLogModel)
                    .where(FetchLogModel.source_id == s_id)
                    .order_by(FetchLogModel.fetched_at.desc())
                )
                log_res = await session.execute(log_stmt)
                logs = log_res.scalars().all()

                total_sweeps = len(logs)
                error_sweeps = sum(1 for lg in logs if lg.status == "error")
                last_log = logs[0] if logs else None

                last_fetch_status = last_log.status if last_log else None
                last_error_msg = last_log.error_message if last_log else None
                last_run_at = (
                    last_log.fetched_at.isoformat()
                    if last_log and last_log.fetched_at
                    else None
                )

                # Derive last_productive_at (latest sweep producing >0 new entries)
                productive_logs = [lg for lg in logs if lg.entries_new > 0]
                last_productive = (
                    productive_logs[0].fetched_at.isoformat()
                    if productive_logs and productive_logs[0].fetched_at
                    else None
                )

                # 2. Entries & Yield analysis
                entries_stmt = select(EntryModel).where(
                    EntryModel.source_id == s_id, EntryModel.is_purged.is_(False)
                )
                entries_res = await session.execute(entries_stmt)
                entries = entries_res.scalars().all()

                total_entries_db = len(entries)
                entries_14d = 0
                entries_7d = 0
                signal_entries = 0

                for e in entries:
                    pub = e.published_at or e.created_at
                    if pub:
                        pub_aware = (
                            pub if pub.tzinfo is not None else pub.replace(tzinfo=UTC)
                        )
                        if pub_aware >= cutoff_14d:
                            entries_14d += 1
                        if pub_aware >= cutoff_7d:
                            entries_7d += 1

                    # SNR calculation
                    text = f"{e.title or ''} {e.summary or ''}"
                    is_core_category = e.category in (
                        Category.AI_MODELS.value,
                        Category.AI_RESEARCH.value,
                        Category.GITHUB_TRENDING.value,
                        Category.CYBER_TOOLS.value,
                        Category.AI_TECH.value,
                    )
                    has_ai_signal = bool(AI_SIGNAL_KEYWORDS.search(text))
                    is_fluff = bool(GENERIC_FLUFF_KEYWORDS.search(text))

                    if (is_core_category or has_ai_signal) and not is_fluff:
                        signal_entries += 1

                snr_pct = (
                    round((signal_entries / max(1, total_entries_db)) * 100.0, 1)
                    if total_entries_db > 0
                    else 0.0
                )

                # 3. Diagnosis and Health state synthesis
                if not enabled:
                    health_status = "disabled"
                    diagnosis = "Source is explicitly disabled in configuration."
                elif total_sweeps == 0:
                    health_status = "unpolled"
                    diagnosis = "Pending initial sweep scheduler execution."
                elif last_fetch_status == "error":
                    health_status = "failing"
                    diagnosis = f"Sweep failed with error: {last_error_msg or 'Unknown network error'}"
                elif total_entries_db == 0:
                    if "commits.atom" in url or "releases.atom" in url:
                        health_status = "stale"
                        diagnosis = (
                            "Pinned GitHub repository feed is inactive (>14 days old); "
                            "upstream releases published under new repo names."
                        )
                    elif last_error_msg and "timeout" in last_error_msg.lower():
                        health_status = "degraded"
                        diagnosis = (
                            "Connection or SSL handshake timeout from server host."
                        )
                    else:
                        health_status = "zero_yield"
                        diagnosis = "Feed operational but yielded 0 items within 14-day freshness window."
                else:
                    if snr_pct >= 85.0:
                        health_status = "healthy"
                        diagnosis = f"Optimal telemetry: high signal-to-noise ratio ({snr_pct}%)."
                    elif snr_pct >= 50.0:
                        health_status = "operational"
                        diagnosis = f"Acceptable yield ({snr_pct}% SNR) with mixed general regional news."
                    else:
                        health_status = "degraded"
                        diagnosis = f"Low signal-to-noise ratio ({snr_pct}%); contains high generic business noise."

                record = ChinaSourceTelemetry(
                    source_name=name,
                    category=cat,
                    source_type=stype,
                    url=url,
                    enabled=enabled,
                    tier=tier,
                    db_id=s_id,
                    health_status=health_status,
                    last_fetch_status=last_fetch_status,
                    last_http_status=200 if last_fetch_status == "success" else None,
                    total_sweeps=total_sweeps,
                    error_sweeps=error_sweeps,
                    zero_entry_streak=zero_streak,
                    total_entries_db=total_entries_db,
                    entries_last_14d=entries_14d,
                    entries_last_7d=entries_7d,
                    signal_entries=signal_entries,
                    signal_to_noise_ratio_pct=snr_pct,
                    last_run_at=last_run_at,
                    last_productive_at=last_productive,
                    last_error_message=last_error_msg,
                    diagnosis=diagnosis,
                )
                telemetry_records.append(record)

        # High-level aggregate statistics
        total_sources = len(telemetry_records)
        active_sources = sum(1 for r in telemetry_records if r.total_entries_db > 0)
        healthy_sources = sum(
            1
            for r in telemetry_records
            if r.health_status in ("healthy", "operational")
        )
        zero_yield_sources = sum(
            1 for r in telemetry_records if r.total_entries_db == 0 and r.enabled
        )
        total_db_entries = sum(r.total_entries_db for r in telemetry_records)
        total_signal = sum(r.signal_entries for r in telemetry_records)
        overall_snr_pct = (
            round((total_signal / max(1, total_db_entries)) * 100.0, 1)
            if total_db_entries > 0
            else 0.0
        )

        return {
            "corridor": "China AI & Ecosystem Telemetry (中国AI生态源健康与信噪比监测)",
            "generated_at": now.isoformat(),
            "total_sources": total_sources,
            "active_sources": active_sources,
            "healthy_sources": healthy_sources,
            "zero_yield_sources": zero_yield_sources,
            "total_entries_db": total_db_entries,
            "total_signal_entries": total_signal,
            "overall_snr_pct": overall_snr_pct,
            "sources": [r.to_dict() for r in telemetry_records],
        }


china_telemetry_service = ChinaTelemetryService()
