from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
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
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


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
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    category: Category
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    analysis: Analysis | None = None


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
    weaponization_potential: str = "Theoretical"  # Theoretical, PoC Verified, Active Weaponization
    mitre_attack_id: str | None = None  # e.g., "T1190", "AML.T0054"
    mitre_technique: str | None = None  # e.g., "Exploit Public-Facing Application"
    model: AnalysisModel = AnalysisModel.HEURISTIC
    confidence: float = 1.0


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
    fetched_at: datetime = field(default_factory=datetime.utcnow)


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
