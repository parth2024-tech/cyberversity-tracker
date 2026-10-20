# AETHERGUARD // Worldwide AI Ecosystem Intelligence & Frontier Radar

[![CI Status](https://github.com/parth2024-tech/cyberversity-tracker/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/parth2024-tech/cyberversity-tracker/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Tests-334%20Passing-brightgreen.svg?style=flat&logo=pytest&logoColor=white)](https://github.com/parth2024-tech/cyberversity-tracker)
[![Coverage](https://img.shields.io/badge/Coverage-75%25-brightgreen.svg?style=flat&logo=pytest&logoColor=white)](https://github.com/parth2024-tech/cyberversity-tracker)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Code Style: Ruff](https://img.shields.io/badge/Code%20Style-Ruff-black.svg?style=flat)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/Type%20Checked-Mypy-blue.svg?style=flat)](http://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)

**AETHERGUARD** is an autonomous intelligence radar that tracks, synthesizes, and broadcasts breakthroughs across the worldwide artificial intelligence ecosystem in real time.

Built on Clean Domain-Driven Architecture (DDD), it continuously aggregates open-source repositories, developer infrastructure, inference runtimes, test-time compute scaling papers, community discussion sentiment, and sovereign AI initiatives from every major global tech corridor.

🌐 **Production Deployment**: [https://ai-security-radar.onrender.com/](https://ai-security-radar.onrender.com/)

---

## 🌐 Core Intelligence Focus & Capabilities

### 1. Trending GitHub Repositories & Hugging Face Drops
- **Multi-Source Velocity Tracking**: Tracks breakout open-source AI projects, autonomous agent runtimes, fine-tuning frameworks, and developer automation codebases across GitHub and Hugging Face.
- **Language-Targeted Scrapers (`GitHubTrendingFetcher`)**: Scrapes multi-ecosystem trending targets including Python, TypeScript, and global repositories, extracting direct canonical project links.
- **Hugging Face Model Radar (`HuggingFaceTrendingFetcher`)**: Ingests trending foundation model checkpoints and open weights directly from Hugging Face Hub.
- **OSS Insight Integration**: Interfaces directly with `api.ossinsight.io` to capture star-gain velocity across repositories before mainstream saturation.

### 2. Resilient Twitter / X Intelligence Scraper Engine
- **Internal GraphQL Timeline Extraction (`TwitterGraphQLExtractor`)**: Targets Twitter's web GraphQL endpoints (`SearchTimeline`, `UserTweets`) with universal web bearer authorization and structured feature flags.
- **Session & Guest Token Pool (`SessionPool`)**: Supports optional account pools (`auth_token`, `ct0`) alongside automated anonymous guest token activation (`/1.1/guest/activate.json`) for public timeline access.
- **Nested Tree Unwinding**: Unpacks `TimelineAddEntries`, unescapes longform note tweets beyond 280 characters, and preserves media, expanded external links, and author metrics.
- **High-Recall Syndication Fallback**: Automatically activates a search syndication bridge if direct access encounters Cloudflare blocks or login walls, guaranteeing 100% continuous data delivery.
- **Targeted Radar Profiles**: Actively monitors key research curators (`@_akhaliq`, `@sama`, `@karpathy`, `@ylecun`, `@deepseek_ai`) and tracking queries across reasoning models, agent runtimes, and inference engines.

### 3. Multi-Subreddit Community Discussion Sentiment
- **Multi-Community Coverage (`RedditFetcher`)**: Gathers practitioner feedback and drops from 6 dedicated subreddits:
  - `r/LocalLLaMA` (Open-weights & local model quantizations)
  - `r/MachineLearning` (Peer research discussions & benchmark reviews)
  - `r/Singularity` (Frontier AGI milestones & frontier model drops)
  - `r/ArtificialIntelligence` (Global AI trends & industry shifts)
  - `r/OpenSource` (Open-source AI frameworks & tooling)
  - `r/BestGitHubRepos` (Trending open-source projects)
- **Multi-Tier Fallback Ladder**: Automatically falls back to high-recall search feeds if direct Reddit endpoints encounter HTTP 429 rate limits or 403 blocks.
- **Discussion Thread Hydration (`RedditEndpointsExtractor`)**: Extracts top developer comments and reaction summaries from `/comments/{id}.json` threads.

### 4. Developer Tooling & Inference Infrastructure
- Dedicated monitoring of high-throughput inference engines and local serving runtimes:
  - **Inference Runtimes**: `vLLM`, `Ollama`, `SGLang`, `llama.cpp`, `TensorRT-LLM`.
  - **Tooling Stacks**: Vector databases, evaluation harnesses, RAG connectors, kernel accelerators, and desktop AI.

### 5. Frontier Foundation Models & Research Breakthroughs
- Real-time intelligence on frontier foundation models and architecture shifts:
  - Open-weights vs. proprietary releases (**DeepSeek**, **Qwen**, **Llama**, **Claude**, **OpenAI**, **Mistral**).
  - Test-time compute scaling, Mixture-of-Experts (MoE), Multi-Head Latent Attention (MLA), and reasoning architectures.
  - Curated arXiv telemetry across `cs.AI`, `cs.CL`, `cs.LG`, and `stat.ML`.

### 6. Hacker News & Web Intelligence
- **Hacker News Algolia Hydration** (`HackerNewsFetcher`): Enriches top-ranked AI stories by concurrently hydrating top developer comments from Algolia item trees.
- **Keyless Google News AI RSS** (`GoogleNewsFetcher`): Surfaces timely mainstream AI news and enterprise releases with publisher attribution.

### 7. Fair-Share Balanced Digest Allocation
- **Balanced Quota Engine** (`BalancedDigestService`): Dynamically balances digest composition across sources (arXiv, GitHub, Hugging Face, Twitter/X, Reddit, Hacker News, Google News, OSS Insight), preventing single high-frequency feeds from dominating the front page.

### 8. Global Sovereign AI & Regional Corridors
- Geographic filtering and coverage across 6 worldwide regional corridors:
  - **North America** (US / CA frontier labs and hyperscalers)
  - **Europe** (Mistral, Kyutai, Aleph Alpha, CERN, EU AI initiatives)
  - **Asia-Pacific** (DeepSeek, Alibaba Qwen, Moonshot, Baidu, South Korea, Japan, India AI)
  - **Latin America**, **Middle East**, and **Africa** (Regional models, compute infrastructure, sovereign labs)

### 9. Ingestion Freshness Guard & Retention Control
- **Strict 14-Day Freshness Guard**: Automatically blocks stale archive dumps and historical entries (`max_ingest_age_days = 14`), ensuring every intelligence entry reflects contemporary advancements.
- **User-Controlled Data Retention**: Automatic background deletions are disabled by default. Data is only purged upon explicit user instruction, with instant soft-restore capabilities.

### 10. Multi-Channel Dispatch & Publishing
- **Discord & Telegram Delivery**: Rich Discord embed dispatcher with severity styling alongside Telegram bot alerts and Slack webhooks.
- **The AI Chronicle & Gazette**: Dedicated responsive reading hub at `/gazette` with synchronized exports in **JSON**, **Markdown**, **HTML**, and vector **PDF** (ReportLab).
- **Glassmorphic Command Center**: Obsidian-themed WebGL HUD with Three.js globe, reactive WebSockets for real-time dispatch alerts, and Command Palette (`Ctrl+K` / `Cmd+K`).

---

## 🏛️ Clean Architecture & Project Structure

The codebase strictly adheres to Clean / Onion Architecture where the Domain Core sits at the center with zero external dependencies, surrounded by Application Services, and decoupled from outer infrastructure and presentation adapters:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION ADAPTERS (INBOUND)                    │
│   FastAPI REST Routers │ WebSockets (/ws) │ Typer CLI │ Stdio MCP Server    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ calls
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                            APPLICATION SERVICES                             │
│   MonitorService │ AutonomousTriageService │ BalancedDigestService          │
│   NewspaperService │ SchedulerService │ VaultFeedbackService                │
│   (Coordinates use cases; depends strictly on Domain interfaces)             │
└──────────────────┬──────────────────────────────────────▲───────────────────┘
                   │ invokes                              │ implements
┌──────────────────▼──────────────────┐  ┌────────────────┴───────────────────┐
│             DOMAIN CORE             │  │   INFRASTRUCTURE ADAPTERS (OUTBOUND)│
│  Entities: Entry, Source, Analysis  │  │  SQLAlchemy 2.0 Async Repositories  │
│  Value Objects: Priority, Category  │  │  Scraper Engine (GraphQL / REST)    │
│  Abstract Repository & UoW Ports    │  │  10+ Fetchers (X, Reddit, arXiv)    │
│  (Pure logic, 0 dependencies)       │  │  Heuristic & Local LLM Analyzers    │
│                                     │  │  Delivery: Discord, Telegram, Slack │
└─────────────────────────────────────┘  └────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                           CROSS-CUTTING UTILITIES                           │
│   core.sanitizer (Anti-Slop, Tracking Purge) │ core.auth (Admin Security)   │
│   core.logging (Structured JSON Logs) │ infrastructure.cache (Hot Cache)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Resilient Scraper Package (`infrastructure/scrapers`)

```text
src/ai_security_monitor/infrastructure/scrapers/
├── config/
│   ├── headers.py            # Static public web bearer token, browser impersonation headers
│   └── queries.py            # Reverse-engineered Twitter GraphQL Query IDs & feature flags
├── core/
│   ├── session_pool.py       # Manages auth_token, ct0, and guest token activation/rotation
│   ├── client.py             # Resilient HTTP/2 client with retry logic and TLS header spoofing
│   └── rate_limiter.py       # Exponential backoff with full jitter and Retry-After header parsing
├── models/
│   ├── tweet.py              # Pydantic schemas for normalized tweets, metrics, and authors
│   └── reddit_post.py        # Pydantic schemas for Reddit posts, authors, and comment trees
└── extractors/
    ├── twitter_graphql.py    # Unwinds nested GraphQL timeline trees and longform note tweets
    └── reddit_endpoints.py   # Unwinds Reddit REST post listings and comment trees
```

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.12+**
- **uv** (recommended) or **pip** & **virtualenv**
- *(Optional)* **Ollama** installed locally for GPU-accelerated local LLM triage.

### 2. Installation

Using `uv` (recommended):
```bash
# Clone repository
git clone https://github.com/parth2024-tech/cyberversity-tracker.git
cd cyberversity-tracker

# Synchronize dependencies with uv
uv sync --all-extras --dev
```

Or using standard `venv` and `pip`:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

### 3. Run the Web Command Center
```bash
# Launch FastAPI server with live WebSockets
python3 cli.py server --port 8000
```
Open your browser at **`http://localhost:8000`** (or **`http://localhost:8000/gazette`** for the Gazette).

---

## 🛠️ CLI Reference

The platform provides a Typer-powered CLI for administration, sweeps, and agent integration:

```bash
# Launch the real-time web command center and API server
python3 cli.py server --port 8000 --host 0.0.0.0

# Execute an immediate worldwide intelligence sweep
python3 cli.py fetch
python3 cli.py fetch --force

# Display real-time database intelligence statistics and metrics
python3 cli.py stats

# List all registered and configured intelligence sources
python3 cli.py sources

# Launch Model Context Protocol (MCP) server over stdio for AI coding assistants
python3 cli.py mcp
```

---

## 📡 REST API & WebSocket Endpoints

| Endpoint | Method | Auth Required | Description |
|---|---|---|---|
| `/api/health` | `GET` | No | Service status and SQLite WAL connectivity |
| `/api/entries` | `GET` | No | Query entries with pagination (`limit <= 200`), search, region, and sorting |
| `/api/entries/{id}/vault` | `POST` | No | Pin/star an entry into the permanent Vault |
| `/api/entries/{id}` | `DELETE` | **Yes (Admin)** | Delete a single intelligence entry |
| `/api/entries/batch-delete` | `POST` | **Yes (Admin)** | Batch delete multiple intelligence entries |
| `/api/entries/export/pdf` | `GET` | No | Export filtered intelligence stream as a styled PDF report |
| `/api/triage/queue` | `GET` | No | Retrieve live priority queue telemetry (`queue_size`, `hold_until_sweep`) |
| `/api/triage/push-all` | `POST` | **Yes (Admin)** | Immediately drain priority queue and push all items to the website |
| `/api/triage/mode` | `POST` | **Yes (Admin)** | Toggle queue hold mode (`hold=true/false`) |
| `/api/triage/clear` | `POST` | **Yes (Admin)** | Clear in-memory priority queue |
| `/api/triage/prioritize-frontier` | `POST` | **Yes (Admin)** | Enqueue high-priority frontier models and research |
| `/api/fetch` | `POST` | **Yes (Admin)** | Trigger a Live Sweep: fetches fresh feeds and pushes queued items |
| `/api/newspaper/latest` | `GET` | No | Fetch latest AI Gazette edition in JSON |
| `/api/newspaper/export/pdf` | `GET` | No | Download latest AI Gazette edition as a publication-ready PDF |
| `/api/digest` | `POST` | No | Compile and dispatch an intelligence digest to configured delivery adapters |
| `/api/proxy` | `GET` | No | SSRF-protected CORS proxy to safely preview external articles with sandbox CSP |
| `/api/backup/export` | `GET` | No | Export portable system backup (vaulted items, sources, state) as JSON |
| `/api/backup/import` | `POST` | **Yes (Admin)** | Safely import and synchronize intelligence state from external backup |
| `/api/stats/retention` | `GET` | No | Inspect data age distribution and purge candidates |
| `/api/stats/purge` | `POST` | **Yes (Admin)** | Execute manual purge (`older_than_days`, `hard_delete`, `include_vaulted`) |
| `/api/stats/restore-purged` | `POST` | **Yes (Admin)** | Instantly restore soft-deleted items back to active status |
| `/ws` | `WebSocket` | No | Live bi-directional streaming for new discoveries, sweeps, and queue updates |

---

## 🧪 Testing & Quality Assurance

The codebase is protected by **334 deterministic automated tests** enforcing strict contracts, SQL injection / XSS fuzzing resilience, boundary enforcement, and feed freshness invariants:

```bash
# Run full test suite
pytest tests/ -q

# Run with coverage report
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=50

# Run Ruff linter
ruff check .

# Run static type checker
mypy src/
```

### Key Test Guarantees:
- **Resilient Scraper Architecture**: Verifies session pool token rotation, rate limiter backoff calculation with jitter, HTTP `Retry-After` header parsing, and GraphQL timeline unwrapping.
- **Multi-Tier Feed Fallback**: Asserts that Reddit and Twitter fetchers automatically fall back to search syndication upon rate-limiting or network blocks.
- **Strict Ingestion Freshness**: Verifies that any feed item older than 14 days is strictly excluded at the ingestion boundary.
- **Administrative Access Control**: Validates that mutating routes reject missing or invalid credentials with 401, support `X-Admin-Key` and `Bearer` tokens, and fail closed in production.
- **Fair-Share Quota Invariants**: Confirms that balanced digest generation enforces proportional allocations across all configured source categories.
- **Privacy & SSRF Defense Guarantees**: Proves that the CORS proxy enforces DNS pinning, manual redirect hop re-validation, blocks Carrier-Grade NAT (`100.64.0.0/10`), IPv4-mapped IPv6 (`::ffff:0:0/96`), RFC 1918 subnets, aborts payloads > 5MB during streaming, and injects sandbox CSP headers.
- **Anti-AI-Slop & Tracking Purging**: Asserts that conversational AI preambles are removed from summaries, and confirms that marketing tracking parameters (`utm_*`, `fbclid`, `gclid`) are stripped from entry URLs.
- **Data Portability & State Restoration**: Verifies standardized export of Vault intelligence to JSON and validates safe schema-compliant re-importing into SQLite.
- **Exact HTTP Status Contracts**: Strict `422 Unprocessable Entity` on invalid boundaries (`limit > 200`, negative offsets, empty schemas) and `405 Method Not Allowed`.

---

## ⚙️ Configuration & Deployment

System parameters can be configured via environment variables or a `.env` file:

```env
# Server
PORT=8000
ENVIRONMENT=production
ADMIN_API_KEY=your-secure-admin-secret-token

# Database & Persistent Storage (Render Disk mounted at /data)
DATA_DIR=/data
DATABASE__URL=sqlite+aiosqlite:////data/monitor.db
DATABASE__MAX_INGEST_AGE_DAYS=14
DATABASE__AUTO_PURGE_ENABLED=false
DATABASE__RETENTION_DAYS=7

# Twitter / X Scraper Authentication (Optional - anonymous guest tokens used by default)
TWITTER_AUTH_TOKEN=your_auth_token_cookie
TWITTER_CT0=your_ct0_cookie

# Ingestion & Triage
ANALYZER__AUTONOMOUS_TRIAGE_ENABLED=true
ANALYZER__QUEUE_HOLD_UNTIL_SWEEP=true
ANALYZER__OLLAMA_BASE_URL=http://localhost:11434
ANALYZER__OLLAMA_MODEL=llama3.1:8b

# Dispatchers (Optional)
DISCORD__WEBHOOK_URL=your_discord_webhook_url
TELEGRAM__BOT_TOKEN=your_bot_token
TELEGRAM__CHAT_ID=your_chat_id
SLACK__WEBHOOK_URL=your_webhook_url
```

### Render Deployment & Reliability
- **Persistent Disk Storage**: Set up in [`render.yaml`](./render.yaml) with a 1GB disk mounted at `/data` and `DATA_DIR=/data`. This ensures SQLite databases and Gazette PDF broadsheets survive all container redeployments and restarts.
- **External Cron Trigger**: On free-tier cloud instances that sleep when idle, configure an external cron job (e.g. cron-job.org or GitHub Actions) to send an authenticated `POST /api/fetch` request with header `X-Admin-Key: <ADMIN_API_KEY>` every 5 hours to wake up the service and execute sweeps.

```bash
# Production start with Uvicorn
uvicorn ai_security_monitor.presentation.api.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
```

---

## 📄 License

Distributed under the **MIT License**. Free and open-source for researchers, developers, and AI enthusiasts.
