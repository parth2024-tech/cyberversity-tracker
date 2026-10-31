# AETHERGUARD: Worldwide AI Ecosystem Intelligence Pipeline

[![Build Status](https://img.shields.io/badge/Build-Passing-2ea44f?style=flat-square)](https://github.com/parth2024-tech/cyberversity-tracker/actions)
[![Test Suite](https://img.shields.io/badge/Tests-399%20Passing-brightgreen?style=flat-square)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-79%25-blue?style=flat-square)](tests/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20%2F%20Onion-orange?style=flat-square)](src/ai_security_monitor/domain)

A zero-daemon, deterministic intelligence pipeline and telemetry engine monitoring the global artificial intelligence landscape. Tracks trending open-source repositories, developer tooling, inference engines, curated arXiv preprints, frontier foundation models, and regional sovereign AI initiatives. 100% free with zero paid LLM APIs required.

> **Note on Naming & Repository**:
> The product name is **AETHERGUARD**. The underlying Python package namespace is `ai_security_monitor` (maintained for backward compatibility), and the GitHub repository is hosted at [`cyberversity-tracker`](https://github.com/parth2024-tech/cyberversity-tracker). The automated daily publication is the **AI Gazette**.

---

## 🎯 Primary Scope & Focus Areas

AETHERGUARD focuses strictly on the worldwide artificial intelligence ecosystem across five core verticals:

1. **Trending GitHub Repositories & Agent Frameworks**: High-velocity open-source AI projects, autonomous agent runtimes, orchestration engines, and developer codebases.
2. **Developer Tools & Inference Infrastructure**: High-throughput inference runtimes (`vLLM`, `SGLang`, `llama.cpp`, `Ollama`, `TensorRT-LLM`), evaluation harnesses, vector stores, and RAG connectors.
3. **Top AI Research Papers & Breakthroughs**: Curated arXiv feeds (`cs.AI`, `cs.LG`, `cs.CL`), test-time compute scaling, reasoning architectures, multimodal advancements, and post-training alignment.
4. **Frontier Foundation Models**: Releases, technical reports, reasoning milestones, open weights vs. proprietary releases (DeepSeek, Claude, OpenAI, Qwen, Llama, Mistral).
5. **Global Sovereign AI & Regional Ecosystems**: National AI compute clusters, robotics laboratories, AI accelerator hardware, and startup ecosystems across Europe, APAC, China, the Middle East, and the Americas.

---

## ⏱️ Mandatory News Freshness Invariant ($\le 14$ Days)

AETHERGUARD enforces a strict **14-day freshness guard** (`DATABASE__MAX_INGEST_AGE_DAYS=14`) across all fetchers, scrapers, and external syndication feeds:
* **Ingestion Filter**: Any RSS item, arXiv preprint, or community post published $> 14$ days ago is rejected at the network boundary.
* **Syndication Feeds**: RSS 2.0 (`/feed.xml`) and JSON Feed 1.1 (`/feed.json`) syndicate only fresh entries within the rolling 14-day window.
* **Historical CSV Export**: The CSV export engine (`/api/export.csv`) supports querying full historical archives upon request while defending against spreadsheet formula injection.

---

## 🏛️ Clean Architecture

AETHERGUARD is engineered following **Clean / Onion Architecture**. Domain entities and repository ports remain isolated from external network scrapers, database drivers, and web delivery protocols.

```text
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                         PRESENTATION LAYER (INBOUND)                        │
 │  FastAPI REST API (/api & /api/v1)  │  Syndication (/feed.xml, /feed.json)  │
 │  CSV Export Engine (/api/export.csv)│  WebSocket Live Event Bus (/ws)       │
 │  Installed Typer CLI (aetherguard)  │  Model Context Protocol (MCP stdio)   │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                        APPLICATION SERVICES LAYER                           │
 │  MonitorService (Orchestrator)      │  AutonomousTriageService (P0-P2 Queue)│
 │  ArticleExtractor (Trafilatura)     │  VaultFeedbackService (User Affinity) │
 │  WeeklyBriefService (What Changed)  │  NewspaperService (Daily AI Gazette)  │
 │  SchedulerService (Cron / Interval) │  BalancedDigestService (Multi-Pillar) │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                                DOMAIN CORE                                  │
 │  Entities: Entry, Source, Digest    │  Repositories & Unit of Work (Ports)  │
 │  Value Objects: Category, Priority  │  Deduplication: SimHash & MinHash     │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                     INFRASTRUCTURE ADAPTERS (OUTBOUND)                      │
 │  SQLAlchemy 2.0 Async Repositories  │  SQLite WAL with FTS5 Full-Text Search│
 │  Resilient Scraper Engine           │  10+ Fetchers (arXiv, GitHub, Hugging)│
 │  Heuristic & Local LLM Analyzers    │  Delivery: Telegram, Discord, Slack   │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Resilient Ingestion Engine (`infrastructure/scrapers` & `fetchers`)

To ensure reliability without relying on brittle third-party services, AETHERGUARD integrates native scrapers and fetchers:

```text
src/ai_security_monitor/infrastructure/
├── fetchers/
│   ├── arxiv_fetcher.py              # Official arXiv API + RSS fallback
│   ├── github_trending_fetcher.py     # GitHub Trending scrape & velocity tracking
│   ├── huggingface_trending_fetcher.py# Hugging Face models & daily papers
│   ├── google_news_fetcher.py        # Curated regional and lab search topics
│   ├── hackernews_fetcher.py          # Firebase API with score & comment thresholds
│   └── rss_fetcher.py                 # Multi-feed syndication with ETag & 304 handling
├── scrapers/
│   ├── core/session_pool.py          # HTTP/2 client with retry backoff and TLS spoofing
│   ├── core/rate_limiter.py          # Exponential backoff with jitter & Retry-After parsing
│   └── extractors/                   # Normalized models for community discussions
└── database/
    ├── connection.py                 # SQLite WAL connection manager with FTS5
    └── repositories.py               # Optimized SQLAlchemy repositories with sub-ms FTS5
```

### Search & Ingestion Safeguards
* **SQLite FTS5 Full-Text Search**: Native full-text index with trigram and CJK regex tokenization (`[\w\u4e00-\u9fff]+`) ensuring sub-10ms search queries and graceful fallback to ILIKE for short tokens.
* **Idempotent Ingestion**: Content-addressable hashing and MinHash Jaccard deduplication prevent duplicate entries across overlapping syndication sources.
* **Dual-Bridge Fallback**: When direct network endpoints encounter rate limits (HTTP 429), fetchers gracefully fall back to alternative syndication bridges to maintain uninterrupted coverage.

---

## ⚙️ Configuration & Retention Controls

AETHERGUARD provides flexible retention and ingestion controls via environment variables:

| Setting | Default | Purpose & Behavior |
|---|---|---|
| `DATABASE__MAX_INGEST_AGE_DAYS` | `14` | **Ingestion Freshness Guard**: Drops entries published $> 14$ days ago. Ensures feeds only contain fresh AI developments. |
| `DATABASE__AUTO_PURGE_ENABLED` | `false` | **Retention Daemon Switch**: When `false`, data is preserved until explicit cleanup. When `true`, background retention purge is active. |
| `DATABASE__RETENTION_DAYS` | `7` | **Retention Window**: Active when `AUTO_PURGE_ENABLED=true` or via manual purge. Vaulted landmark entries are preserved. |
| `API__ADMIN_API_KEY` | *(None)* | **Admin Authentication**: Required on mutating endpoints (`POST /weekly/generate`, `DELETE /entries/{id}`, `POST /sources`). |

---

## 🇨🇳 Dedicated China AI Corridor (中国前沿)

China represents a critical hub for open-source foundation models (DeepSeek, Qwen, Moonshot/Kimi, Zhipu AI, ModelScope) that are frequently obscured by language barriers:
* **Bilingual Translation Engine**: Automatically translates technical Chinese announcements into English with domain-specific terminology mapping (e.g. "thought chain" $\to$ "Chain-of-Thought (CoT)", "video memory" $\to$ "VRAM").
* **Researcher Glossary**: Standardized bilingual vocabulary accessible via `/api/v1/china/glossary`.
* **Zero-Compute Static Export**: Generates a pre-compiled JSON snapshot (`data/china_radar.json`) accessible via `/api/v1/china/export` for CDN caching and dashboard delivery.

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
```

### Step 2: Configure Environment

```bash
cp .env.example .env
```

Key environment settings in `.env`:
```dotenv
# API Server Configuration
PORT=8080
API__PORT=8080
API__HOST=0.0.0.0

# Database Storage (SQLite WAL)
DATA_DIR=/tmp/aetherguard_data
DATABASE__MAX_INGEST_AGE_DAYS=14
DATABASE__AUTO_PURGE_ENABLED=false
DATABASE__RETENTION_DAYS=7

# Admin Key for Write Operations
ADMIN_API_KEY=your_secure_admin_key_here
```

### Step 3: Run via CLI

```bash
# Execute an intelligence sweep across all configured AI feeds
aetherguard sweep

# Display database metrics and category breakdown
aetherguard stats

# List configured sources and status
aetherguard sources

# Start the web dashboard and REST API server
aetherguard server --port 8080
```

---

## 📡 REST API & Syndication Reference

All endpoints are available under both `/api` and `/api/v1` prefixes:

### Core Intelligence & Entries

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/entries` | `GET` | No | List entries with filters (`category`, `lab`, `region`, `tier`, `q`, `from`, `to`, `limit`, `offset`) |
| `/api/v1/entries/{id}` | `GET` | No | Retrieve detailed entry record including extracted abstract and metadata |
| `/api/v1/entries/{id}` | `DELETE` | **Yes** | Delete entry (defaults to permanent deletion) |
| `/api/v1/entries/batch-delete` | `POST` | **Yes** | Batch delete multiple entries by ID |

### Syndication Feeds & CSV Export

| Endpoint | Method | Rate Limit | Description |
|---|---|:---:|---|
| `/feed.xml` / `/rss.xml` | `GET` | None | Standards-compliant RSS 2.0 XML feed ($\le 14$ days freshness guard) |
| `/feed.json` | `GET` | None | JSON Feed 1.1 syndication stream for feed readers and automation bots |
| `/api/export.csv` | `GET` | 30/min | RFC 4180 CSV export with formula injection defense and historical filtering |
| `/api/digest/weekly` | `GET` | None | Retrieve Weekly 'What Changed' Intelligence Brief (JSON or Markdown) |
| `/api/digest/weekly/generate` | `POST` | **Yes** | Generate and persist Weekly Briefing to disk (`data/briefs/YYYY-WW.md`) |

### Permanent Vault (Landmark Research & Models)

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/vault` | `GET` | No | List all permanently vaulted landmark entries (`limit`, `offset`, `search`) |
| `/api/v1/vault/{id}` | `POST` | No | Pin an intelligence entry into the permanent Vault |
| `/api/v1/vault/{id}` | `DELETE` | No | Unpin an entry from the permanent Vault |

### Source Management & China Radar

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/sources` | `GET` | No | List configured intelligence sources and health states |
| `/api/v1/sources` | `POST` | **Yes** | Register a new source feed (`name`, `url`, `category`, `type`) |
| `/api/v1/china/overview` | `GET` | No | China AI radar telemetry: monitored labs, models, and recent breakthroughs |
| `/api/v1/china/glossary` | `GET` | No | Bilingual researcher vocabulary mapping Chinese ML terms |
| `/api/v1/china/export` | `GET` | None | Pre-compiled static JSON snapshot (`data/china_radar.json`) |

---

## 🧪 Testing & Verification

AETHERGUARD is verified by **399 automated unit and integration tests** ensuring data integrity, deduplication, formula injection prevention, and zero-daemon operation:

```bash
# Run full test suite
poetry run pytest

# Run Ruff linter
poetry run ruff check .

# Run static type checker
poetry run mypy src/
```

### Verified Guarantees
* **14-Day Freshness Guard**: Confirms stale historical items ($> 14$ days) are blocked at the ingestion boundary.
* **CSV Formula Defense**: Ensures all user and feed text starting with `=`, `+`, `-`, `@`, `\t`, `\r` is neutralized via single-quote escaping.
* **Zero Paid APIs**: 100% deterministic local heuristics, BM25 scoring, and regex analyzers with zero external LLM API dependency.
* **Vault Immunity**: Asserts vaulted milestone papers are protected from automated retention sweeps.

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
