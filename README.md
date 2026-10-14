# AETHERGUARD // Worldwide AI Ecosystem Intelligence & Frontier Radar

[![CI Status](https://github.com/parth2024-tech/cyberversity-tracker/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/parth2024-tech/cyberversity-tracker/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Tests-314%20Passing-brightgreen.svg?style=flat&logo=pytest&logoColor=white)](https://github.com/parth2024-tech/cyberversity-tracker)
[![Coverage](https://img.shields.io/badge/Coverage-74%25-brightgreen.svg?style=flat&logo=pytest&logoColor=white)](https://github.com/parth2024-tech/cyberversity-tracker)
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

### 1. Trending GitHub Repositories & Open Source
- **Velocity Tracking**: Tracks high-velocity open-source AI projects, autonomous agent runtimes, fine-tuning frameworks, and developer automation codebases.
- **OSS Insight Integration**: Interfaces directly with `api.ossinsight.io` to capture breakout star-gain velocity across open-source AI repositories before mainstream saturation.

### 2. Developer Tooling & Inference Infrastructure
- Dedicated monitoring of high-throughput inference engines and local serving runtimes:
  - **Inference Runtimes**: `vLLM`, `Ollama`, `SGLang`, `llama.cpp`, `TensorRT-LLM`.
  - **Tooling Stacks**: Vector databases, evaluation harnesses, RAG connectors, kernel accelerators, and desktop AI.

### 3. Frontier Foundation Models & Research Breakthroughs
- Real-time intelligence on frontier foundation models and architecture shifts:
  - Open-weights vs. proprietary releases (**DeepSeek**, **Qwen**, **Llama**, **Claude**, **OpenAI**, **Mistral**).
  - Test-time compute scaling, Mixture-of-Experts (MoE), Multi-Head Latent Attention (MLA), and reasoning architectures.
  - Curated arXiv telemetry across `cs.AI`, `cs.CL`, `cs.LG`, and `stat.ML`.

### 4. Community Sentiment & Discussion Intelligence
- **Multi-Subreddit AI Intelligence** (`RedditFetcher`): Ingests community drops from `r/LocalLLaMA`, `r/MachineLearning`, `r/ArtificialIntelligence`, and `r/Singularity`, automatically extracting top discussion comments to capture practitioner reactions.
- **Hacker News Algolia Hydration** (`HackerNewsFetcher`): Enriches top-ranked AI stories by concurrently hydrating top developer comments from Algolia item trees.
- **Keyless Google News AI RSS** (`GoogleNewsFetcher`): Surfaces timely mainstream AI news and enterprise releases with publisher attribution.

### 5. Fair-Share Balanced Digest Allocation
- **Balanced Quota Engine** (`BalancedDigestService`): Dynamically balances digest composition across sources (arXiv, GitHub, Hugging Face, Reddit, Hacker News, Google News, OSS Insight), preventing single high-frequency feeds from dominating the front page.

### 6. Global Sovereign AI & Regional Corridors
- Geographic filtering and coverage across 6 worldwide regional corridors:
  - **North America** (US / CA frontier labs and hyperscalers)
  - **Europe** (Mistral, Kyutai, Aleph Alpha, CERN, EU AI initiatives)
  - **Asia-Pacific** (DeepSeek, Alibaba Qwen, Moonshot, Baidu, South Korea, Japan, India AI)
  - **Latin America**, **Middle East**, and **Africa** (Regional models, compute infrastructure, sovereign labs)

### 7. Ingestion Freshness Guard & Retention Control
- **Strict 14-Day Freshness Guard**: Automatically blocks stale archive dumps and historical entries (`max_ingest_age_days = 14`), ensuring every intelligence entry reflects contemporary advancements.
- **User-Controlled Data Retention**: Automatic background deletions are disabled by default. Data is only purged upon explicit user instruction, with instant soft-restore capabilities.

### 8. Multi-Channel Dispatch & Publishing
- **Discord & Telegram Delivery**: Rich Discord embed dispatcher with severity styling alongside Telegram bot alerts and Slack webhooks.
- **The AI Chronicle & Gazette**: Dedicated responsive reading hub at `/gazette` with synchronized exports in **JSON**, **Markdown**, **HTML**, and vector **PDF** (ReportLab).
- **Glassmorphic Command Center**: Obsidian-themed WebGL HUD with Three.js globe, reactive WebSockets for real-time dispatch alerts, and Command Palette (`Ctrl+K` / `Cmd+K`).

### 9. Privacy Hardening, Administrative Auth & Hardened SSRF Defense
- **Administrative Access Control (`require_admin_auth`)**: Enforces API key verification via `X-Admin-Key` or `Authorization: Bearer <token>` on all mutating endpoints (`/api/stats/purge`, `/api/triage/mode`, `/api/triage/push-all`, `/api/backup/import`, `/api/fetch`). Fails closed in production if unconfigured.
- **SSRF-Protected CORS Proxy (`/api/proxy`)**: Socket-level DNS pinning (`SSRFProtectedTransport`) to eliminate DNS rebinding, manual redirect hop validation (max 5 hops), blocked network filtering (RFC 1918, CGNAT `100.64.0.0/10`, IPv4-mapped IPv6 `::ffff:0:0/96`, `0.0.0.0/8`), 5MB stream cutoff, and sandbox CSP headers (`Content-Security-Policy: ... sandbox`) to prevent stored XSS.
- **Anti-AI-Slop Cleaning Engine** (`AIPromptSanitizer`): Multi-pass regex engine that strips conversational AI preambles ("Here's a 20-word summary:", "This article discusses...", "Sure, here is the technical summary:") and quotation wraps from summaries and gazette dossiers.
- **URL Telemetry Scrubber**: Automatically purges marketing tracking query parameters (`utm_*`, `fbclid`, `gclid`, `twclid`, `srsltid`, `si`, `ref`, `mkt_tok`) during feed ingestion, ensuring canonical cross-source deduplication.
- **YouTube No-Cookie Privacy Rewriting**: Automatically converts multimedia announcement and conference links into `youtube-nocookie.com/embed/` format.
- **Tracking Pixel & Beacon Scrubbing**: Identifies and removes 1x1 tracking pixels and analytics beacon images prior to HTML indexing.

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
│  Value Objects: Priority, Category  │  │  8+ External Fetchers (arXiv, etc.) │
│  Abstract Repository & UoW Ports    │  │  Heuristic & Local LLM Analyzers    │
│  (Pure logic, 0 dependencies)       │  │  Delivery: Discord, Telegram, Slack│
└─────────────────────────────────────┘  └────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                           CROSS-CUTTING UTILITIES                           │
│   core.sanitizer (Anti-Slop, Tracking Purge) │ core.auth (Admin Security)   │
│   core.logging (Structured JSON Logs) │ infrastructure.cache (Hot Cache)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Domain Language & Model Semantics

To align domain models with the Worldwide AI Ecosystem, the `Analysis` entity provides clean property aliases alongside canonical attributes:

| Entity Attribute | Ecosystem Alias | Description |
|---|---|---|
| `attack_vector` | `tech_focus` | Core discipline (e.g. Inference Optimization, Reasoning, Agents) |
| `risk_assessment` | `capability_summary` | Summary of technical advancement or capability breakthrough |
| `threat_velocity` | `velocity_score` | Community adoption / GitHub star velocity (1–100) |
| `blast_radius_score` | `ecosystem_reach` | Estimated ecosystem footprint and dependency depth (0–100) |
| `severity_index` | `severity_index` | Impact score (1–100). Heuristic mode uses deterministic keyword weights; LLM mode produces uncalibrated estimates. |

### Corroboration & Confidence Scoring
- **`Story.confidence_score`**: Calculated deterministically based on independent multi-source corroboration:
  - 1 source: $0.60$ base confidence (single-source claim).
  - 2 sources: $0.85$ corroborated confidence (verified across distinct platforms).
  - 3+ sources: $\min(0.99, 0.85 + (N - 2) \times 0.05)$ consensus score.
- **`Entry` State Mutability**: Uses `@dataclass(kw_only=True)`. While `Entry` has an immutable identity (`id` and SHA-256 `content_hash`), lifecycle state flags (`is_purged`, `purged_at`, `story_id`) are modified via repository methods or `dataclasses.replace()`.

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

The codebase is protected by **314 deterministic automated tests** enforcing strict contracts, SQL injection / XSS fuzzing resilience, boundary enforcement, and feed freshness invariants:

```bash
# Run full test suite
uv run pytest tests/ -q

# Run with coverage report
uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=50

# Run Ruff linter
uv run ruff check .

# Run static type checker
uv run mypy src/
```

### Key Test Guarantees:
- **Administrative Access Control**: Validates that mutating routes reject missing or invalid credentials with 401, support `X-Admin-Key` and `Bearer` tokens, and fail closed in production.
- **Strict Ingestion Freshness**: Verifies that any feed item older than 14 days is strictly excluded at the ingestion boundary.
- **Fair-Share Quota Invariants**: Confirms that balanced digest generation enforces proportional allocations across all configured source categories.
- **Privacy & SSRF Defense Guarantees**: Proves that the CORS proxy enforces DNS pinning, manual redirect hop re-validation, blocks Carrier-Grade NAT (`100.64.0.0/10`), IPv4-mapped IPv6 (`::ffff:0:0/96`), RFC 1918 subnets, aborts payloads > 5MB during streaming, and injects sandbox CSP headers.
- **Anti-AI-Slop & Tracking Purging**: Asserts that conversational AI preambles are removed from LLM summaries, and confirms that marketing tracking parameters (`utm_*`, `fbclid`, `gclid`) are stripped from entry URLs.
- **Data Portability & State Restoration**: Verifies standardized export of Vault intelligence to JSON and validates safe schema-compliant re-importing into SQLite.
- **Exact HTTP Status Contracts**: Strict `422 Unprocessable Entity` on invalid boundaries (`limit > 200`, negative offsets, empty schemas) and `405 Method Not Allowed`.
- **Fuzzing & Injection Resilience**: Resists SQL injection payloads, XSS injections, script tags, control bytes, and Unicode edge cases with zero crashes.
- **Adversarial Priority Heap Testing**: Verifies monotonic non-decreasing priority popping ($P0 \rightarrow P1 \rightarrow P2$) even when items are enqueued in adversarial reverse order.

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

# Optional: PostgreSQL Database
# DATABASE__URL=postgresql+asyncpg://user:pass@host:5432/dbname

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
