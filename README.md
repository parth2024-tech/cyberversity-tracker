# AETHERGUARD: Worldwide AI Ecosystem Intelligence Pipeline

[![Build Status](https://img.shields.io/badge/Build-Passing-2ea44f?style=flat-square)](https://github.com/parth2024-tech/cyberversity-tracker/actions)
[![Test Suite](https://img.shields.io/badge/Tests-474%20Passing-brightgreen?style=flat-square)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-79%25-blue?style=flat-square)](tests/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20%2F%20Onion-orange?style=flat-square)](src/ai_security_monitor/domain)
[![Cost](https://img.shields.io/badge/Cost-%240%2Fmo%20Zero--Cloud-success?style=flat-square)](README.md#-100-free--zero-cost-architecture-0month-law)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

A high-recall, zero-daemon intelligence pipeline, telemetry engine, and real-time command center monitoring the global artificial intelligence landscape. Tracks frontier foundation models, reasoning breakthroughs, open-weight architectures, developer infrastructure, inference engines, arXiv preprints, and regional sovereign AI initiatives.

> **Note on Naming & Repository**:
> The project product name is **AETHERGUARD**. The underlying Python package namespace is `ai_security_monitor` (preserved for backward compatibility), the GitHub repository is hosted at [`cyberversity-tracker`](https://github.com/parth2024-tech/cyberversity-tracker), the primary command-line interface is `aetherguard`, and the continuous publication engine publishes the **Global AI Gazette**.

---

## 🎯 Primary Scope & Focus Areas

AETHERGUARD focuses strictly on the worldwide artificial intelligence ecosystem across five core verticals:

1. **Frontier Foundation Models**: Model family releases, reasoning architectures, test-time compute scaling, and open weights (DeepSeek, Qwen, Claude, Llama, Mistral, OpenAI).
2. **Inference Runtimes & Infrastructure**: High-throughput inference engines (`vLLM`, `SGLang`, `llama.cpp`, `Ollama`, `TensorRT-LLM`), memory-efficient kernels, and serving frameworks.
3. **Trending Repositories & Open Source**: High-velocity GitHub repositories, autonomous agent frameworks, tool-use systems, and developer libraries.
4. **Research Breakthroughs & Preprints**: Curated arXiv feeds, model architecture innovations, synthetic data pipelines, and post-training alignment.
5. **Sovereign AI & Regional Ecosystems**: National AI compute clusters, regional labs, hardware accelerators, and sovereign AI initiatives across Europe, APAC, China, the Middle East, and the Americas.

---

## 💎 Core Architectural Guarantees

### 1. 🛡️ 14-Day Freshness Window (Ingestion Boundary Guard)
All intelligence entries, GitHub discoveries, and research breakthroughs must be fresh (maximum 14 days old). The pipeline's Ingestion Freshness Guard strictly enforces `DATABASE__MAX_INGEST_AGE_DAYS=14`, automatically dropping historical RSS items, stale archive dumps, and obsolete syndications before they touch the database.

### 2. 💸 100% Free & Zero-Cost Architecture ($0/Month Law)
AETHERGUARD runs perpetually with **zero monthly subscription bills, zero commercial API keys, and zero paid SaaS dependencies**:
* **Local Silicon Inference**: Native SLM support via Ollama / llama.cpp (`qwen2.5-coder:7b`, `llama3.1:8b`).
* **Generous Free Tiers**: Seamless integration with Groq free-tier cloud inference for sub-second headless execution.
* **Direct Public RPCs**: Built-in HTTP RPC connectors (e.g. Google GTX endpoints) with zero credential requirements.
* **Embedded Offline Translation**: In-process neural machine translation via Argos Translate with custom AI token shielding (`<ai_token_N>`), preserving code snippets, model names, and math notation intact.

### 3. ⚡ Local-First On-Demand Process Governance (Arch Linux Rulebook)
Strictly adheres to the Supreme Law of On-Demand Systems: **Do not run a background service just because it exists.**
* When you launch `./scripts/run_local.sh` or `python -m ai_security_monitor server --port 8080`, the command center starts on-demand.
* When you close the terminal or issue `Ctrl+C`, all workers, threads, and child processes terminate cleanly with zero lingering daemons or battery-draining pollers.

### 4. 🪶 Memory-Hardened & Container OOM Resilient (Render 512MB RAM Protection)
Engineered to operate reliably within strict memory constraints (e.g. Render 512MB free-tier containers):
* **Cgroup-Aware Autoscaled Pool**: Monitors host memory limits and process RSS, adjusting concurrency dynamically.
* **Bounded SQLite Engine**: Clamps SQLite WAL memory to 4MB cache, 32MB mmap, FILE `temp_store`, and `wal_autocheckpoint=100`.
* **Zero-Daemon Vector Fallback**: Employs an ultra-fast 384-dimensional deterministic pseudo-vector fallback on low-memory hosts when heavyweight ONNX / FastEmbed models exceed container thresholds.
* **Garbage Collection Cadence**: Actively clears ReportLab canvas dictionaries and invokes `gc.collect()` following scheduled sweeps.

---

## 🏛️ System Architecture

AETHERGUARD is engineered according to **Clean / Onion Architecture**. Domain models, value objects, and business rules remain strictly decoupled from database drivers, network scrapers, and external UI frameworks.

```text
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                         PRESENTATION LAYER (INBOUND)                        │
 │  FastAPI REST API (/api & /api/v1)  │  WebSocket Event Bus (/ws)            │
 │  Installed Typer CLI (aetherguard)  │  Model Context Protocol (MCP stdio)   │
 │  Progressive Web App (PWA & HUD)    │  Telegram Two-Way ChatOps Webhook     │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                        APPLICATION SERVICES LAYER                           │
 │  MonitorService (Orchestrator)      │  AutonomousTriageService (Tiered SLM) │
 │  KnowledgeGraphService (Entities)   │  ChinaRepoIntelligence (Archetypes)   │
 │  TranslationService (Argos/GTX)     │  VaultFeedbackService (Rocchio)       │
 │  SchedulerService (Cron / Interval) │  NewspaperService (Daily AI Gazette)  │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                                DOMAIN CORE                                  │
 │  Entities: Entry, Source, Analysis  │  Repositories & Unit of Work (Ports)  │
 │  EntityRecord & Benchmark Triples   │  Multi-Tier Deduplication Engines     │
 │  Value Objects: Category, Priority  │  SimHash (64-bit), MinHash, Vectors   │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    │
 ┌──────────────────────────────────▼──────────────────────────────────────────┐
 │                     INFRASTRUCTURE ADAPTERS (OUTBOUND)                      │
 │  SQLAlchemy 2.0 Async Repositories  │  SQLite WAL / PostgreSQL Driver       │
 │  Resilient Scraper & TLS Fallback   │  200+ Feeds (GitHub, arXiv, Hugging)  │
 │  Fast-Fail SLM Circuit Breaker      │  Multi-Channel Delivery (TG/Discord)  │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Key Functional Pillars

### 1. 🧠 Structured AI Entity & Benchmark Knowledge Graph (`/api/v1/entities`)
A relational knowledge graph powered by the `entry_entities` table automatically extracts, links, and indexes AI entities across incoming streams:
* **Entity Types**: Tracks `model`, `repository`, `benchmark`, `organization`, and `hardware`.
* **Bidirectional Benchmark Extraction**: Extracts evaluation scores (e.g. `SWE-bench: 49.2%`, `AIME 2024: 79.8%`, `HumanEval: 92.4%`, `GSM8K: 95.1%`) alongside contextual snippet proofs.
* **Longest-First Span Suppression**: Eliminates false-positive substring duplicate matches (e.g. prevents matching `MMLU` inside `MMLU-Pro`).
* **Entity Timelines**: Chronological trajectories and citation velocity tracking over the 14-day freshness window.

### 2. 🇨🇳 Dedicated China AI Open-Source Corridor (`/api/v1/china`)
China's fast-moving AI ecosystem is often obscured by language barriers and platform fragmentation. AETHERGUARD provides first-class surveillance:
* **Epistemic Repository Profiling**: Categorizes repositories by architectural archetype (`foundation_model`, `inference_runtime`, `agentic_system`, `rag_knowledge_base`, `multimodal_voice`, `eval_and_benchmark`, `dev_tool`).
* **Lab Authority Mapping**: Tracks premier organizations including DeepSeek, Alibaba Qwen, Shanghai AI Lab, Zhipu AI, Moonshot AI, InfiniFlow, and ModelScope.
* **Bilingual Translation Corridor**: In-process Argos Translate neural translation with domain terminology alignment (mapping Chinese ML expressions into global equivalents like Chain-of-Thought, VRAM, and MoE).
* **Chinese GitHub Trending Scraper**: Captures trending Chinese repositories using native spoken-language filtering (`zh`) and bilingual keyword matching.

### 3. 🤖 Tiered SLM Triage & Prompt Caching Engine
* **Fast-Fail Circuit Breaker**: Probes local Ollama / llama.cpp daemon with a strict $\le 500\text{ms}$ connection timeout and a 300-second cooldown recovery. When local daemons are offline, requests fail fast to heuristic or cloud inference without blocking sweeps.
* **Structured Output Resilience**: Small models (3B–7B) frequently output markdown code fences, conversational preambles, or trailing commas. The parser applies regex fence stripping, comma repair, and balanced bracket extraction.
* **Prompt Caching Prefix Isolation**: Isolates static system prompts at index 0, maximizing cache hits on OpenAI, Gemini, and Groq inference endpoints.

### 4. 📱 Telegram ChatOps & Two-Way Interactive Callbacks (`/api/v1/telegram`)
* **Interactive Inline Keyboards**: Telegram alert messages feature interactive inline buttons:
  * `[📌 Vault Entry]` (`cb:vault:<uuid>`) — Bookmark entry into permanent storage.
  * `[🚫 Dismiss]` (`cb:dismiss:<uuid>`) — Soft-purge entry from live feed.
  * `[↩️ Undo]` (`cb:undo:<uuid>`) — Restore accidentally dismissed entries.
  * `[📰 Gazette]` (`cb:digest:md`) — Request on-demand markdown summary.
  * `[🔄 Unquarantine]` (`cb:unquarantine:<slug>`) — Instantly restore quarantined feeds.
* **Source Auto-Quarantine Circuit Breaker**: If a feed fails $\ge 5$ consecutive sweeps, the circuit trips to `QUARANTINED`, suspends polling for 12 hours, and sends an alert with an instant unquarantine button.

### 5. 📰 Autonomous Daily AI Gazette & Multi-Channel Publishing
* **Print-Ready PDF Generation**: ReportLab-powered publication engine formatting the latest 5-hour or daily edition into an elegant broadsheet.
* **Neural Audio Broadcast**: Broadcast-grade audio briefings synthesized via Microsoft Edge Neural TTS with Google TTS fallback (`/api/v1/audio/briefing`).
* **Interactive Gazette Web View**: Clean, newspaper-style layout accessible at `/gazette`.
* **Universal Syndication Feeds**: Standard RSS 2.0 (`/feed.xml`) and JSON Feed 1.1 (`/feed.json`) streams for feed readers and automation bots.

---

## 🔌 Model Context Protocol (MCP) Server

AETHERGUARD includes a built-in JSON-RPC 2.0 stdio server compliant with the **Model Context Protocol (MCP)** specification. AI coding assistants (Claude Desktop, Antigravity, Cursor) can directly query the live AI ecosystem:

```bash
# Launch MCP server directly over stdio
aetherguard mcp
# or via python module:
python -m ai_security_monitor mcp
```

### Exposed MCP Tools

| Tool Name | Parameters | Purpose |
|---|---|---|
| `get_worldwide_ai_news` | `limit: int`, `category: str` | Retrieve fresh ($< 14$ days) curated AI releases, model announcements, and tools. |
| `query_ai_entity_timeline` | `name: str`, `entity_type: str`, `days: int`, `limit: int` | Chronological trajectory and benchmark history for an AI model or repository. |
| `get_top_ai_entities` | `entity_type: str`, `days: int`, `limit: int` | Most cited models, benchmarks, and libraries ranked by 14-day frequency. |
| `get_source_health_telemetry` | *none* | Operational health, latency metrics, and crawl delays across monitored feeds. |
| `convert_html_to_markdown` | `html_content: str`, `base_url: str` | Strip scripts and boilerplate, converting raw HTML into LLM-ready markdown. |
| `sanitize_ai_prompt` | `text: str` | Defuse prompt injections, strip zero-width characters, and clean untrusted web input. |

### Claude Desktop Integration Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aetherguard": {
      "command": "python",
      "args": ["-m", "ai_security_monitor", "mcp"],
      "cwd": "/path/to/cyberversity-tracker"
    }
  }
}
```

---

## 🔍 Resilient Scraper Engine (`infrastructure/scrapers`)

To overcome the fragility of dynamic platforms without paying for commercial scraping APIs, AETHERGUARD features an internal scraping suite:

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

### Browser TLS Impersonation & Fallback Continuity
* **Browser Impersonation (`curl_cffi`)**: On Cloudflare or HTTP 403 challenges, requests seamlessly fall back to `curl_cffi` using Chrome 131 TLS/JA3 impersonation.
* **Search Syndication Bridge**: If Twitter GraphQL or Reddit JSON endpoints return HTTP 429 (Rate Limited), fetchers automatically fall back to Google News syndication bridges (`site:x.com ... when:14d` and `site:reddit.com/r/{sub} when:14d`), guaranteeing 100% data continuity.

---

## ⚙️ Configuration & Ingestion Controls

AETHERGUARD provides straightforward environment configuration via `.env` or system environment variables:

| Setting | Default | Description |
|---|---|---|
| `DATABASE__MAX_INGEST_AGE_DAYS` | `14` | **Ingestion Freshness Guard**: Drops entries published > 14 days ago. |
| `DATABASE__AUTO_PURGE_ENABLED` | `false` | **Retention Daemon**: When `false`, zero automatic deletion occurs. |
| `DATABASE__RETENTION_DAYS` | `7` | **Retention Window**: Active *only* if `AUTO_PURGE_ENABLED=true` or manual purge. |
| `DATABASE__URL` | `sqlite+aiosqlite:////data/monitor.db` | Async SQLAlchemy database connection string. |
| `SCHEDULER__ENABLED` | `true` | Starts the background polling scheduler. |
| `SCHEDULER__INTERVAL_MINUTES` | `60` | Interval between scheduled intelligence sweeps. |
| `ANALYZER__AUTONOMOUS_TRIAGE_ENABLED` | `true` | Enables background priority queue worker for deep triage. |
| `DELIVERY__TELEGRAM_ENABLED` | `false` | Enables Telegram delivery and two-way ChatOps. |
| `DELIVERY__TELEGRAM_MODE` | `poll` | Transport mode for Telegram: `poll` (long-polling) or `webhook`. |
| `ADMIN_API_KEY` | `""` | Optional key to protect mutating REST endpoints (`DELETE`, `POST /sources`). |
| `GROQ_API_KEY` | `""` | Optional free-tier cloud LLM inference key. |

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

### Step 3: Run Locally (On-Demand)

```bash
# Start the on-demand Command Center and Web HUD on port 8080:
./scripts/run_local.sh

# Or start directly using the installed CLI:
aetherguard server --port 8080
```

Open `http://127.0.0.1:8080` in your browser. All workers terminate cleanly when you press `Ctrl+C`.

### Step 4: CLI Operations

```bash
# Execute an immediate intelligence sweep across all 200+ sources
aetherguard sweep

# Display live database metrics and category breakdown
aetherguard stats

# List configured intelligence sources and health status
aetherguard sources

# Reconcile database sources against config/sources.yaml
python scripts/reconcile_sources.py --apply
```

---

## 📡 Complete REST API Reference (`/api` and `/api/v1`)

All endpoints are fully versioned and available under both `/api` and `/api/v1` prefixes:

### 1. Core Intelligence & Entries

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/entries` | `GET` | No | List intelligence entries with filtering (`category`, `region`, `hours`, `limit`, `offset`) |
| `/api/v1/entries/{id}` | `GET` | No | Retrieve detailed entry record including extracted text and analysis |
| `/api/v1/entries/{id}` | `DELETE` | **Yes** | Delete entry (`hard_delete=true` for permanent, `false` for soft-purge) |
| `/api/v1/entries/batch-delete` | `POST` | **Yes** | Batch delete multiple entries by ID |
| `/api/v1/entries/{id}/notes` | `POST` | No | Attach researcher notes to an entry |
| `/api/v1/entries/{id}/deep-analysis` | `GET` | No | Execute on-demand deep LLM triage on an individual entry |
| `/api/v1/entries/export/pdf` | `GET` / `POST` | No | Export filtered intelligence entries to a branded PDF report |

### 2. Structured Knowledge Graph & Benchmarks

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/entities/timeline` | `GET` | No | Query chronological mention timeline and benchmark metrics for an AI entity |
| `/api/v1/entities/top` | `GET` | No | Retrieve top referenced AI models, benchmarks, and repos ranked by 14-day frequency |
| `/api/v1/entities/entry/{entry_id}` | `GET` | No | Retrieve structured entities and evaluation triples extracted for a specific entry |

### 3. Permanent Vault & Personalization

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/vault` | `GET` | No | List all permanently saved Vault entries (`search`, `category`, `limit`, `offset`) |
| `/api/v1/vault/{id}` | `POST` | No | Pin an intelligence entry into the permanent Vault |
| `/api/v1/vault/{id}` | `DELETE` | No | Unpin and remove an entry from the permanent Vault |
| `/api/v1/vault/profile` | `GET` | No | View current Rocchio user preference centroid vector and top keyword weights |
| `/api/v1/vault/profile/refresh` | `POST` | No | Recompute personalization weights from positive (vaulted) and negative signals |

### 4. 🇨🇳 China AI Open-Source Corridor

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/china/overview` | `GET` | No | Aggregated China intelligence telemetry: signal counts, monitored labs, and highlights |
| `/api/v1/china/trending` | `GET` | No | Trending Chinese open-source GitHub repositories filterable by `archetype` and `lab` |
| `/api/v1/china/glossary` | `GET` | No | Bilingual researcher-grade vocabulary mapping Chinese ML terms to global standards |
| `/api/v1/china/export` | `GET` | No | Export static JSON snapshot (`data/china_radar.json`) for zero-compute CDN hosting |

### 5. Translation Engine

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/translate` | `POST` | No | Translate arbitrary text into English with automatic language detection |
| `/api/v1/translate/entry/{id}` | `POST` | No | Translate an existing database entry and preserve original text in metadata |
| `/api/v1/translate/backfill` | `POST` | No | Backfill English translations for un-translated foreign language entries |

### 6. Daily AI Gazette & Audio Briefings

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/newspaper/latest` | `GET` | No | Retrieve metadata and content of the latest 5-hour broadsheet edition |
| `/api/v1/newspaper/latest/html` | `GET` | No | Render latest broadsheet directly in browser as print-ready HTML |
| `/api/v1/newspaper/download` | `GET` | No | Download latest edition as Markdown (`.md`), HTML (`.html`), or PDF (`.pdf`) |
| `/api/v1/newspaper/editions` | `GET` | No | List historical archived newspaper editions |
| `/api/v1/newspaper/generate` | `POST` | No | Manually trigger compilation and publication of a fresh edition |
| `/api/v1/newspaper/email` | `POST` | No | Email the latest newspaper PDF document to a specified recipient |
| `/api/v1/audio/briefing` | `GET` | No | Stream high-quality neural voice audio briefing synthesized via Edge-TTS |
| `/api/v1/audio/synthesize` | `POST` | No | Synthesize custom text into an MP3 audio stream |

### 7. Sources & Telemetry

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/sources` | `GET` | No | List all registered intelligence feeds, categories, and health states |
| `/api/v1/sources/health` | `GET` | No | Real-time health metrics: success rates, consecutive failures, and quarantine status |
| `/api/v1/sources` | `POST` | **Yes** | Register a new intelligence feed (`name`, `url`, `category`, `type`) |
| `/api/v1/sources/{id}` | `DELETE` | **Yes** | Remove an intelligence source from the registry |
| `/api/v1/sources/{id}/toggle` | `POST` | No | Enable or disable a specific source (`{"enabled": true/false}`) |
| `/api/v1/fetch` | `POST` | **Yes** | Trigger an immediate manual sweep across all active feeds |
| `/api/v1/stats` | `GET` | No | Overview of total entries, categories, and active source counts |
| `/api/v1/stats/source-yield` | `GET` | No | Performance metrics ranking sources by new entries yielded |
| `/api/v1/stats/token-savings` | `GET` | No | Total tokens and cost saved via local SLM triage and deduplication |
| `/api/v1/stats/purge` | `POST` | **Yes** | Manually execute retention purge on non-vaulted entries |

### 8. Autonomous Triage & SLM Queue

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/triage/queue` | `GET` | No | Inspect status, size, and rate metrics of the autonomous triage queue |
| `/api/v1/triage/enqueue/{id}` | `POST` | No | Enqueue a specific entry for deep triage via local SLM or Groq |
| `/api/v1/triage/clear` | `POST` | **Yes** | Flush the in-memory triage queue to eliminate backlogs |
| `/api/v1/triage/prioritize-frontier`| `POST` | No | Prioritize un-triaged frontier foundation model entries in the queue |

### 9. Telegram ChatOps

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/api/v1/telegram/webhook` | `POST` | Secret Token | Inbound Telegram webhook receiver for two-way interactive callbacks |
| `/api/v1/telegram/status` | `GET` | No | Inspect Telegram transport mode (`poll`/`webhook`) and polling status |

### 10. Syndication Feeds & Backup Portability

| Endpoint | Method | Admin Auth | Description |
|---|---|:---:|---|
| `/feed.xml` / `/api/v1/feed.xml` | `GET` | No | Standards-compliant RSS 2.0 XML feed of worldwide AI ecosystem intelligence |
| `/feed.json` / `/api/v1/feed.json` | `GET` | No | JSON Feed 1.1 syndication stream for modern news clients |
| `/api/v1/digest/markdown` | `GET` | No | Structured Markdown intelligence briefing (`days`, `min_velocity`) |
| `/api/v1/backup/export` | `GET` | No | Export all Vault entries and configured sources into portable JSON |
| `/api/v1/backup/import` | `POST` | **Yes** | Import backup package safely with schema validation |

---

## 🧪 Testing & Verification

AETHERGUARD is verified by **474 automated unit and integration tests** enforcing boundary validation, deduplication contracts, SQL injection resilience, and feed freshness invariants:

```bash
# Run the full test suite with coverage enforcement
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=75

# Run linter
ruff check .

# Run static type checker (0 errors across 146 source files)
mypy src/
```

### Verified Test Guarantees
* **Cross-Source Deduplication**: Verifies that duplicate wire stories from Hacker News, Reddit, and Google News are correctly clustered via canonical URL normalization, 64-bit SimHash Hamming distance ($\le 4$), and MinHash Jaccard similarity ($\ge 0.35$).
* **Feed Freshness Guard**: Confirms that entries published $> 14$ days ago are rejected at the ingestion boundary.
* **Vault Durability**: Asserts that vaulted entries are immune to automated retention purges unless `include_vaulted=true` is explicitly requested.
* **Scraper Resilience**: Tests session rotation, exponential backoff with jitter, and search syndication fallbacks under simulated HTTP 429/403 conditions.
* **Structured Parsing**: Validates that malformed JSON responses from SLMs are automatically stripped and repaired.

---

## 🚀 Production Deployment & Scaling

### SQLite WAL Single Worker Guard
When using SQLite, Uvicorn MUST be run with a single worker process (`--workers 1`):
* SQLite's Write-Ahead Log (WAL) allows concurrent readers but only one concurrent writer.
* Multiple worker processes will cause database lock contention (`sqlite3.OperationalError: database is locked`) and split the in-memory WebSocket connection state.

### Scaling to Multi-Worker / PostgreSQL
To scale horizontally across multiple container instances or workers, configure external PostgreSQL:
```bash
DATABASE__URL=postgresql+asyncpg://user:password@host:5432/aetherguard
```

### Cloud Hosting Guide

| Platform | Recommended Storage | Cost | Architecture Notes |
|---|---|---|---|
| **Local Machine** | Local SQLite WAL (`./data/monitor.db`) | $0 | On-demand execution with zero background services (`./scripts/run_local.sh`). |
| **Fly.io** | Persistent Volume (`/data`) | Free tier | Mount 1GB volume with `fly volumes create monitor_data -s 1`. Run `--workers 1`. |
| **Render** | External PostgreSQL (Neon/Supabase) | Free tier | Render's free tier has an ephemeral filesystem. Connect free serverless Postgres via `DATABASE__URL`. Memory-hardened for 512MB RAM. |
| **Railway** | Persistent Volume or Postgres plugin | Free tier | Attach persistent volume to `/data` or provision Railway Postgres. |
| **Docker / Self-Hosted**| Host bind mount (`./data:/data`) | $0 | Standard docker-compose or systemd service setup. |

---

## 🗺️ Roadmap

- [x] Multi-source Reddit feed aggregation (`r/LocalLLaMA`, `r/MachineLearning`, `r/OpenSource`, etc.)
- [x] Twitter/X GraphQL scraper with automated guest token activation & search fallback
- [x] Dedicated Vault API and `/api/v1` clean versioning
- [x] Structured AI Entity & Benchmark Knowledge Graph (`entry_entities`)
- [x] China AI Open-Source Corridor with Epistemic Archetype Profiling & Bilingual Translation
- [x] 100% Free Offline Translation via Argos Translate with AI Token Shielding
- [x] Telegram ChatOps with Two-Way Inline Callbacks and Source Auto-Quarantine Circuit Breaker
- [x] Model Context Protocol (MCP) stdio server for AI coding assistants
- [x] Local-first on-demand runner and Render 512MB RAM OOM hardening
- [ ] Keyset / cursor-based pagination (`before_id` / `since_timestamp`) for high-volume sweeps
- [ ] Webhook outbound alert subscriptions for custom framework watchlists

---

## 🤝 Contributing

Contributions to AETHERGUARD are welcome:

1. Fork the repository and create a feature branch (`git checkout -b feat/my-feature`).
2. Adhere strictly to **Clean Architecture** boundaries (domain models must remain dependency-free).
3. Ensure all tests pass with at least 75% coverage: `pytest tests/ --cov=src --cov-fail-under=75`.
4. Verify clean linting and typing: `ruff check .` and `mypy src/`.
5. Submit a descriptive Pull Request with conventional commit titles (`feat:`, `fix:`, `docs:`).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
