"""
Application configuration using Pydantic Settings.
All settings loaded from environment variables and config files.
"""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_default_db_url() -> str:
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        clean_dir = data_dir.rstrip("/")
        return f"sqlite+aiosqlite:///{clean_dir}/monitor.db"
    return "sqlite+aiosqlite:///data/monitor.db"


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    url: str = Field(
        default_factory=_get_default_db_url, description="SQLAlchemy async database URL"
    )

    @property
    def resolved_url(self) -> str:
        """Dynamically resolve database URL honoring runtime environment variables."""
        env_url = os.environ.get("DATABASE__URL") or os.environ.get("DB_URL")
        if env_url:
            return env_url
        data_dir = os.environ.get("DATA_DIR")
        if data_dir:
            clean_dir = data_dir.rstrip("/")
            return f"sqlite+aiosqlite:///{clean_dir}/monitor.db"
        return self.url
    retention_days: int = Field(
        default=7, description="Data retention period in days (1 week)"
    )
    auto_purge_enabled: bool = Field(
        default=False,
        description="Whether automatic background retention purge is enabled (False = manual cleanup only)",
    )
    hard_delete_grace_days: int = Field(
        default=30,
        description="Grace period in days before permanent deletion of soft-purged entries",
    )
    max_ingest_age_days: int = Field(
        default=14,
        description="Max age in days for newly fetched entries to prevent historical feed pollution (default 14 days / 2 weeks)",
    )
    backup_interval_hours: int = Field(
        default=12,
        description="Interval in hours between automated SQLite database backups",
    )
    backup_retention_copies: int = Field(
        default=60,
        description="Number of rolling backups to retain (60 copies @ 12h = 30 days of disaster recovery)",
    )
    echo: bool = Field(default=False, description="Log SQL queries")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max pool overflow")

    model_config = SettingsConfigDict(env_prefix="DB_")


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="json", description="Log format: json or console")
    file: Path | None = Field(default=None, description="Log file path")

    model_config = SettingsConfigDict(env_prefix="LOG_")


class APISettings(BaseSettings):
    """FastAPI server configuration."""

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    reload: bool = Field(default=False, description="Auto-reload on changes")
    workers: int = Field(default=1, description="Worker processes")
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")
    admin_api_key: str | None = Field(
        default_factory=lambda: (
            os.environ.get("ADMIN_API_KEY") or os.environ.get("API_ADMIN_API_KEY")
        ),
        description="Secret API key required for mutating and administrative endpoints",
    )

    model_config = SettingsConfigDict(env_prefix="API_")


class SchedulerSettings(BaseSettings):
    """Background scheduler configuration."""

    enabled: bool = Field(default=True, description="Enable background scheduler")
    timezone: str = Field(default="UTC", description="Scheduler timezone")
    fetch_interval_minutes: int = Field(
        default=10, description="Periodic radar sweep interval in minutes"
    )
    fetch_cron: str = Field(
        default="0 6 * * *", description="Fetch job cron (6 AM daily)"
    )
    digest_cron: str = Field(
        default="0 8 * * *", description="Digest job cron (8 AM daily)"
    )

    model_config = SettingsConfigDict(env_prefix="SCHEDULER_")


class FetchSettings(BaseSettings):
    """Feed fetching configuration."""

    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts")
    retry_delay: float = Field(
        default=2.0, description="Initial retry delay in seconds"
    )
    user_agent: str = Field(
        default="AI-Security-Monitor/2.0 (+https://github.com/your-repo)",
        description="HTTP User-Agent header",
    )
    rate_limit_default: int = Field(
        default=3600, description="Default rate limit (seconds)"
    )
    max_concurrency: int = Field(
        default=12,
        description="Maximum concurrent fetch workers (adaptive semaphore cap)",
    )
    consecutive_failure_threshold: int = Field(
        default=3, description="Consecutive fetch failures before triggering alert"
    )
    langdetect_confidence_threshold: float = Field(
        default=0.7, description="Minimum confidence for language detection"
    )
    max_entries_per_feed: int = Field(
        default=25,
        description="Maximum entries to ingest from a single feed per sweep to ensure source diversity and prevent feed domination",
    )

    model_config = SettingsConfigDict(env_prefix="FETCH_")


class AnalyzerSettings(BaseSettings):
    """AI analysis configuration."""

    enabled: bool = Field(default=True, description="Enable AI analysis")
    default_model: str = Field(
        default="heuristic",
        description="Default analyzer: heuristic, ollama, groq, auto/offline",
    )
    ollama_host: str = Field(
        default="http://localhost:11434", description="Ollama API host"
    )
    ollama_model: str = Field(default="llama3.1:8b", description="Ollama model name")
    groq_api_key: str | None = Field(default=None, description="Groq API key")
    groq_model: str = Field(
        default="llama-3.1-70b-versatile", description="Groq model name"
    )
    max_tokens: int = Field(default=400, description="Max tokens for LLM response")
    temperature: float = Field(default=0.1, description="LLM temperature")

    # Local LLM routing via Hermes gateway
    use_local_llm: bool = Field(
        default=True, description="Route LLM calls through local gateway (auto/offline)"
    )
    local_model: str = Field(
        default="auto/offline", description="Local model via gateway"
    )

    # Autonomous High-Priority Triage Queue
    autonomous_triage_enabled: bool = Field(
        default=True, description="Enable autonomous high-priority LLM triage"
    )
    triage_velocity_threshold: int = Field(
        default=70, description="Minimum threat velocity to auto-enqueue for LLM triage"
    )
    triage_concurrency: int = Field(
        default=1, description="Max concurrent LLM triage jobs"
    )
    triage_interval_seconds: float = Field(
        default=2.0, description="Pause between queued triage tasks"
    )
    queue_hold_until_sweep: bool = Field(
        default=True,
        description="Hold queued entries in triage queue until user triggers Live Sweep",
    )
    prompt_version: str = Field(
        default="v1.0",
        description="Prompt version string hashed into LLM receipts to enable intentional cache invalidation",
    )
    receipt_max_retries: int = Field(
        default=3,
        description="Maximum failed LLM attempts before an entry is marked poisoned and skipped on boot",
    )

    # Pillar 3: Tiered Model Routing & Ephemeral Prompt Caching
    slm_enabled: bool = Field(
        default=True,
        description="Enable Tier 1 Local SLM routing for high-volume tasks (translation, fast-pass triage)",
    )
    slm_endpoint: str = Field(
        default="http://localhost:11434",
        description="Ollama/OpenAI-compatible local SLM endpoint",
    )
    slm_model: str = Field(
        default="qwen2.5:7b",
        description="Local SLM model name (e.g. qwen2.5:7b, llama3.2:3b)",
    )
    slm_timeout_seconds: float = Field(
        default=0.5,
        description="Fast-fail timeout (seconds) for local SLM health & connect checks (<= 500ms)",
    )
    slm_cooldown_seconds: float = Field(
        default=300.0,
        description="Circuit breaker cooldown (seconds) on local SLM connection failure (5 minutes)",
    )
    cloud_frontier_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Tier 2 Cloud Frontier model for high-priority items & deep dossiers",
    )
    cloud_fast_model: str = Field(
        default="llama-3.1-70b-versatile",
        description="Fast cloud fallback model (Groq / Gemini / Haiku) when local SLM circuit breaker is open",
    )
    enable_prompt_caching: bool = Field(
        default=True,
        description="Enable ephemeral prompt caching headers and strict static prefix structuring",
    )

    model_config = SettingsConfigDict(env_prefix="ANALYZER_")


class DeliverySettings(BaseSettings):
    """Delivery channels configuration."""

    # Console (always available)
    console_enabled: bool = Field(default=True, description="Enable console output")

    # Email
    email_enabled: bool = Field(default=False, description="Enable email delivery")
    email_smtp_server: str = Field(default="smtp.gmail.com", description="SMTP server")
    email_smtp_port: int = Field(default=587, description="SMTP port")
    email_username: str | None = Field(default=None, description="SMTP username")
    email_password: str | None = Field(
        default=None, description="SMTP password (app password)"
    )
    email_from: str | None = Field(default=None, description="From email address")
    email_to: str | None = Field(default=None, description="To email address")

    # Slack
    slack_enabled: bool = Field(default=False, description="Enable Slack delivery")
    slack_webhook_url: str | None = Field(default=None, description="Slack webhook URL")
    slack_channel: str | None = Field(default=None, description="Slack channel")

    # Telegram
    telegram_enabled: bool = Field(
        default=False, description="Enable Telegram delivery"
    )
    telegram_bot_token: str | None = Field(
        default=None, description="Telegram bot token"
    )
    telegram_chat_id: str | None = Field(default=None, description="Telegram chat ID")
    telegram_mode: str = Field(
        default="webhook", description="Telegram transport mode: 'webhook' or 'poll'"
    )
    telegram_webhook_secret: str | None = Field(
        default=None,
        description="Secret token for X-Telegram-Bot-Api-Secret-Token validation",
    )
    telegram_allowed_user_id: int | None = Field(
        default=None,
        description="Authorized Telegram user ID for ChatOps action execution",
    )

    model_config = SettingsConfigDict(env_prefix="DELIVERY_")


class Settings(BaseSettings):
    """Main application settings."""

    # App metadata
    app_name: str = Field(default="AI Security Monitor", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application version")
    environment: str = Field(
        default="development",
        description="Environment: development, staging, production",
    )
    debug: bool = Field(default=False, description="Debug mode")

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api: APISettings = Field(default_factory=APISettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    analyzer: AnalyzerSettings = Field(default_factory=AnalyzerSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


# Global settings instance
settings = Settings()
