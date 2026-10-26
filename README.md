# AETHERGUARD: Worldwide AI Ecosystem Intelligence Pipeline

[![Build Status](https://img.shields.io/badge/Build-Passing-2ea44f?style=flat-square)](https://github.com/parth2024-tech/cyberversity-tracker/actions)
[![Test Suite](https://img.shields.io/badge/Tests-345%20Passing-brightgreen?style=flat-square)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-79%25-blue?style=flat-square)](tests/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20%2F%20Onion-orange?style=flat-square)](src/ai_security_monitor/domain)

A zero-daemon, high-recall intelligence pipeline and telemetry engine monitoring the global artificial intelligence landscape. Tracks frontier foundation models, open-weight breakthroughs, developer tooling, inference engines, arXiv preprints, and regional sovereign AI initiatives.

> **Note on Naming & Repository**:
> The project product name is **AETHERGUARD**. The underlying Python package namespace is `ai_security_monitor` (preserved for backward compatibility), and the GitHub repository is hosted at [`cyberversity-tracker`](https://github.com/parth2024-tech/cyberversity-tracker). The automated daily publication is the **AI Gazette**.

---

## 🎯 Primary Scope & Focus Areas

AETHERGUARD focuses strictly on the worldwide artificial intelligence ecosystem across five core verticals:

1. **Frontier Foundation Models**: Model releases, reasoning architectures, test-time compute scaling, and open weights (DeepSeek, Qwen, Claude, Llama, Mistral, OpenAI).
2. **Inference Runtimes & Infrastructure**: High-throughput inference engines (`vLLM`, `SGLang`, `llama.cpp`, `Ollama`, `TensorRT-LLM`), memory-efficient kernels, and serving frameworks.
3. **Trending Repositories & Open Source**: High-velocity GitHub repositories, autonomous agent frameworks, tool-use systems, and developer libraries.
4. **Research Breakthroughs & Preprints**: Curated arXiv feeds, model architecture innovations, synthetic data pipelines, and post-training alignment.
5. **Sovereign AI & Regional Ecosystems**: National AI compute clusters, regional labs, hardware accelerators, and sovereign AI initiatives across Europe, APAC, China, the Middle East, and the Americas.

---

## 🏛️ System Architecture

AETHERGUARD is designed according to **Clean / Onion Architecture**. Pure domain rules and value objects remain completely decoupled from external frameworks, scrapers, and database engines.

```text
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                         PRESENTATION LAYER (INBOUND)                        │
 │  FastAPI REST API (/api & /api/v1)  │  WebSocket Event Bus (/ws)            │
 │  Installed Typer CLI (aetherguard)  │  Model Context Protocol (MCP stdio)   │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                        APPLICATION SERVICES LAYER                           │
 │  MonitorService (Orchestrator)      │  AutonomousTriageService (P0-P2 Queue)│
 │  ArticleExtractor (Trafilatura)     │  VaultFeedbackService (Preference)    │
 │  SchedulerService (Cron / Interval) │  NewspaperService (Daily Gazette)     │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                               DOMAIN CORE                                   │
 │  Entities: Entry, Source, Analysis  │  Repositories & Unit of Work (Ports)  │
 │  Value Objects: Category, Priority  │  Deduplication: SimHash & MinHash     │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                     INFRASTRUCTURE ADAPTERS (OUTBOUND)                      │
 │  SQLAlchemy 2.0 Async Repositories  │  SQLite WAL / PostgreSQL Driver       │
 │  Resilient Scraper Engine           │  10+ Fetchers (X, Reddit, arXiv, etc.)│
 │  Heuristic & Local LLM Analyzers    │  Delivery: Discord, Telegram, Slack   │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Resilient Scraper Engine (`infrastructure/scrapers`)

To overcome the fragility and strict rate-limiting of modern platforms, AETHERGUARD features an internal GraphQL and REST scraper package:

```text
src/ai_security_monitor/infrastructure/scrapers/
├── config/
│   ├── headers.py            # Static public web bearer token & browser client headers
│   └── queries.py            # Reverse-engineered Twitter GraphQL Query IDs & feature flags
├── core/
│   ├── session_pool.py       # Manages auth_token, ct0, and automated guest token rotation
│   ├── client.py             # HTTP/2 client with retry backoff and TLS fingerprint spoofing
│   └── rate_limiter.py       # Exponential backoff with full jitter & Retry-After parsing
├── models/
│   ├── tweet.py              # Pydantic schemas for normalized tweets, metrics, and authors
│   └── reddit_post.py        # Pydantic schemas for Reddit posts, authors, and comments
└── extractors/
    ├── twitter_graphql.py    # Unwinds nested GraphQL timeline trees and note tweets
    └── reddit_endpoints.py   # Unwinds Reddit REST post listings and comment trees
```

### Scraper Maintenance & Terms of Service Notice
* **Query ID Rotation**: Twitter/X periodically regenerates GraphQL `queryId` hashes during web client releases. These can be inspected and updated directly in `config/queries.py`.
* **Multi-Tier Search Fallback**: If Twitter GraphQL or Reddit JSON endpoints return HTTP 429 (Rate Limited) or 403 (Forbidden), fetchers automatically fall back to Google News syndication search bridges (`site:x.com ... when:14d` and `site:reddit.com/r/{sub} when:14d`), guaranteeing 100% data continuity.
* **ToS & Usage**: Scrapers are provided strictly for research and open-source intelligence monitoring. Anonymous guest tokens are used by default; optional personal session cookies (`TWITTER_AUTH_TOKEN`, `TWITTER_CT0`) can be supplied in `.env`.

---

## ⚙️ Configuration & Ingestion Controls

AETHERGUARD employs three distinct time and retention controls to prevent database bloat and keep intelligence timely:

| Setting | Default | Purpose & Behavior |
|---|---|---|
| `DATABASE__MAX_INGEST_AGE_DAYS` | `14` | **Ingestion Boundary Gate**: Strictly drops historical RSS/feed entries published > 14 days ago. Guarantees that only fresh, relevant breakthroughs enter the pipeline. |
| `DATABASE__AUTO_PURGE_ENABLED` | `false` | **Retention Daemon Switch**: When `false`, zero automatic deletion occurs (data is retained indefinitely). When set to `true`, background cleanup executes periodically. |
| `DATABASE__RETENTION_DAYS` | `7` | **Retention Window**: Active *only* if `AUTO_PURGE_ENABLED=true` or when executing a manual `/api/stats/purge` sweep. Non-vaulted entries older than this threshold are purged. |

### Source Provenance & Regional Tagging
Region assignment (e.g. `europe`, `apac`, `china`, `north_america`, `middle_east`, `global`) is **not** an error-prone post-hoc keyword guess. It is explicitly configured per-source in `config/sources.yaml` under the `SourceConfig.region` attribute and inherited by all ingested entries.

### 🇨🇳 Dedicated China Intelligence Corridor (中国前沿)
China's rapid AI and cybersecurity advancements are often obscured by language barriers and platform silos. AETHERGUARD integrates a dedicated, first-class **China Radar**:
* **Bilingual Ingestion & Translation Engine**: Chinese feeds (WeChat syndications, ModelScope, QbitAI, Synced, Zhihu, and security research portals) are automatically translated into English with domain-specific terminology post-processing (e.g. mapping "thought chain" $\to$ "Chain-of-Thought (CoT)", "video memory" $\to$ "VRAM", "right escalation" $\to$ "privilege escalation").
* **Researcher Glossary**: Built-in curated bilingual vocabulary (`/api/v1/china/glossary`) covering Chinese ML and threat intelligence jargon.
* **Dual-Track Surveillance**: Tracks both frontier AI engineering (DeepSeek, Qwen/Alibaba, Shanghai AI Lab, ModelScope, Kimi/Moonshot, Zhipu AI) and top-tier cybersecurity research/vulnerability intelligence (Qi-AnXin, Qihoo 360, DarkNavy, Cyber Kunlun, CNNVD).
* **Bilingual Switcher UI**: Frontend cards feature an instant toggle between translated analysis and raw Chinese original title/summary with provenance tags.

---

## 🚀 Production Deployment & Infrastructure Realities

### The Production Truth: SQLite vs. PostgreSQL

1. **Single Worker (`--workers 1`) Requirement**:
   When using SQLite, Uvicorn MUST be run with a single worker process (`--workers 1`). SQLite's Write-Ahead Log (WAL) allows concurrent readers but only one concurrent writer. Multiple worker processes will cause lock contention (`sqlite3.OperationalError: database is locked`) and split the in-memory WebSocket connection state.
2. **Scaling to Multi-Worker / Multi-Node**:
   To run multiple workers or scale horizontally across containers, configure external PostgreSQL:
   ```bash
   DATABASE__URL=postgresql+asyncpg://user:password@host:5432/aetherguard
   ```

### Cloud Hosting Guide

| Provider | Persistence Strategy | Cost | Notes |
|---|---|---|---|
| **Render** | External PostgreSQL | Free | **Important**: Render's *Free Web Service* has an ephemeral filesystem. Persistent disks (`/data`) require an upgraded *Starter* plan ($7/mo). For zero cost, attach a free Neon or Supabase PostgreSQL instance via `DATABASE__URL`. |
| **Fly.io** | Persistent Volume | Free | Mount a 1GB volume at `/data` with `fly volumes create monitor_data -s 1`. Run single-process with SQLite WAL. |
| **Railway** | Persistent Volume | Free tier | Attach a persistent volume to `/data` or use Railway PostgreSQL plugin. |
| **Self-Hosted / Docker** | Bind Mount | Zero | Mount local host volume `./data:/data`. Run natively via Docker or systemd. |

### LLM Analyzer Fallback & Triage Quality
* **Local Default**: Connects to `http://localhost:11434` (Ollama) with `llama3.1:8b` or `qwen2:0.5b`.
* **Cloud Fallback**: When running on cloud platforms without Ollama, the analyzer automatically activates `HeuristicAnalyzer`—a deterministic regex engine computing technical focus, blast radius (1–100), and community velocity with zero external dependencies.
* **Cloud LLM Acceleration**: Set `GROQ_API_KEY` in `.env` to route deep triage through Groq's high-speed inference API (`llama-3.1-70b-versatile`) with sub-second turnaround.

### Priority Queue Durability
The `AutonomousTriageService` manages an in-memory priority queue (`P0` Urgent, `P1` High, `P2` Standard). To prevent silent data loss during container redeployments or host reboots, the service executes `_safe_startup_hydrate()` on boot, automatically re-enqueuing un-triaged high-velocity entries directly from persistent storage.

---

## 🛠️ Installation & Quickstart

### Prerequisites
* Python 3.11 or 3.12
* Git

### Step 1: Clone and Install

```bash
git clone https://github.com/parth2024-tech/cyberversity-tracker.git
cd cyberversity-tracker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with development and CLI dependencies
pip install -e ".[all]"
# Or using uv:
# uv pip install -e ".[all]"
```

### Step 2: Environment Configuration

```bash
cp .env.example .env
```

Key environment variables:
```dotenv
# Server Configuration
API__PORT=8000
API__HOST=0.0.0.0

# Database Storage (SQLite or PostgreSQL)
DATABASE__URL=sqlite+aiosqlite:////data/monitor.db
DATABASE__MAX_INGEST_AGE_DAYS=14
DATABASE__AUTO_PURGE_ENABLED=false
DATABASE__RETENTION_DAYS=7

# Optional: Cloud LLM Inference
GROQ_API_KEY=your_groq_api_key_here

# Optional: Twitter / X Scraper Session Cookies
TWITTER_AUTH_TOKEN=your_auth_token_cookie
TWITTER_CT0=your_ct0_cookie
```

### Step 3: Running via Installed CLI

AETHERGUARD provides a first-class CLI entrypoint (`aetherguard`):

```bash
# Execute an immediate intelligence sweep across all sources
aetherguard sweep

# Display live database metrics and category breakdown
aetherguard stats

# List configured threat feeds and intelligence sources
aetherguard sources

# Start the web dashboard and REST API server
aetherguard server --port 8000
```

---

## 📡 REST API Reference (`/api` and `/api/v1`)

All endpoints are fully versioned and available under both `/api` and `/api/v1` prefixes:

### Core Intelligence & Entries

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/entries` | `GET` | No | List intelligence entries with filtering (`category`, `region`, `hours`, `limit`, `offset`) |
| `/api/v1/entries/{id}` | `GET` | No | Retrieve detailed entry record including extracted text and analysis |
| `/api/v1/entries/{id}` | `DELETE` | **Yes** | Delete entry. Defaults to `hard_delete=true` (permanent). Pass `hard_delete=false` for soft-purge. |
| `/api/v1/entries/batch-delete` | `POST` | **Yes** | Batch delete multiple entries by ID |

### Permanent Vault (Bookmarks & Landmark Papers)

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/vault` | `GET` | No | List all permanently saved Vault entries (`limit`, `offset`, `search`) |
| `/api/v1/vault/{id}` | `POST` | No | Pin an intelligence entry into the permanent Vault |
| `/api/v1/vault/{id}` | `DELETE` | No | Unpin and remove an entry from the permanent Vault |
| `/api/v1/entries/{id}/toggle-vault` | `POST` | No | Legacy toggle endpoint (pin / unpin) |

### Source Management

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/sources` | `GET` | No | List all configured intelligence sources and their current health status |
| `/api/v1/sources` | `POST` | **Yes** | Register a new intelligence feed (`name`, `url`, `category`, `type`, `rate_limit_seconds`) |
| `/api/v1/sources/{id}` | `DELETE` | **Yes** | Remove an intelligence source from the registry |
| `/api/v1/sources/{id}/toggle` | `POST` | No | Enable or disable a specific source (`{"enabled": true/false}`) |
| `/api/v1/fetch` | `POST` | **Yes** | Trigger an immediate manual sweep across all active feeds |

### 🇨🇳 China Intelligence Corridor Endpoints

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/china/overview` | `GET` | No | Aggregated China intelligence telemetry: total signals, category breakdown, monitored frontier labs, and recent highlights |
| `/api/v1/china/glossary` | `GET` | No | Bilingual researcher-grade vocabulary mapping Chinese AI and cybersecurity terms to global standards |
| `/api/v1/entries?category=china` | `GET` | No | Corridor intelligence feed uniting Chinese foundation models, repos, arXiv papers, and cyber threat intelligence |

---

## 🧪 Testing & Verification

AETHERGUARD is covered by **345 automated unit and integration tests** enforcing boundary validation, deduplication contracts, SQL injection resilience, and feed freshness invariants:

```bash
# Run full test suite with enforced coverage threshold
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=75

# Run linter
ruff check .

# Run static type checker
mypy src/
```

### Verified Test Guarantees
* **Cross-Source Deduplication**: Verifies that duplicate wire stories from Hacker News, Reddit, and Google News are correctly clustered via canonical URL normalization, 64-bit SimHash Hamming distance ($\le 4$), and MinHash Jaccard similarity ($\ge 0.35$).
* **Feed Freshness Guard**: Confirms that entries published $> 14$ days ago are rejected at the ingestion boundary.
* **Vault Durability**: Asserts that vaulted entries are immune to automated retention purges unless `include_vaulted=true` is explicitly requested.
* **Scraper Resilience**: Tests session rotation, exponential backoff with jitter, and search syndication fallbacks under simulated HTTP 429/403 conditions.

---

## 🛡️ Production Hardening Checklist

Before deploying AETHERGUARD to a public production environment:

- [ ] **Configure Storage Persistence**: Ensure `/data` is on a persistent volume (Fly/Railway/Starter) or set `DATABASE__URL` to external PostgreSQL (Neon/Supabase).
- [ ] **Enforce Admin Key**: Set `ADMIN_API_KEY` in production. Mutating routes (`DELETE /entries`, `POST /sources`, `/stats/purge`) fail closed if no key is supplied.
- [ ] **Single Worker Guard**: Ensure your Dockerfile or process manager runs `uvicorn` with `--workers 1` when utilizing SQLite.
- [ ] **Configure Cloud LLM Key**: Add `GROQ_API_KEY` if running on headless containers without a local GPU/Ollama instance.
- [ ] **Validate Scraper Credentials**: (Optional) Populate `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` to unlock authenticated query rate limits.

---

## 🗺️ Roadmap & Known Limitations

### Known Limitations
* **SQLite Lock Concurrency**: Running multiple worker processes against SQLite will cause database lock errors. Always use `--workers 1` or migrate to PostgreSQL for multi-process concurrency.
* **Dynamic Scraper Lifespans**: Twitter GraphQL query IDs and Reddit REST endpoints may change without prior notice. The search syndication fallback mitigates this automatically.
* **Pagination**: Intelligence entries currently use `limit` and `offset` pagination. Keyset/cursor-based pagination is planned for high-volume deployments.

### Roadmap
* [x] Multi-source Reddit feed aggregation (`r/LocalLLaMA`, `r/MachineLearning`, `r/OpenSource`, etc.)
* [x] Twitter/X GraphQL scraper with automated guest token activation
* [x] Dedicated Vault API and `/api/v1` versioning
* [ ] Keyset/cursor-based pagination (`before_id` / `since_timestamp`)
* [ ] Multi-tenant watchlists with webhook alert delivery
* [ ] Distributed Celery/Redis worker backend for enterprise-scale deployments

---

## 🤝 Contributing

Contributions to AETHERGUARD are welcome:

1. Fork the repository and create a feature branch (`git checkout -b feat/my-feature`).
2. Adhere strictly to the **Clean Architecture** boundaries (domain models must remain dependency-free).
3. Ensure all tests pass with at least 75% coverage: `pytest tests/ --cov=src --cov-fail-under=75`.
4. Ensure clean linting and typing: `ruff check .` and `mypy src/`.
5. Submit a descriptive Pull Request with conventional commit titles (`feat:`, `fix:`, `docs:`).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
