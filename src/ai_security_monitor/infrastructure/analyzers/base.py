# Abstract base analyzer and registry.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from ai_security_monitor.domain.entities import Analysis, AnalysisModel, Entry
from ai_security_monitor.domain.events import EntryAnalyzedEvent, event_bus


@dataclass
class AnalysisResult:
    """Result of analysis operation."""
    entry_id: UUID
    attack_vector: str
    risk_assessment: str
    mitigation: str
    threat_velocity: int  # 1-100
    severity_index: int  # 1-100
    blast_radius_score: int = 0  # 1-100
    affected_ecosystem: list[str] = None
    is_pre_cve_warning: bool = False
    attack_archetype: str = ""
    weaponization_potential: str = "Theoretical"
    model: AnalysisModel = AnalysisModel.HEURISTIC
    confidence: float = 1.0

    def __post_init__(self):
        if self.affected_ecosystem is None:
            self.affected_ecosystem = []


class BaseAnalyzer(ABC):
    """Abstract base class for all analyzers."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @property
    @abstractmethod
    def analyzer_type(self) -> str:
        """Unique identifier for this analyzer."""
        ...

    @property
    @abstractmethod
    def model(self) -> AnalysisModel:
        """Analysis model enum value."""
        ...

    @abstractmethod
    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze a single entry."""
        ...

    async def analyze_batch(self, entries: list[Entry]) -> list[tuple[UUID, AnalysisResult]]:
        """Analyze multiple entries."""
        results = []
        for entry in entries:
            try:
                result = await self.analyze(entry)
                results.append((entry.id, result))

                # Publish domain event
                analysis = Analysis(
                    id=entry.id,  # temporary, will be set by repo
                    entry_id=entry.id,
                    attack_vector=result.attack_vector,
                    risk_assessment=result.risk_assessment,
                    mitigation=result.mitigation,
                    threat_velocity=result.threat_velocity,
                    severity_index=result.severity_index,
                    blast_radius_score=result.blast_radius_score,
                    affected_ecosystem=result.affected_ecosystem,
                    is_pre_cve_warning=result.is_pre_cve_warning,
                    attack_archetype=result.attack_archetype,
                    weaponization_potential=result.weaponization_potential,
                    model=result.model,
                    confidence=result.confidence,
                )
                await event_bus.publish(EntryAnalyzedEvent(
                    aggregate_id=entry.id,
                    entry_id=entry.id,
                    analysis=analysis,
                ))
            except Exception as e:
                print(f"Analysis failed for entry {entry.id}: {e}")
                results.append((entry.id, None))
        return results


class AnalyzerRegistry:
    """Registry for analyzer plugins."""

    def __init__(self):
        self._analyzers: dict[str, type[BaseAnalyzer]] = {}

    def register(self, analyzer_type: str, analyzer_class: type[BaseAnalyzer]) -> None:
        self._analyzers[analyzer_type] = analyzer_class

    def get(self, analyzer_type: str) -> type[BaseAnalyzer]:
        if analyzer_type not in self._analyzers:
            raise ValueError(f"No analyzer registered for type: {analyzer_type}")
        return self._analyzers[analyzer_type]

    def create(self, analyzer_type: str, config: dict | None = None) -> BaseAnalyzer:
        analyzer_class = self.get(analyzer_type)
        return analyzer_class(config)

    def list_types(self) -> list[str]:
        return list(self._analyzers.keys())


# Global analyzer registry
analyzer_registry = AnalyzerRegistry()
