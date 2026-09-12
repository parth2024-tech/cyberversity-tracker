# Changelog

All notable changes to **AI Security Monitor** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2.0.0] — 2026-09-11

### Added
- Clean 4-Layer DDD Architecture (Domain, Application, Infrastructure, Presentation)
- Worldwide AI Ecosystem Focus — GitHub trending repos, frontier models, arXiv research, developer tools
- Autonomous 5-Hour Newspaper — 10-page PDF/HTML/Markdown broadsheets via Email & Telegram
- Translation Service — auto-detects and translates non-English AI intelligence
- Audio Podcast Digest — TTS summaries via edge-tts / gTTS
- GitHub Trending Fetcher — scrape + GitHub Search API with AI keyword filtering
- Autonomous Triage Queue — background LLM worker (Ollama/Groq)
- WebSocket Live Telemetry — real-time new-entry and sweep-status broadcasts
- Response Cache — TTL-based in-memory cache with prefix invalidation
- Watchlist Rules, Permanent Vault, Sovereign Region Tagging
- GitHub Actions CI — automated lint, type-check, and test on every push/PR
- CHANGELOG.md (this file)

### Changed
- `datetime.utcnow()` → `datetime.now(UTC)` throughout (Python 3.12 deprecation fix)
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` in lifespan manager
- `logger.warn()` → `logger.warning()` (deprecated alias removed)
- `Optional[T]` → `T | None` union syntax in all modules
- `FetchLog.entries_total` now populated correctly from fetcher result
- `EventBus.publish()` logs suppressed handler errors instead of silent `pass`
- Duplicate `digest_router` mount under `/api/telegram` removed
- `_ensure_seed_database()` deduplicated to single call in `init_db()`
- `newspaper_service.py` refactored: live fetching → `NewspaperLiveFetcher`, PDF/HTML → `NewspaperRenderer`

### Removed
- `src/_legacy_v1/` — abandoned v1 monolith with 32 lint violations
- `vercel.json` — incompatible with persistent SQLite + APScheduler + WebSocket runtime

### Fixed
- `FetchLog.entries_total` was always 0
- Silent exception swallowing in `EventBus.publish()`
- Duplicate Telegram router mount causing duplicate route registration

---

## [1.0.0] — 2026-01-01

- Initial monolithic release
