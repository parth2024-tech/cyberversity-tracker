from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class Category(str, Enum):
    """Entry categories."""

    AI_TECH = "ai_tech"
    AI_RESEARCH = "ai_research"
    CYBERSECURITY = "cybersecurity"
    VULNERABILITIES = "vulnerabilities"
    GITHUB_TRENDING = "github_trending"
    AI_MODELS = "ai_models"
    CYBER_TOOLS = "cyber_tools"
    EXPLOITS_TRICKS = "exploits_tricks"


class SourceType(str, Enum):
    """Source types."""

    RSS = "rss"
    ARXIV = "arxiv"
    NVD_API = "nvd_api"
    GITHUB_ADVISORIES = "github_advisories"
    CISA_KEV_JSON = "cisa_kev_json"
    HACKERNEWS = "hackernews"
    GITHUB_TRENDING = "github_trending"
    REDDIT = "reddit"
    GOOGLE_NEWS = "google_news"
    OSS_INSIGHT = "oss_insight"
    SITEMAP = "sitemap"
    HUGGINGFACE_TRENDING = "huggingface_trending"
    TWITTER_X = "twitter_x"
    MODELSCOPE = "modelscope"
    HUGGINGFACE_CHINA = "huggingface_china"
    HUGGINGFACE_DAILY_PAPERS = "huggingface_daily_papers"


class FetchStatus(str, Enum):
    """Fetch operation status."""

    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class AnalysisModel(str, Enum):
    """Analysis model used."""

    HEURISTIC = "heuristic"
    OLLAMA = "ollama"
    GROQ = "groq"
    LOCAL = "local"
    BLAST_RADIUS = "blast_radius"


@dataclass(kw_only=True)
class Entity:
    """Base entity with ID and timestamps."""

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class Source(Entity):
    """Intelligence source configuration."""

    name: str
    category: Category
    type: SourceType
    url: str = ""
    query: str | None = None
    rate_limit_seconds: int = 3600
    enabled: bool = True
    last_fetched_at: datetime | None = None
    last_status: FetchStatus | None = None
    last_entries_new: int = 0
    tier: float = 2.0
    config: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class Entry(Entity):
    """Intelligence entry - a piece of content from a source."""

    source_id: UUID
    title: str
    url: str
    content_hash: str  # SHA256 for deduplication
    summary: str = ""
    published_at: datetime
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    category: Category
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    analysis: Analysis | None = None
    is_purged: bool = False
    purged_at: datetime | None = None
    story_id: UUID | None = None
    lab_id: UUID | None = None
    subject_region: str | None = None

    def __post_init__(self) -> None:
        if (
            self.published_at
            and hasattr(self.published_at, "tzinfo")
            and self.published_at.tzinfo is not None
        ):
            self.published_at = self.published_at.replace(tzinfo=None)
        if (
            self.fetched_at
            and hasattr(self.fetched_at, "tzinfo")
            and self.fetched_at.tzinfo is not None
        ):
            self.fetched_at = self.fetched_at.replace(tzinfo=None)


@dataclass(kw_only=True)
class Story(Entity):
    """A synthesized cluster/story aggregate uniting 1+ corroborating cross-source entries."""

    title: str
    canonical_url: str
    fingerprint: str
    category: Category
    summary: str = ""
    source_count: int = 1
    confidence_score: float = (
        0.50  # 0.50 single, 0.75 corroborated (2), 1.00 consensus (4+)
    )
    entry_ids: list[UUID] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    participant_timestamps: list[datetime] = field(default_factory=list)
    heat_score: float = 0.0
    heat_badge: str | None = None

    def calculate_heat(
        self, now: datetime | None = None, half_life_hours: float = 24.0
    ) -> float:
        """Compute half-life heat decay: sum(0.5 ** (delta_t / 24.0)) across all participant timestamps."""
        ref_time = now or datetime.now(UTC)
        total_heat = 0.0
        timestamps = self.participant_timestamps or [self.last_seen_at]
        for ts in timestamps:
            ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
            ref_aware = (
                ref_time if ref_time.tzinfo is not None else ref_time.replace(tzinfo=UTC)
            )
            delta_hours = max(0.0, (ref_aware - ts_aware).total_seconds() / 3600.0)
            total_heat += 0.5 ** (delta_hours / half_life_hours)
        self.heat_score = round(total_heat, 3)
        return self.heat_score

    def update_badge(self, now: datetime | None = None) -> str | None:
        """Assign heat badge: surge (requires >= 2 unique sources + strong heat), rising, or new."""
        ref_time = now or datetime.now(UTC)
        heat = self.calculate_heat(now=ref_time)
        first_seen = (
            self.first_seen_at
            if self.first_seen_at.tzinfo is not None
            else self.first_seen_at.replace(tzinfo=UTC)
        )
        ref_aware = (
            ref_time if ref_time.tzinfo is not None else ref_time.replace(tzinfo=UTC)
        )
        age_hours = max(0.0, (ref_aware - first_seen).total_seconds() / 3600.0)

        # 1. Surge: multi-source momentum
        # Strictly requires at least 2 unique corroborating sources AND heat >= 1.6
        if self.source_count >= 2 and heat >= 1.6:
            self.heat_badge = "surge"
        # 2. Rising: accelerating interest or solid heat
        elif heat >= 1.2 or (age_hours <= 12.0 and heat >= 0.85):
            self.heat_badge = "rising"
        # 3. New: broke very recently
        elif age_hours <= 6.0:
            self.heat_badge = "new"
        else:
            self.heat_badge = None
        return self.heat_badge

    def add_entry(self, entry: Entry, source_name: str | None = None) -> None:
        """Add corroborating entry to story and update decoupled factual confidence and heat."""
        import math

        if entry.id not in self.entry_ids:
            self.entry_ids.append(entry.id)
            if source_name and source_name not in self.sources:
                self.sources.append(source_name)
            self.source_count = len(self.sources) or len(self.entry_ids)
            # Decoupled Factual Confidence: C = min(1.0, 0.50 + 0.25 * log2(N_sources))
            n_src = max(1, self.source_count)
            self.confidence_score = min(1.0, round(0.50 + 0.25 * math.log2(n_src), 2))
            ts = entry.published_at or entry.created_at or datetime.now(UTC)
            self.participant_timestamps.append(ts)
            self.last_seen_at = datetime.now(UTC)
            for tag in entry.tags:
                if tag not in self.tags:
                    self.tags.append(tag)
            self.calculate_heat()
            self.update_badge()


@dataclass(kw_only=True)
class Analysis(Entity):
    """AI analysis of an entry."""

    entry_id: UUID
    attack_vector: str
    risk_assessment: str
    mitigation: str
    threat_velocity: int  # 1-100
    severity_index: int  # 1-100
    blast_radius_score: int = 0  # 1-100
    affected_ecosystem: list[str] = field(default_factory=list)
    is_pre_cve_warning: bool = False
    attack_archetype: str = ""
    weaponization_potential: str = (
        "Theoretical"  # Theoretical, PoC Verified, Active Weaponization
    )
    mitre_attack_id: str | None = None  # e.g., "T1190", "AML.T0054"
    mitre_technique: str | None = None  # e.g., "Exploit Public-Facing Application"
    model: AnalysisModel = AnalysisModel.HEURISTIC
    confidence: float = 1.0

    # Domain language aliases for Worldwide AI Ecosystem context
    @property
    def tech_focus(self) -> str:
        """Ecosystem domain alias for attack_vector (e.g. Inference Optimization, Reasoning)."""
        return self.attack_vector

    @property
    def capability_summary(self) -> str:
        """Ecosystem domain alias for risk_assessment (e.g. Architectural breakthrough description)."""
        return self.risk_assessment

    @property
    def velocity_score(self) -> int:
        """Ecosystem domain alias for threat_velocity (e.g. Star/adoption velocity 1-100)."""
        return self.threat_velocity

    @property
    def ecosystem_reach(self) -> int:
        """Ecosystem domain alias for blast_radius_score (e.g. Ecosystem footprint 1-100)."""
        return self.blast_radius_score


@dataclass(kw_only=True)
class FetchLog(Entity):
    """Log of a fetch operation."""

    source_id: UUID
    source_name: str
    status: FetchStatus
    entries_new: int = 0
    entries_total: int = 0
    error_message: str | None = None
    duration_ms: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class Digest(Entity):
    """Generated digest for delivery."""

    schedule: str  # daily, weekly
    entries_by_category: dict[str, list[Entry]] = field(default_factory=dict)
    total_entries: int = 0
    period_start: datetime
    period_end: datetime
    delivered: bool = False
    delivery_channels: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class LLMReceipt(Entity):
    """Execution receipt for LLM inference to ensure idempotency and prevent retry loops."""

    logical_key: str
    provider: str
    model: str
    prompt_version: str
    status: str = "pending"  # "pending", "succeeded", "failed"
    entry_id: UUID | None = None
    attempts: int = 1
    max_attempts: int = 3
    response_json: dict[str, Any] | None = None
    error_message: str | None = None

    @property
    def is_retryable(self) -> bool:
        if self.status == "succeeded":
            return False
        return self.attempts < self.max_attempts


@dataclass(kw_only=True)
class Lab(Entity):
    """Frontier AI Lab entity."""

    name: str
    region: str
    country: str
    hf_orgs: list[str] = field(default_factory=list)
    github_orgs: list[str] = field(default_factory=list)
    modelscope_ids: list[str] = field(default_factory=list)
    wechat_accounts: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    notes: str | None = None


