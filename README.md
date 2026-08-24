# AETHER-GUARD // Autonomous AI Security & Threat Radar

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A zero-cost, high-level **Autonomous AI Security Intelligence Platform & Real-Time Threat Radar**. Aggregates, analyzes, cross-correlates, and broadcasts real-time threat intelligence across AI technology launches, CVEs, arXiv academic zero-days, and cybersecurity feeds.

---

## ⚡ Key Highlights & Core Capabilities

1. **Autonomous AI Correlation & Blast Radius Engine (AI × CVE Intersection)**:
   - Computes cross-correlation between security disclosures and AI stacks/frameworks (`PyTorch`, `Transformers`, `LangChain`, `Ollama`, `LlamaIndex`, `vLLM`, `DeepSeek`, `FastAPI`).
   - Calculates **Blast Radius (1-100)** and affected software components.

2. **Pre-CVE Zero-Day Early Warning Detector**:
   - Scans academic arXiv research papers (`cs.CR`, `cs.AI`, `stat.ML`) for novel pre-CVE weaponization vectors (*Jailbreaks, Prompt Injections, RAG Poisoning, Model Inversion, Backdoors*).
   - Tags **Attack Archetype** and **Weaponization Potential** before official CVE assignments.

3. **Autonomous AI Triage & De-Noise Agent**:
   - Scores threats with **Threat Velocity Index (1-100)** and **Severity Index (1-100)**.
   - Extracts exact **Attack Vector**, **Tangible Risk Assessment**, and immediate **Mitigation Patch**.

4. **Real-Time Interactive Command Center (WebSockets)**:
   - Modern dark glassmorphic command center (`web/index.html`).
   - Real-time slide-in pop-up alert system with synthetic Web Audio chimes.
   - Live Chart.js intelligence distribution, instant search, and source health manager.

5. **Multi-Channel Dispatch Engine**:
   - Dispatches structured daily/weekly intelligence digests to **Telegram Bot API**, **Slack Webhooks**, and **Email (HTML)**.

---

## 🚀 Quick Start

### 1. Installation
```bash
git clone https://github.com/parth2024-tech/cyberversity-tracker.git
cd cyberversity-tracker

# Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Launch the Web Command Center & Live Radar
```bash
python3 cli.py server --port 8000
```
Open your browser at **`http://localhost:8000`**

### 3. CLI Operations
```bash
# Initialize database and sources
python3 cli.py init

# Perform an immediate intelligence sweep
python3 cli.py fetch

# Generate console digest
python3 cli.py digest --method console

# Send digest to Telegram
python3 cli.py digest --method telegram --telegram-token <BOT_TOKEN> --telegram-chat <CHAT_ID>

# View statistics
python3 cli.py stats
```

---

## 📁 Architecture

```
ai-security-monitor/
├── cli.py                  # Unified CLI management entrypoint
├── config/
│   └── sources.yaml        # Feed sources, rate limits, delivery configs
├── src/
│   ├── analyzer.py         # Blast Radius Engine, Pre-CVE Detector & AI Triage Agent
│   ├── database.py         # SQLite WAL persistence with deduplication & LEFT JOIN analysis
│   ├── fetchers.py         # Multi-channel fetchers (RSS, arXiv, HN, NVD, CISA KEV, GHSA)
│   ├── delivery.py         # Telegram, Slack, Email (HTML), Console dispatchers
│   ├── monitor.py          # Pipeline orchestration & auto-analysis engine
│   └── server.py           # FastAPI server with WebSocket streaming & REST endpoints
└── web/
    └── index.html          # Cyber command center SPA with real-time toast engine
```

---

## 📄 License
MIT License. Free for open-source research and personal development.
