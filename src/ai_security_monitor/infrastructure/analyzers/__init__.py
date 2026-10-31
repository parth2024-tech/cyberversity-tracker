"""
Analyzers infrastructure package - plugin registration.
"""

# Import all analyzers to register them
from ai_security_monitor.infrastructure.analyzers import (
    base,
    blast_radius_analyzer,
    embedding_service,
    heuristic_analyzer,
    llm_analyzer,
)
from ai_security_monitor.infrastructure.analyzers.base import (
    AnalysisResult,
    AnalyzerRegistry,
    BaseAnalyzer,
    analyzer_registry,
)
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    EmbeddingService,
)
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service as default_embedding_service,
)

__all__ = [
    "BaseAnalyzer",
    "AnalysisResult",
    "analyzer_registry",
    "AnalyzerRegistry",
    "EmbeddingService",
    "default_embedding_service",
    "base",
    "blast_radius_analyzer",
    "embedding_service",
    "heuristic_analyzer",
    "llm_analyzer",
]
