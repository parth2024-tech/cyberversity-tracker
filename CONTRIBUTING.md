# Contributing to AETHERGUARD

Thank you for your interest in contributing to **AETHERGUARD**! We welcome contributions that expand, refine, and accelerate worldwide AI ecosystem tracking.

---

## 🌐 Core Project Directives

Before contributing code, please review our foundational design guidelines:

### 1. Worldwide AI Ecosystem Focus (No Cybersecurity/CVE Focus)
- **Primary Scope**:
  - Trending open-source GitHub repositories and agent frameworks.
  - High-performance developer tools, inference runtimes (`vLLM`, `Ollama`, `SGLang`, `llama.cpp`), and evaluation harnesses.
  - Frontier foundation model breakthroughs, reasoning architectures, and sovereign AI initiatives.
- **Strict Policy**: Do **not** focus on or introduce cybersecurity, CVE, vulnerability, or exploit telemetry unless explicitly specified. Keep the focus purely on artificial intelligence research, developer tools, and ecosystem innovations.

### 2. Strict News Freshness (14-Day Guard)
- All ingested intelligence must be fresh (maximum 14 days / 2 weeks old).
- Stale feeds or historical archives older than 14 days are rejected by the ingestion guard.

### 3. User-Controlled Retention
- Automatic background deletion is disabled by default. Data is only soft-purged or hard-deleted upon explicit user command.

---

## 🛠️ Development Setup

### 1. Prerequisites
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip` + `venv`

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/parth2024-tech/cyberversity-tracker.git
cd cyberversity-tracker

# Install dependencies with uv
uv sync --all-extras --dev

# Alternatively with standard venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

---

## 🧪 Testing & Code Quality

All pull requests must pass the CI pipeline (Linting, Static Typing, and Automated Tests):

```bash
# 1. Format and Lint with Ruff
uv run ruff check .
uv run ruff format . --check

# 2. Static Type Check with Mypy
uv run mypy src/ai_security_monitor/ --python-version 3.12

# 3. Run Automated Tests with Pytest
uv run pytest tests/ -q

# 4. Run Coverage Check (Must be >= 50%)
uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=50
```

---

## 🏛️ Code Architecture Standards

- **Domain Layer (`src/ai_security_monitor/domain/`)**: Pure business logic, value objects, domain entities, and abstract interfaces. No dependencies on database or web frameworks.
- **Application Layer (`src/ai_security_monitor/application/`)**: Use cases, workflow orchestrators (`MonitorService`, `AutonomousTriageService`, `NewspaperService`).
- **Infrastructure Layer (`src/ai_security_monitor/infrastructure/`)**: External fetchers, SQLite/SQLAlchemy 2.0 repositories, analyzers, and dispatchers.
- **Presentation Layer (`src/ai_security_monitor/presentation/`)**: FastAPI REST API, WebSocket handlers, and CLI commands.

---

## 📝 Pull Request Checklist

- [ ] Code adheres to the Worldwide AI Ecosystem scope (no CVE/security telemetry).
- [ ] New functionality includes deterministic unit or integration tests in `tests/`.
- [ ] All tests pass cleanly (`pytest`).
- [ ] Ruff and Mypy report zero errors.
- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) format (e.g., `feat: ...`, `fix: ...`, `docs: ...`).
