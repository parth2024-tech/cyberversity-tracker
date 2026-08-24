"""
Application configuration using Pydantic Settings.
All settings loaded from environment variables and config files.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    url: str = Field(
        default="sqlite+aiosqlite:///data/monitor.db",
        description="SQLAlchemy async database URL"
    )
    echo: bool = Field(default=False, description="Log SQL queries")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max pool overflow")

    model_config = SettingsConfigDict(env_prefix="DB_")


class LoggingSettings(BaseSettings):
    """Logging configuration."""
    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="json", description="Log format: json or console")
    file: Optional[Path] = Field(default=None, description="Log file path")

    model_config = SettingsConfigDict(env_prefix="LOG_")


class APISettings(BaseSettings):
    """FastAPI server configuration."""
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    reload: bool = Field(default=False, description="Auto-reload on changes")
    workers: int = Field(default=1, description="Worker processes")
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")

    model_config = SettingsConfigDict(env_prefix="API_")


class SchedulerSettings(BaseSettings):
    """Background scheduler configuration."""
    enabled: bool = Field(default=True, description="Enable background scheduler")
    timezone: str = Field(default="UTC", description="Scheduler timezone")
    fetch_cron: str = Field(default="0 6 * * *", description="Fetch job cron (6 AM daily)")
    digest_cron: str = Field(default="0 8 * * *", description="Digest job cron (8 AM daily)")

    model_config = SettingsConfigDict(env_prefix="SCHEDULER_")


class FetchSettings(BaseSettings):
    """Feed fetching configuration."""
    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts")
    retry_delay: float = Field(default=2.0, description="Initial retry delay in seconds")
    user_agent: str = Field(
        default="AI-Security-Monitor/2.0 (+https://github.com/your-repo)",
        description="HTTP User-Agent header"
    )
    rate_limit_default: int = Field(default=3600, description="Default rate limit (seconds)")

    model_config = SettingsConfigDict(env_prefix="FETCH_")


class AnalyzerSettings(BaseSettings):
    """AI analysis configuration."""
    enabled: bool = Field(default=True, description="Enable AI analysis")
    default_model: str = Field(default="heuristic", description="Default analyzer: heuristic, ollama, groq")
    ollama_host: str = Field(default="http://localhost:11434", description="Ollama API host")
    ollama_model: str = Field(default="llama3.1:8b", description="Ollama model name")
    groq_api_key: Optional[str] = Field(default=None, description="Groq API key")
    groq_model: str = Field(default="llama-3.1-70b-versatile", description="Groq model name")
    max_tokens: int = Field(default=2000, description="Max tokens for LLM response")
    temperature: float = Field(default=0.1, description="LLM temperature")

    model_config = SettingsConfigDict(env_prefix="ANALYZER_")


class DeliverySettings(BaseSettings):
    """Delivery channels configuration."""
    # Console (always available)
    console_enabled: bool = Field(default=True, description="Enable console output")

    # Email
    email_enabled: bool = Field(default=False, description="Enable email delivery")
    email_smtp_server: str = Field(default="smtp.gmail.com", description="SMTP server")
    email_smtp_port: int = Field(default=587, description="SMTP port")
    email_username: Optional[str] = Field(default=None, description="SMTP username")
    email_password: Optional[str] = Field(default=None, description="SMTP password (app password)")
    email_from: Optional[str] = Field(default=None, description="From email address")
    email_to: Optional[str] = Field(default=None, description="To email address")

    # Slack
    slack_enabled: bool = Field(default=False, description="Enable Slack delivery")
    slack_webhook_url: Optional[str] = Field(default=None, description="Slack webhook URL")
    slack_channel: Optional[str] = Field(default=None, description="Slack channel")

    # Telegram
    telegram_enabled: bool = Field(default=False, description="Enable Telegram delivery")
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    telegram_chat_id: Optional[str] = Field(default=None, description="Telegram chat ID")

    model_config = SettingsConfigDict(env_prefix="DELIVERY_")


class Settings(BaseSettings):
    """Main application settings."""
    # App metadata
    app_name: str = Field(default="AI Security Monitor", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application version")
    environment: str = Field(default="development", description="Environment: development, staging, production")
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
        nested_model_default_partial_update=True,
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


# Global settings instance
settings = Settings()