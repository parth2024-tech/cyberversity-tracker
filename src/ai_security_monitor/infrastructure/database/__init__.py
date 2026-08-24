"""
Database infrastructure package initialization.
"""

from ai_security_monitor.infrastructure.database.connection import (
    DatabaseManager,
    db_manager,
    get_db_session,
)
from ai_security_monitor.infrastructure.database.models import (
    AnalysisModel,
    Base,
    DigestModel,
    EntryModel,
    FetchLogModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyAnalysisRepository,
    SQLAlchemyDigestRepository,
    SQLAlchemyEntryRepository,
    SQLAlchemyFetchLogRepository,
    SQLAlchemySourceRepository,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    UnitOfWork,
    get_unit_of_work,
    unit_of_work,
)

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
