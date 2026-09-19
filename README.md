# AETHERGUARD // Worldwide AI Ecosystem Intelligence & Frontier Radar

[![Live Radar](https://img.shields.io/badge/Live%20Radar-Online-00ffcc?style=for-the-badge&logo=render&logoColor=black)](https://ai-security-radar.onrender.com/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-193%20Passing-brightgreen.svg?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org)
[![Code Style: Ruff](https://img.shields.io/badge/Code%20Style-Ruff-black.svg?style=flat)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/Type%20Checked-Mypy-blue.svg?style=flat)](http://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)

**AETHERGUARD** is a high-performance, autonomous intelligence radar that tracks, synthesizes, and broadcasts breakthroughs across the worldwide artificial intelligence ecosystem in real time.

Built on Clean Domain-Driven Architecture (DDD), it continuously aggregates open-source repositories, frontier foundation models, inference runtimes, test-time compute scaling papers, and sovereign AI initiatives from every major global tech corridor.

🌐 **Production Deployment**: [https://ai-security-radar.onrender.com/](https://ai-security-radar.onrender.com/)

---

## 🌐 Core Intelligence Focus & Capabilities

### 1. Trending GitHub Repositories & Open Source
- Autonomously tracks high-velocity AI repositories, agent runtimes, fine-tuning frameworks, and developer automation codebases.
- Identifies breakthrough projects and surging stars before mainstream industry saturation.

### 2. Developer Tooling & Inference Infrastructure
- Dedicated monitoring of high-throughput inference engines and local serving runtimes:
  - **Inference Runtimes**: `vLLM`, `Ollama`, `SGLang`, `llama.cpp`, `TensorRT-LLM`.
  - **Tooling Stacks**: Vector stores, evaluation harnesses, RAG frameworks, kernel accelerators, and desktop AI.

### 3. Frontier AI Foundation Models & Reasoning Breakdowns
- Real-time intelligence on next-generation model releases, architecture shifts, and benchmark breakthroughs:
  - Open-weights vs. proprietary releases (**DeepSeek**, **Qwen**, **Llama**, **Claude**, **OpenAI**, **Mistral**).
  - Test-time compute scaling, Mixture-of-Experts (MoE), Multi-Head Latent Attention (MLA), and reasoning models.

### 4. Global Sovereign AI & Regional Corridors
- Geographic filtering and coverage across 6 worldwide regional corridors:
  - **North America** (US / CA frontier labs and hyperscalers)
  - **Europe** (Mistral, Aleph Alpha, CERN, EU AI initiatives)
  - **Asia-Pacific** (DeepSeek, Alibaba Qwen, Moonshot, Baidu, South Korea & Japan AI)
  - **Latin America**, **Middle East**, and **Africa** (Regional models, infrastructure, sovereign compute)

### 5. Autonomous Priority Triage & Queue Hold Engine
- **Priority-Tiered Ingestion**:
  - **P0**: Frontier foundation models and seminal reasoning papers.
  - **P1**: Developer tooling, inference runtimes, and core infrastructure.
  - **P2**: General ecosystem news and broader applications.
- **Queue Hold Mode**: Discovered items accumulate cleanly in the background priority queue (`• QUEUED (N)`) until explicitly pushed via **Live Sweep** or the **Push All Queued** action, preventing notification fatigue and unreviewed feed churn.

### 6. The AI Chronicle & Gazette Publishing
- **Web Edition**: Dedicated responsive reading hub at `/gazette` with editorial styling, executive summaries, and key architectural highlights.
- **Multi-Format Export**: Generates synchronized editions in **JSON**, **Markdown**, **HTML**, and publication-grade vector **PDF** (powered by ReportLab).

### 7. User-Controlled Data Retention & Hygiene
- **Strict User Control**: Automatic background data deletion is disabled by default. Data is only modified upon explicit user command.
- **Ingestion Freshness Guard**: Automatically prevents stale feed archive dumps (> 90 days old) from polluting the active database.
- **Flexible Cleanup**: Support for soft-purge with instant one-click restoration, or permanent raw disk wiping (`hard_delete=True`).

### 8. Real-Time Glassmorphic Command Center
- Obsidian-themed HUD with Three.js WebGL globe, reactive WebSockets for real-time dispatch alerts, synthetic Web Audio chimes, and instant Command Palette (`Ctrl+K` / `Cmd+K`).

---

## 🏛️ Clean Architecture & Project Structure

The codebase strictly adheres to Domain-Driven Design (DDD) with decoupled layers:

```
ai-security-monitor/
├── cli.py                                 # Unified CLI management entrypoint
├── pyproject.toml                         # Project metadata, Ruff, mypy, & pytest configurations
├── config/
│   └── sources.yaml                       # Configured worldwide feed sources & regional tags
├── src/
│   └── ai_security_monitor/
│       ├── domain/                        # Pure business entities, enums, & value objects
│       │   ├── entities.py                # Entry, Analysis, Source, SourceType, Category
│       │   ├── repositories.py            # Abstract repository & Unit-of-Work interfaces
│       │   └── value_objects.py           # Priority, Ecosystem, Region types
│       ├── application/                   # Use cases, application services, & workflow coordination
│       │   └── services/
│       │       ├── monitor_service.py     # Main ingestion orchestrator & freshness guard
│       │       ├── autonomous_triage_service.py # PriorityQueue worker & queue hold engine
│       │       ├── newspaper_service.py   # AI Gazette publisher (PDF, HTML, MD, JSON)
│       │       └── scheduler_service.py   # Scheduled recurring background sweep runner
│       ├── infrastructure/                # External adapters, persistence, fetchers, & analyzers
│       │   ├── database/                  # SQLAlchemy 2.0 async engine, models, WAL SQLite
│       │   ├── fetchers/                  # RSS, arXiv, GitHub API, HackerNews, Web scrapers
│       │   ├── analyzers/                 # Heuristic fast-path & Ollama/LLM neural analyzers
│       │   └── delivery/                  # Telegram bot, Slack webhooks, HTML email dispatchers
│       └── presentation/                  # User interface & public contracts
│           └── api/
│               ├── main.py                # FastAPI application factory & middleware
│               ├── limiter.py             # SlowAPI rate limiting configuration
│               └── routers/               # REST routers (entries, triage, stats, newspaper, sources)
├── web/                                   # Frontend Single Page Application
│   ├── index.html                         # Primary Command Center HUD
│   ├── gazette.html                       # The AI Chronicle & Gazette reader
│   └── js/                                # WebSocket receiver, palette, & interactive controls
└── tests/                                 # Industrial automated test suite (193 tests)
    ├── unit/                              # Isolated entity, analyzer, and domain tests
    └── integration/                       # Brutal API stress, boundary contracts, and DB tests
```

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.11+**
- **pip** and **virtualenv**
- *(Optional)* **Ollama** installed locally for GPU-accelerated local LLM triage.

### 2. Installation
```bash
# Clone repository
git clone https://github.com/parth2024-tech/cyberversity-tracker.git
cd cyberversity-tracker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Web Command Center
```bash
# Launch FastAPI server with live WebSockets
python3 cli.py server --port 8000
```
Open your browser at **`http://localhost:8000`** (or **`http://localhost:8000/gazette`** for the Gazette).

---

## 🛠️ CLI Reference

The platform provides a comprehensive CLI for administration, sweeps, and exports:

```bash
# Initialize SQLite database and load source feeds
python3 cli.py init

# Execute an immediate worldwide intelligence sweep
python3 cli.py fetch

# Display current intelligence statistics and source health
python3 cli.py stats

# Generate The AI Chronicle Gazette (HTML, JSON, Markdown, PDF)
python3 cli.py newspaper --pdf

# Dispatch an intelligence digest to console or messaging channels
python3 cli.py digest --method console
python3 cli.py digest --method telegram --telegram-token <TOKEN> --telegram-chat <CHAT_ID>
python3 cli.py digest --method slack --slack-webhook <WEBHOOK_URL>

# Manage data retention and storage cleanup
python3 cli.py retention status
python3 cli.py retention purge --older-than 30
```

---

## 📡 REST API & WebSocket Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/entries` | `GET` | Query entries with pagination (`limit <= 200`), search, region, and sorting (`newest`, `velocity`, `top`) |
| `/api/entries/{id}/vault` | `POST` | Pin/star an entry into the permanent Vault |
| `/api/entries/export/pdf` | `GET` | Export filtered intelligence stream as a styled PDF report |
| `/api/triage/status` | `GET` | Retrieve live priority queue telemetry (`queue_size`, `hold_until_sweep`, `total_enqueued`) |
| `/api/triage/push-all` | `POST` | Immediately drain priority queue and push all items to the website |
| `/api/triage/mode` | `POST` | Toggle or query queue hold mode (`hold=true/false`) |
| `/api/fetch` | `POST` | Trigger a Live Sweep: fetches fresh feeds and pushes queued items |
| `/api/newspaper/latest` | `GET` | Fetch latest AI Gazette edition in JSON |
| `/api/newspaper/export/pdf` | `GET` | Download latest AI Gazette edition as a publication-ready PDF |
| `/api/stats/retention` | `GET` | Inspect data age distribution and purge candidates |
| `/api/stats/purge` | `POST` | Execute manual purge (`older_than_days`, `hard_delete`, `include_vaulted`) |
| `/api/stats/restore-purged` | `POST` | Instantly restore soft-deleted items back to active status |
| `/ws` | `WebSocket` | Live bi-directional streaming for new discoveries, sweeps, and queue updates |

---

## 🧪 Testing & Quality Assurance

The codebase is protected by **193 brutal, deterministic automated tests** enforcing strict contracts, SQL injection / XSS fuzzing resilience, boundary enforcement, and heap priority invariants:

```bash
# Run full test suite
pytest -q

# Run with coverage report
pytest --cov=ai_security_monitor --cov-report=term-missing

# Run Ruff linter
ruff check .

# Run static type checker
mypy src/ai_security_monitor tests
```

### Brutal Test Guarantees:
- **Exact HTTP Status Contracts**: Strict `422 Unprocessable Entity` on invalid boundaries (`limit > 200`, negative offsets, empty schemas) and `405 Method Not Allowed`.
- **Fuzzing & Injection Resilience**: Resists SQL injection payloads, XSS injections, script tags, control bytes, and Unicode edge cases with zero crashes.
- **Adversarial Priority Heap Testing**: Verifies monotonic non-decreasing priority popping ($P0 \rightarrow P1 \rightarrow P2$) even when items are enqueued in adversarial reverse order.
- **Physical Disk Wipe Verification**: Executes raw SQL checks against SQLite to prove complete removal of hard-deleted entries.

---

## ⚙️ Configuration

System parameters can be configured via environment variables or a `.env` file:

```env
# Server
PORT=8000
ENVIRONMENT=production

# Database
DATABASE__URL=sqlite+aiosqlite:///./data/monitor.db
DATABASE__MAX_INGEST_AGE_DAYS=90
DATABASE__AUTO_PURGE_ENABLED=false
DATABASE__RETENTION_DAYS=7

# Ingestion & Triage
ANALYZER__AUTONOMOUS_TRIAGE_ENABLED=true
ANALYZER__QUEUE_HOLD_UNTIL_SWEEP=true
ANALYZER__OLLAMA_BASE_URL=http://localhost:11434
ANALYZER__OLLAMA_MODEL=llama3.1:8b

# Dispatchers (Optional)
TELEGRAM__BOT_TOKEN=your_bot_token
TELEGRAM__CHAT_ID=your_chat_id
SLACK__WEBHOOK_URL=your_webhook_url
```

---

## 🚀 Deployment

The platform is designed for zero-maintenance containerized or direct cloud deployment (Render, Railway, Fly.io, or VPS):

```bash
# Production start with Uvicorn
uvicorn ai_security_monitor.presentation.api.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
```

Render auto-builds from `requirements.txt` and starts via the start command specified in the dashboard.

---

## 📄 License

Distributed under the **MIT License**. Free and open-source for researchers, developers, and AI enthusiasts.

