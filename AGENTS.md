# Project Core Directive: Worldwide AI Ecosystem Focus

## ⚠️ MANDATORY RULE: Do NOT Focus on Security / Cybersecurity
- **CRITICAL DIRECTIVE**: From now on, DO NOT focus on the cybersecurity, vulnerability, CVE, exploit, or threat intelligence part of this project.
- This is a personal preference of the user: **ONLY and ONLY focus on security when the user explicitly says so.**
- When generating reports, newsletters, dashboard updates, features, or digests, omit security/CVE/vulnerability items unless explicitly instructed by the user.

## ⚠️ MANDATORY RULE: News Freshness (Max 2 Weeks Old / 14 Days)
- **CRITICAL DIRECTIVE**: All news, intelligence entries, and research breakthroughs MUST be fresh: mostly within 2 weeks old, and NEVER older than 14 days.
- **Ingestion & Feed Guard**: Do NOT ingest, highlight, digest, surface, or report stale news or historical archive dumps published > 14 days ago.
- The pipeline's Ingestion Freshness Guard strictly enforces `max_ingest_age_days = 14` (2 weeks).

## 🌐 Primary Project Scope & Focus Areas
Always prioritize and balance broad, worldwide artificial intelligence news:
1. **Trending GitHub Repositories**: Open-source AI projects, agent runtimes, automation frameworks, popular developer codebases.
2. **Interesting Developer Tools & Infrastructure**: Inference runtimes (e.g., vLLM, Ollama, SGLang, llama.cpp), evaluation harnesses, vector stores, RAG connectors, desktop AI.
3. **Top AI Research Papers & Breakthroughs**: Seminal arXiv publications, test-time compute scaling, reasoning architectures, multimodal advancements.
4. **Frontier AI Models**: New foundation models, reasoning breakthroughs, open weights vs. proprietary releases (DeepSeek, Claude, OpenAI, Qwen, Llama, Mistral).
5. **Global Sovereign AI & Regional Ecosystems**: National AI labs, robotics, AI chips, hardware, and startup ecosystems worldwide.

## ⚠️ MANDATORY RULE: No Autonomous PR Merging
- **CRITICAL DIRECTIVE**: Antigravity MUST NEVER run `gh pr merge` or merge its own pull requests autonomously under any circumstance.
- All pull requests MUST remain open with the PR URL and a clear diff summary provided to the user.
- Merging and deployment are strictly reserved for the human user.

## ⚠️ MANDATORY RULE: 100% Free & Zero-Cost Architecture ($0/Month Law)
- **CRITICAL DIRECTIVE**: Everything in this project MUST be 100% completely free ($0/month).
- **Zero Paid APIs / Zero Subscriptions**: Under NO circumstance should any paid API, recurring subscription, proprietary cloud billing (e.g., paid OpenAI, paid Anthropic, paid DeepL, paid Google Cloud Translation API), or commercial SaaS dependency be introduced or required.
- **Permissive Open-Source Only**: All models, libraries, runtimes, and dependencies must be free and open-source (Apache 2.0, MIT, BSD, CC0). Avoid commercial paywalls or non-commercial licensing traps.
- **Local Silicon & Free-Tier First**: Architecture must rely entirely on local SLMs (via Ollama/llama.cpp such as `qwen2.5-coder:7b`/`3b`), generous free tiers (e.g., Groq free tier), direct public RPCs (e.g., Google GTX endpoint), or embedded in-process engines (e.g., Argos Translate).
- **Zero Operational Cost Guarantee**: The system must run perpetually on local compute and free public infrastructure with zero monthly bills or credit card requirements.
