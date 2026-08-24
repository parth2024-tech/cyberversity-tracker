"""
Sources configuration loader.
Loads source definitions from YAML and validates them.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ai_security_monitor.config.settings import settings


class SourceConfig(BaseModel):
    """Individual source configuration."""
    name: str = Field(..., description="Unique source name")
    category: str = Field(..., description="Category: ai_tech, ai_research, cybersecurity, vulnerabilities, github_trending")
    type: str = Field(..., description="Source type: rss, arxiv, nvd_api, github_advisories, cisa_kev_json, hackernews, github_trending")
    url: str = Field(default="", description="Source URL (for RSS/API)")
    query: str | None = Field(default=None, description="Query parameter (for arXiv)")
    rate_limit_seconds: int = Field(default=3600, description="Rate limit in seconds")
    enabled: bool = Field(default=True, description="Whether source is active")
    config: dict[str, Any] = Field(default_factory=dict, description="Type-specific extra config")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        allowed = {"ai_tech", "ai_research", "cybersecurity", "vulnerabilities", "github_trending"}
        if v not in allowed:
            raise ValueError(f"Category must be one of {allowed}")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"rss", "arxiv", "nvd_api", "github_advisories", "cisa_kev_json", "hackernews", "github_trending"}
        if v not in allowed:
            raise ValueError(f"Type must be one of {allowed}")
        return v


class SourcesConfig(BaseModel):
    """All sources configuration."""
    sources: list[SourceConfig] = Field(default_factory=list)


@dataclass
class SourceRegistry:
    """Registry of all configured sources."""
    sources: list[SourceConfig] = field(default_factory=list)

    def get_enabled(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def get_by_category(self, category: str) -> list[SourceConfig]:
        return [s for s in self.sources if s.category == category and s.enabled]

    def get_by_type(self, type_: str) -> list[SourceConfig]:
        return [s for s in self.sources if s.type == type_ and s.enabled]


def load_sources(config_path: Path | None = None) -> SourcesConfig:
    """Load sources from YAML configuration file."""
    if config_path is None:
        config_path = Path(settings.config.sources_path) if hasattr(settings, 'config') else Path("config/sources.yaml")

    if not config_path.exists():
        raise FileNotFoundError(f"Sources config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return SourcesConfig(**data)


def load_sources_from_yaml(config_path: Any | None = None) -> list[SourceConfig]:
    """Load sources list directly from YAML configuration file."""
    path = Path(config_path) if config_path else Path("config/sources.yaml")
    return load_sources(path).sources


def create_registry(config_path: Path | None = None) -> SourceRegistry:
    """Create source registry from config."""
    config = load_sources(config_path)
    return SourceRegistry(sources=config.sources)
