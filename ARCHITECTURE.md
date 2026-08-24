# AI Security Monitor - Professional Architecture

## Design Principles

1. **Separation of Concerns** - Clear layers: Domain, Application, Infrastructure, Presentation
2. **Dependency Inversion** - Abstract interfaces, concrete implementations
3. **Plugin Architecture** - Extensible fetchers, analyzers, delivery adapters
4. **Async-First** - All I/O operations async, sync only for CLI entry points
5. **Type Safety** - Full type hints, mypy strict mode
6. **Testability** - Dependency injection, pure functions, interfaces
7. **Observability** - Structured logging, metrics, health checks
8. **Zero-Cost** - SQLite, free APIs, no external paid services

## Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   CLI App   │  │  FastAPI    │  │   Web UI    │              │
│  │   (Typer)   │  │  (REST/WS)  │  │  (Static)   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
└─────────┼────────────────┼────────────────┼─────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    Use Cases / Services                      │  │
│  │  • FetchOrchestrator    • AnalysisOrchestrator             │  │
│  │  • DigestService        • SchedulerService                 │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DOMAIN LAYER                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │   Entities   │ │   Events     │ │  Exceptions  │             │
│  │ • Entry      │ │ • Fetched    │ │ • FetchError │             │
│  │ • Analysis   │ │ • Analyzed   │ │ • AnalysisError          │
│  │ • Source     │ │ • Delivered  │ │ • DeliveryError          │
│  │ • Digest     │ └──────────────┘ └──────────────┘             │
│  └──────────────┘                                                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    Repository Interfaces                     │  │
│  │  • EntryRepository    • AnalysisRepository                 │  │
│  │  • SourceRepository   • DigestRepository                   │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      INFRASTRUCTURE LAYER                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │  Database    │ │  External    │ │  Config      │             │
│  │  (SQLAlchemy │ │  Adapters    │ │  (Pydantic)  │             │
│  │   Async)     │ │              │ │              │             │
│  │              │ │ • RSS Fetcher│ │ • Settings   │             │
│  │ • Repositories│ │ • ArXiv API │ │ • Sources    │             │
│  │ • Migrations │ │ • NVD API    │ │ • Secrets    │             │
│  │ • Unit of Work│ │ • GitHub API │ └──────────────┘             │
│  └──────────────┘ └──────────────┘                                │
│  ┌──────────────┐ ┌──────────────┐                               │
│  │  Analyzers   │ │  Delivery    │                               │
│  │  (Plugins)   │ │  (Plugins)   │                               │
│  │              │ │              │                               │
│  │ • Heuristic  │ │ • Console    │                               │
│  │ • LLM (Ollama│ │ • Email      │                               │
│  │   / Groq)    │ │ • Slack      │                               │
│  │ • BlastRad.  │ │ • Telegram   │                               │
│  └──────────────┘ └──────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

## Package Structure

```
ai_security_monitor/
├── pyproject.toml              # Modern packaging, deps, tool config
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .pre-commit-config.yaml
├── README.md
├── Makefile
│
├── config/
│   └── settings.yaml           # Runtime configuration
│
├── src/
│   └── ai_security_monitor/
│       ├── __init__.py
│       ├── __main__.py         # Entry point
│       │
│       ├── config/             # Configuration management
│       │   ├── __init__.py
│       │   ├── settings.py     # Pydantic Settings
│       │   └── sources.py      # Sources configuration
│       │
│       ├── domain/             # Pure domain logic (no external deps)
│       │   ├── __init__.py
│       │   ├── entities.py     # Entry, Analysis, Source, Digest
│       │   ├── events.py       # Domain events
│       │   ├── exceptions.py   # Domain exceptions
│       │   ├── repositories.py # Repository interfaces (ABCs)
│       │   └── value_objects.py# ContentHash, ThreatScore, etc.
│       │
│       ├── application/        # Use cases / orchestration
│       │   ├── __init__.py
│       │   ├── services/
│       │   │   ├── __init__.py
│       │   │   ├── fetch_orchestrator.py
│       │   │   ├── analysis_orchestrator.py
│       │   │   ├── digest_service.py
│       │   │   └── scheduler_service.py
│       │   ├── dto.py          # Data transfer objects
│       │   └── ports/          # Port interfaces (for DI)
│       │       ├── __init__.py
│       │       ├── fetcher_port.py
│       │       ├── analyzer_port.py
│       │       └── delivery_port.py
│       │
│       ├── infrastructure/     # External adapters
│       │   ├── __init__.py
│       │   ├── database/
│       │   │   ├── __init__.py
│       │   │   ├── connection.py      # Async SQLAlchemy engine/session
│       │   │   ├── models.py          # ORM models
│       │   │   ├── repositories.py    # Repository implementations
│       │   │   ├── unit_of_work.py    # Transaction management
│       │   │   └── migrations/        # Alembic migrations
│       │   │
│       │   ├── fetchers/       # Fetcher plugin implementations
│       │   │   ├── __init__.py
│       │   │   ├── base.py     # AbstractFetcher
│       │   │   ├── registry.py # Plugin registry
│       │   │   ├── rss_fetcher.py
│       │   │   ├── arxiv_fetcher.py
│       │   │   ├── nvd_fetcher.py
│       │   │   ├── github_fetcher.py
│       │   │   ├── cisa_fetcher.py
│       │   │   ├── hackernews_fetcher.py
│       │   │   └── github_trending_fetcher.py
│       │   │
│       │   ├── analyzers/      # Analyzer plugin implementations
│       │   │   ├── __init__.py
│       │   │   ├── base.py     # AbstractAnalyzer
│       │   │   ├── registry.py # Plugin registry
│       │   │   ├── heuristic_analyzer.py
│       │   │   ├── llm_analyzer.py
│       │   │   └── blast_radius_analyzer.py
│       │   │
│       │   ├── delivery/       # Delivery plugin implementations
│       │   │   ├── __init__.py
│       │   │   ├── base.py     # AbstractDelivery
│       │   │   ├── registry.py # Plugin registry
│       │   │   ├── console_delivery.py
│       │   │   ├── email_delivery.py
│       │   │   ├── slack_delivery.py
│       │   │   └── telegram_delivery.py
│       │   │
│       │   └── config/
│       │       ├── __init__.py
│       │       └── source_loader.py  # YAML source loading
│       │
│       ├── presentation/       # Presentation layer
│       │   ├── __init__.py
│       │   ├── cli/
│       │   │   ├── __init__.py
│       │   │   ├── app.py      # Typer CLI app
│       │   │   └── commands/
│       │   │       ├── __init__.py
│       │   │       ├── fetch.py
│       │   │       ├── analyze.py
│       │   │       ├── digest.py
│       │   │       ├── server.py
│       │   │       ├── sources.py
│       │   │       └── stats.py
│       │   │
│       │   └── api/
│       │       ├── __init__.py
│       │       ├── main.py     # FastAPI app factory
│       │       ├── lifespan.py # Startup/shutdown
│       │       ├── deps.py     # Dependency injection
│       │       ├── routers/
│       │       │   ├── __init__.py
│       │       │   ├── stats.py
│       │       │   ├── entries.py
│       │       │   ├── sources.py
│       │       │   ├── analysis.py
│       │       │   ├── digest.py
│       │       │   └── health.py
│       │       ├── schemas/    # Pydantic request/response models
│       │       │   ├── __init__.py
│       │       │   ├── entry.py
│       │       │   ├── analysis.py
│       │       │   ├── source.py
│       │       │   ├── stats.py
│       │       │   └── digest.py
│       │       └── websocket/
│       │           ├── __init__.py
│       │           └── manager.py
│       │
│       └── core/               # Cross-cutting concerns
│           ├── __init__.py
│           ├── logging.py      # Structured logging setup
│           ├── metrics.py      # Prometheus metrics
│           ├── health.py       # Health checks
│           └── constants.py    # App constants
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Pytest fixtures
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   ├── integration/
│   │   ├── test_database.py
│   │   ├── test_fetchers.py
│   │   ├── test_analyzers.py
│   │   └── test_delivery.py
│   └── e2e/
│       └── test_cli.py
│
└── web/                        # Static web assets (served by FastAPI)
    ├── index.html
    ├── favicon.ico
    └── assets/