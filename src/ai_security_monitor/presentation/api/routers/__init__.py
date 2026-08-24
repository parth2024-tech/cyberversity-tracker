"""
API routers export.
"""
from ai_security_monitor.presentation.api.routers.analysis import analysis_router
from ai_security_monitor.presentation.api.routers.digest import digest_router
from ai_security_monitor.presentation.api.routers.entries import entries_router
from ai_security_monitor.presentation.api.routers.sources import sources_router
from ai_security_monitor.presentation.api.routers.stats import stats_router

__all__ = [
    "stats_router",
    "entries_router",
    "sources_router",
    "analysis_router",
    "digest_router"
]
