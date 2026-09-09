# ⚠️ DEPRECATED — Legacy v1 Monolithic Codebase

This directory contains the original synchronous monolithic implementation that was
superseded by the Clean Architecture rewrite in `src/ai_security_monitor/`.

## Files Archived

| File | Description |
|---|---|
| `database.py` | Synchronous `sqlite3`-based `Database` class |
| `monitor.py` | Original `AISecurityMonitor` — imports from `database.py` and `analyzer.py` |
| `analyzer.py` | Heuristic + OpenAI-based threat analyzer (sync) |
| `fetchers.py` | RSS/GitHub/CVE fetchers (sync `requests`) |
| `server.py` | Flask/CherryPy HTTP server — imports from `monitor.py` |
| `delivery.py` | Email/Slack notification delivery (sync) |
| `cli.py` | Root CLI entry-point that imports `AISecurityMonitor` from `monitor.py` |

## Why Archived (Not Deleted)

These files are preserved for historical reference. They are **not imported** by the
modern Clean Architecture code at any point.

## Modern Equivalents

All functionality has been fully reimplemented in:
  src/ai_security_monitor/domain/
  src/ai_security_monitor/application/
  src/ai_security_monitor/infrastructure/
  src/ai_security_monitor/presentation/

**Do not add new features here.**
