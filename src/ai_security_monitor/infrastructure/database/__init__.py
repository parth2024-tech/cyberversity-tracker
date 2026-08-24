"""
Database infrastructure package initialization.
"""

from ai_security_monitor.infrastructure.database.connection import db_manager, get_db_session, DatabaseManager
from ai_security_monitor.infrastructure.database.models import (
    Base, SourceModel, EntryModel, AnalysisModel, FetchLogModel, DigestModel
)
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyEntryRepository,
    SQLAlchemyAnalysisRepository,
    SQLAlchemySourceRepository,
    SQLAlchemyFetchLogRepository,
    SQLAlchemyDigestRepository,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork, unit_of_work, get_unit_of_work

__all__ = [
    "db_manager",
    "get_db_session",
    "DatabaseManager",
    "Base",
    "SourceModel",
    "EntryModel",
    "AnalysisModel",
    "FetchLogModel",
    "DigestModel",
    "SQLAlchemyEntryRepository",
    "SQLAlchemyAnalysisRepository",
    "SQLAlchemySourceRepository",
    "SQLAlchemyFetchLogRepository",
    "SQLAlchemyDigestRepository",
    "UnitOfWork",
    "unit_of_work",
    "get_unit_of_work",
]