# AetherGuard: Worldwide AI Ecosystem Intelligence Architecture

## System Overview & Core Directive

**AetherGuard** is an enterprise-grade, real-time intelligence monitoring platform tracking the worldwide artificial intelligence ecosystem:
1. **Frontier AI Models**: Foundation model breakthroughs, open weights vs. proprietary releases (DeepSeek, Claude, OpenAI, Qwen, Llama, Mistral).
2. **Top AI Research & Breakthroughs**: Seminal arXiv preprints, reasoning architectures, inference compute scaling, multimodal advances.
3. **Trending GitHub Repositories**: Open-source AI repositories, autonomous agent runtimes, automation frameworks, developer codebases.
4. **Developer Tools & Infrastructure**: Inference runtimes (vLLM, Ollama, SGLang, llama.cpp), evaluation harnesses, vector databases, RAG connectors.
5. **Global Sovereign AI & Regional Ecosystems**: National AI labs, robotics, AI chips, hardware, and startup ecosystems worldwide.

> **Operational Directive**: Security, CVEs, and vulnerability telemetry are strictly omitted unless explicitly instructed by the user.

---

## Architecture Principles

1. **Clean Layered Architecture**: Strict dependency flow (`Domain` ← `Application` ← `Infrastructure` ← `Presentation`).
2. **Async-First & High Concurrency**: Non-blocking asynchronous I/O across all fetchers, database queries, and WebSocket broadcasting.
3. **Adaptive Concurrency & Priority Ingestion**: Ingestion concurrency dynamically adapts to source volume (up to 12 slots) with priority ordering favoring highest-value AI ecosystem sources.
4. **Data Hygiene with Grace Recovery**: Rolling 7-day soft-delete retention with a 30-day permanent deletion grace window, complemented by automated rolling 12-hour SQLite backups (60 copies = 30 days).
5. **Epistemic Resilience**: Robust scrape health checks with automated API fallbacks, language detection confidence thresholds (>0.7), and multi-engine translation fallbacks.
6. **Zero External SaaS Dependency**: Fully functional locally using SQLite WAL, offline heuristic and Ollama models, and free upstream APIs.

---

## High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             PRESENTATION LAYER                              │
│  ┌───────────────────────────┐    ┌──────────────────────────────────────┐  │
│  │   FastAPI REST API        │    │    WebSocket Broadcast Manager       │  │
│  │   • slowapi Rate Limiting │    │    • Real-time Feed Broadcast        │  │
│  │     (60/min & 5/min)      │    │    • 2.0s Backpressure Timeout       │  │
│  │   • Response Cache (30s)  │    │    • Stalled Client Pruning (1008)   │  │
│  └─────────────┬─────────────┘    └──────────────────┬───────────────────┘  │
│                │                                     │                      │
│  ┌─────────────▼─────────────────────────────────────▼───────────────────┐  │
│  │   Web HUD Frontend (web/index.html)                                   │  │
│  │   • Glassmorphic Dark Obsidian UI     • Deferred Three.js 3D Globe    │  │
│  │   • Auto-reconnecting WebSocket       • On-Demand Audio / Voice Radar │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             APPLICATION LAYER                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  MonitorService                                                       │  │
│  │  • Priority Ingestion Queue (Models → Research → GitHub → Tools)       │  │
│  │  • Adaptive Concurrency Semaphore (up to 12 concurrent slots)         │  │
│  │  • Consecutive Failure Tracking & Telegram Bot Alerts (threshold=3)   │  │
│  │  • Soft-Purge (7-day) & Hard-Purge (30-day grace window)              │  │
│  ├───────────────────────────────────────────────────────────────────────┤  │
│  │  AutonomousTriageService & DeepAnalysisService                        │  │
│  │  • Async GPU Worker Queue • Epistemic Deep Dives (Models/Papers/Tools)│  │
│  ├───────────────────────────────────────────────────────────────────────┤  │
│  │  TranslationService                                                   │  │
│  │  • langdetect Confidence Thresholding (prob >= 0.70)                  │  │
│  │  • Multi-engine Fallback (GoogleTranslator → MyMemory → Linguee)      │  │
│  ├───────────────────────────────────────────────────────────────────────┤  │
│  │  SchedulerService                                                     │  │
│  │  • Periodic Sweeps • 5-hour Newspaper Dispatches                      │  │
│  │  • Automated SQLite Backups (every 12h, retains 60 copies = 30 days)   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                DOMAIN LAYER                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Entities: Entry, Analysis, Source, Digest, WatchlistRule             │  │
│  │  Value Objects: Category, SourceType, FetchStatus, PaginationParams   │  │
│  │  Repository Interfaces: EntryRepository, SourceRepository, etc.       │  │
│  │  Domain Events & Exceptions                                           │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            INFRASTRUCTURE LAYER                             │
│  ┌───────────────────────────────┐    ┌──────────────────────────────────┐  │
│  │  Database (Async SQLAlchemy)  │    │  Intelligence Fetchers           │  │
│  │  • SQLite WAL Mode & PRAGMAs  │    │  • tenacity Exponential Retries  │  │
│  │  • is_purged / purged_at Soft │    │  • GitHub Trending + DOM Check   │  │
│  │    Delete Columns & Filters   │    │    with Search API Fallback      │  │
│  │  • Unit of Work Pattern       │    │  • ArXiv API & RSS Fetchers      │  │
│  │  • Auto-Pruning Repositories  │    │  • HackerNews Algolia API        │  │
│  ├───────────────────────────────┤    ├──────────────────────────────────┤  │
│  │  Delivery Adapters            │    │  Response Cache                  │  │
│  │  • Console, Telegram, Email   │    │  • In-memory TTL Cache           │  │
│  │  • Newspaper Delivery Tracker │    │  • Startup Pre-Warming           │  │
│  └───────────────────────────────┘    └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Component Specifications

### 1. Ingestion Pipeline & Concurrency
- **Priority Queue Ordering**: Sources are sorted before sweeping so high-value signals process first:
  1. `Category.AI_MODELS` (Priority 1)
  2. `Category.AI_RESEARCH` (Priority 2)
  3. `Category.GITHUB_TRENDING` (Priority 3)
  4. `Category.CYBER_TOOLS` (Developer Tools & Runtimes - Priority 4)
  5. `Category.AI_TECH` (General Ecosystem - Priority 5)
- **Adaptive Concurrency**: Replaced the fixed 4-slot bottleneck with `asyncio.Semaphore(min(len(sources), max_concurrency))` where `max_concurrency` defaults to 12 (configured via `FETCH_MAX_CONCURRENCY`).
- **Resilience & Backoff**: Every HTTP request in `BaseFetcher` is wrapped in `tenacity` exponential retry logic (2 retries with jitter).
- **GitHub Scrape Health Check**: `GitHubTrendingFetcher` inspects the HTML for `article.Box-row` containers. If GitHub layout changes or yield is zero, it automatically logs a warning and falls back to the GitHub Search API.

### 2. Multi-Lingual Translation
- Foreign intelligence feeds (Chinese, Russian, Japanese, Arabic, Korean, German, French) are processed by `TranslationService`.
- **Confidence Cutoff**: `detect_language()` uses `langdetect.detect_langs()` for Latin-script text. If the top candidate is non-English but confidence is below 0.70 (`FETCH_LANGDETECT_CONFIDENCE_THRESHOLD`), the text is left untranslated and tagged with `language_uncertain=True` in metadata. This protects technical jargon, package names, and release tags from corruption.

### 3. Data Persistence, Soft-Delete & Backups
- **Database Engine**: Async SQLite via `aiosqlite` + SQLAlchemy.
- **Performance PRAGMAs**: Boot sequence enforces `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA cache_size=-64000` (64MB page cache), and `PRAGMA busy_timeout=10000`.
- **Two-Tier Data Hygiene**:
  - **7-Day Soft Purge**: Stale, un-vaulted entries have `is_purged=True` and `purged_at=now()` applied. All standard `list()` and `count()` queries automatically filter them out.
  - **30-Day Permanent Purge**: Entries remaining in soft-purged state for over 30 days are purged via `hard_delete_purged()`. Entries saved to the Vault remain permanently protected.
- **Disaster Recovery Backups**: `SchedulerService._backup_loop` copies `monitor.db` to `data/backups/monitor_backup_{timestamp}.db` every 12 hours, retaining 60 snapshots (30 days of coverage to match the hard-delete grace period).

### 4. Presentation & API Layer
- **FastAPI Endpoints**:
  - `GET /api/entries`: Rate limited to 60 requests/minute via `slowapi`. Supports filtering by category, region, country, search terms, and sort orders.
  - `POST /api/sources/fetch`: Rate limited to 5 requests/minute.
  - `GET /api/stats`: Cached for 30s in `response_cache`. Pre-warmed at server boot in `lifespan`.
  - `GET /api/stats/sweep-status`: Cached for 15s in `response_cache`. Pre-warmed at boot.
- **WebSocket Broadcast Protection**:
  - `ConnectionManager.broadcast()` wraps client sends in `asyncio.wait_for(..., timeout=2.0)`.
  - If a consumer stalls or fails to acknowledge within 2.0s, it is disconnected with code `1008` (Policy Violation) and pruned, preventing buffer bloat.
- **Frontend Dashboard (`web/index.html`)**:
  - **Modular Architecture (Zero-Bundler)**: Extracted into standalone, decoupled JavaScript files under `web/js/` loaded via native browser script tags, keeping local development zero-build while shrinking `index.html` by >1,700 lines:
    - `web/js/websocket.js`: Real-time WebSocket manager, exponential backoff reconnection, ping/pong RTT latency tracking, live event dispatcher, and HUD toast notification system.
    - `web/js/voice.js`: Neural TTS voice briefing engine (`VoiceRadar`), Web Speech fallback, tactical chirps, audio player HUD with speed cycling and playlist queuing.
    - `web/js/gazette.js`: 5-hour Autonomous Broadsheet modal, live markdown compile, HTML iframe preview, Telegram PDF dispatcher, and recipient email delivery.
    - `web/js/globe.js`: Three.js WebGL 3D holographic radar globe, 36 sovereign research and defense stations, raycaster hover tooltip, great-circle bezier communication arcs, and low-power GPU profiles.
    - `web/js/palette.js`: Spotlight Command Palette (`Cmd+K` / `Ctrl+K`), fuzzy action filtering, query backfill, and tactical global hotkeys (`/`, `?`, `g`, `b`, `j`, `k`, `Enter`, `Space`, `p`, `s`, `o`).
  - **Deferred Initialization**: Three.js WebGL globe and VoiceRadar sound engines are loaded on-demand when toggled by the user, dramatically reducing initial page load time and memory footprints.
  - **DataSyncEngine**: Request coalescing, staleness budgeting per channel, visibility API pause/burst, and WebSocket-first cache invalidation.

### 5. Self-Healing Telemetry Engine
- **In-Memory Diagnostics Tracker (`DiagnosticsTracker`)**:
  - `github_scrape_fallbacks_total`: Incremented whenever BeautifulSoup scraping detects fewer than 5 repos and switches to GitHub Search API fallback.
  - `websocket_backpressure_drops_total`: Incremented whenever a slow or unresponsive client exceeds the 2.0s send timeout and is disconnected with code `1008`.
  - `consecutive_failure_alerts_total`: Incremented whenever an alert is successfully dispatched to Telegram upon source failure.
  - `language_uncertain_preservations_total`: Incremented whenever low-confidence text is preserved untranslated to protect technical tokens.
  - `last_backup`: Records timestamp, file size (KB), and snapshot retention count on every SQLite backup cycle.
- **Surface**:
  - Exposed via `GET /api/stats/sweep-status` under the `self_healing` object.
  - Rendered live on the frontend in the dedicated "Self-Healing Engine" sidebar card.

---

## Directory & Package Map

```
ai_security_monitor/
├── src/ai_security_monitor/
│   ├── config/
│   │   ├── settings.py           # Pydantic v2 settings (Database, Fetch, Delivery, etc.)
│   │   └── sources.py            # Sources YAML definition & taxonomy loader
│   ├── core/
│   │   └── diagnostics.py        # DiagnosticsTracker singleton for self-healing metrics
│   ├── domain/
│   │   ├── entities.py           # Entry, Source, Analysis, Category entities
│   │   └── repositories.py       # Abstract repository interfaces (EntryRepository, etc.)
│   ├── application/
│   │   └── services/
│   │       ├── monitor_service.py       # Core orchestration, priority queue, Telegram alerts
│   │       ├── scheduler_service.py     # Sweep schedule, automated backups (12h/60 copies)
│   │       ├── translation_service.py   # Confidence-based language translation
│   │       ├── autonomous_triage_service.py # LLM GPU triage worker
│   │       ├── deep_analysis_service.py # Epistemic deep dives (models/papers/tools)
│   │       └── newspaper_service.py     # Multi-format publication dispatch
│   ├── infrastructure/
│   │   ├── database/
│   │   │   ├── connection.py     # SQLite WAL engine & migration runner
│   │   │   ├── models.py         # SQLAlchemy models (is_purged, purged_at)
│   │   │   ├── repositories.py   # SQLAlchemy implementations with soft-delete filtering
│   │   │   └── unit_of_work.py   # Unit of Work transaction manager
│   │   ├── fetchers/
│   │   │   ├── base.py           # BaseFetcher with tenacity retry backoff
│   │   │   ├── github_trending_fetcher.py # Trending scraper + DOM health fallback
│   │   │   ├── arxiv_fetcher.py  # ArXiv preprints fetcher
│   │   │   └── rss_fetcher.py    # RSS & Atom feed fetcher
│   │   ├── cache/
│   │   │   └── response_cache.py # In-memory TTL cache with invalidation
│   │   └── delivery/             # Telegram, Email, Slack, Console dispatchers
│   └── presentation/
│       └── api/
│           ├── main.py           # FastAPI app, lifespan cache warming, CORS/GZip
│           ├── limiter.py        # slowapi Limiter instance
│           ├── routers/          # REST route handlers (entries, sources, stats, etc.)
│           └── websocket/
│               └── manager.py    # WebSocket manager with 2s backpressure eviction
├── web/
│   ├── index.html                # Responsive HUD dashboard (luxury dark obsidian theme)
│   └── js/
│       ├── websocket.js          # WS client, live event dispatch, HUD toasts
│       ├── voice.js              # Neural TTS VoiceRadar audio briefing engine
│       ├── gazette.js            # 5-hour Autonomous Broadsheet modal & dispatchers
│       ├── globe.js              # Three.js WebGL 3D holographic radar globe
│       └── palette.js            # Spotlight Command Palette (Cmd+K) & hotkeys
├── scripts/
│   └── verify_and_loadtest.py    # Automated behavioral load test & scenario verifier
└── tests/
    ├── test_architectural_improvements.py # Comprehensive test suite for all 14 items
    ├── unit/test_diagnostics.py  # Unit tests for self-healing diagnostics tracker
    └── ... (157 tests total)
```