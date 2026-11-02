"""
API routers export.
"""

from ai_security_monitor.presentation.api.routers.analysis import analysis_router
from ai_security_monitor.presentation.api.routers.audio import audio_router
from ai_security_monitor.presentation.api.routers.backup import backup_router
from ai_security_monitor.presentation.api.routers.china import china_router
from ai_security_monitor.presentation.api.routers.clusters import (
    router as clusters_router,
)
from ai_security_monitor.presentation.api.routers.council import council_router
from ai_security_monitor.presentation.api.routers.digest import digest_router
from ai_security_monitor.presentation.api.routers.entities import entities_router
from ai_security_monitor.presentation.api.routers.entries import entries_router
from ai_security_monitor.presentation.api.routers.events import events_router
from ai_security_monitor.presentation.api.routers.feed import feed_router
from ai_security_monitor.presentation.api.routers.newspaper import newspaper_router
from ai_security_monitor.presentation.api.routers.parity import parity_router
from ai_security_monitor.presentation.api.routers.sources import sources_router
from ai_security_monitor.presentation.api.routers.stats import stats_router
from ai_security_monitor.presentation.api.routers.telegram import telegram_router
from ai_security_monitor.presentation.api.routers.translation import translation_router
from ai_security_monitor.presentation.api.routers.triage import triage_router
from ai_security_monitor.presentation.api.routers.vault import vault_router
from ai_security_monitor.presentation.api.routers.watchlist import watchlist_router

__all__ = [
    "stats_router",
    "entries_router",
    "sources_router",
    "analysis_router",
    "digest_router",
    "watchlist_router",
    "triage_router",
    "newspaper_router",
    "audio_router",
    "translation_router",
    "backup_router",
    "vault_router",
    "china_router",
    "feed_router",
    "telegram_router",
    "entities_router",
    "council_router",
    "clusters_router",
    "parity_router",
    "events_router",
]
