"""
Replay Harness for the AI Security Monitor.

Implements the "Time Machine for Agents" from the 0.1% plan — replaying historical
entries with mutated strategies to benchmark improvements before deployment.
This enables safe evolution: never blindly update production behavior.
"""

import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from src.database import Database
from src.analyzer import HeuristicAnalyzer, AnalysisResult
from src.ai_security_monitor.infrastructure.evolution.strategy_genome import StrategyDna, BenchmarkResult


class ReplayMode(Enum):
    """How to replay entries."""
    EXACT_MATCH = "exact_match"          # Re-run with exact same inputs
    MUTATED_STRATEGY = "mutated_strategy"  # Run with different strategy
    COMPARATIVE = "comparative"           # Run both old and new, compare


@dataclass
class ReplayEntry:
    """A single entry to replay."""
    id: int
    title: str
    summary: str
    category: str
    url: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    original_analysis: Optional[Dict[str, Any]] = None


@dataclass
class ReplayResult:
    """Result of replaying a single entry."""
    entry_id: int
    strategy_name: str
    strategy_genes: Dict[str, Any]
    analysis: AnalysisResult
    latency_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ComparisonResult:
    """Comparison between original and new analysis."""
    entry_id: int
    original_analysis: Optional[AnalysisResult]
    new_analysis: AnalysisResult
    strategy_name: str
    strategy_genes: Dict[str, Any]
    differences: Dict[str, Tuple[Any, Any]]  # field -> (original, new)
    improvement_score: float  # -1 to 1, positive = better
    latency_ms: float


class ReplayHarness:
    """
    Replays historical entries with different strategies.
    Enables safe testing of strategy mutations.
    """
    
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
    
    def load_entries(
        self, 
        limit: int = 100,
        since_days: int = 7,
        include_analysis: bool = True
    ) -> List[ReplayEntry]:
        """Load historical entries for replay."""
        since = datetime.now() - timedelta(days=since_days)
        entries = self.db.get_entries(since=since, limit=limit)
        
        replay_entries = []
        for entry in entries:
            original_analysis = None
            if include_analysis:
                analysis_dict = self.db.get_analysis(entry['id'])
                if analysis_dict:
                    original_analysis = analysis_dict
            
            replay_entries.append(ReplayEntry(
                id=entry['id'],
                title=entry['title'],
                summary=entry.get('summary', ''),
                category=entry['category'],
                url=entry['url'],
                metadata=entry.get('metadata', {}),
                original_analysis=original_analysis,
            ))
        
        return replay_entries
    
    def replay_with_strategy(
        self,
        entries: List[ReplayEntry],
        strategy: StrategyDna,
        analyzer_fn: Optional[Callable] = None
    ) -> List[ReplayResult]:
        """Replay entries with a specific strategy."""
        if analyzer_fn is None:
            analyzer_fn = self._default_analyzer_fn
        
        results = []
        start_time = time.time()
        
        for entry in entries:
            entry_start = time.time()
            try:
                analysis = analyzer_fn(entry, strategy.genes)
                latency = (time.time() - entry_start) * 1000
                
                results.append(ReplayResult(
                    entry_id=entry.id,
                    strategy_name=f"gen{strategy.generation}_{strategy.id.hex[:8]}",
                    strategy_genes=strategy.genes,
                    analysis=analysis,
                    latency_ms=latency,
                ))
            except Exception as e:
                print(f"Replay error for entry {entry.id}: {e}")
        
        total_latency = (time.time() - start_time) * 1000
        print(f"Replayed {len(results)} entries in {total_latency:.0f}ms "
              f"(avg {total_latency/len(results):.0f}ms per entry)")
        
        return results
    
    def compare_strategies(
        self,
        entries: List[ReplayEntry],
        old_strategy: StrategyDna,
        new_strategy: StrategyDna,
        analyzer_fn: Optional[Callable] = None
    ) -> List[ComparisonResult]:
        """Compare old and new strategies on the same entries."""
        old_results = self.replay_with_strategy(entries, old_strategy, analyzer_fn)
        new_results = self.replay_with_strategy(entries, new_strategy, analyzer_fn)
        
        comparisons = []
        for old, new in zip(old_results, new_results):
            differences = {}
            improvement_score = 0.0
            
            # Compare key metrics
            fields_to_compare = [
                "threat_velocity", "severity_index", "blast_radius_score",
                "is_pre_cve_warning", "attack_archetype", "weaponization_potential"
            ]
            
            for field_name in fields_to_compare:
                old_val = getattr(old.analysis, field_name, None)
                new_val = getattr(new.analysis, field_name, None)
                
                if old_val != new_val:
                    differences[field_name] = (old_val, new_val)
            
            # Calculate improvement score
            # Positive = new is better, negative = old is better
            velocity_diff = new.analysis.threat_velocity - old.analysis.threat_velocity
            severity_diff = new.analysis.severity_index - old.analysis.severity_index
            blast_diff = new.analysis.blast_radius_score - old.analysis.blast_radius_score
            
            improvement_score = (velocity_diff + severity_diff + blast_diff) / 300  # Normalize to -1 to 1
            
            comparisons.append(ComparisonResult(
                entry_id=old.entry_id,
                original_analysis=old.analysis,
                new_analysis=new.analysis,
                strategy_name=new.strategy_name,
                strategy_genes=new.strategy_genes,
                differences=differences,
                improvement_score=improvement_score,
                latency_ms=new.latency_ms,
            ))
        
        return comparisons
    
    def _default_analyzer_fn(self, entry: ReplayEntry, genes: Dict[str, Any]) -> AnalysisResult:
        """Default analyzer function using HeuristicAnalyzer with strategy genes."""
        analyzer = HeuristicAnalyzer(config={"strategy_genes": genes})
        raw_entry = {
            'id': entry.id,
            'title': entry.title,
            'summary': entry.summary,
            'category': entry.category,
            'url': entry.url,
            'metadata': entry.metadata,
        }
        return analyzer.analyze(raw_entry)


class ReplayManager:
    """
    High-level manager for replay operations.
    Coordinates with evolution engine for safe strategy updates.
    """
    
    def __init__(self, db: Database):
        self.db = db
        self.harness = ReplayHarness(db)
        self._lock = threading.Lock()
    
    def validate_strategy_improvement(
        self,
        new_strategy: StrategyDna,
        old_strategy: StrategyDna,
        test_limit: int = 100,
        min_improvement: float = 0.05,  # 5% improvement required
        max_regression: float = 0.1,    # Max 10% regression allowed
    ) -> Dict[str, Any]:
        """
        Validate that a new strategy is better than the old one.
        Returns validation result with recommendation.
        """
        entries = self.harness.load_entries(limit=test_limit)
        
        if not entries:
            return {
                "valid": False,
                "reason": "No test entries available",
                "improvement": 0.0,
                "recommendation": "Cannot validate without data",
            }
        
        comparisons = self.harness.compare_strategies(entries, old_strategy, new_strategy)
        
        if not comparisons:
            return {
                "valid": False,
                "reason": "No comparisons generated",
                "improvement": 0.0,
                "recommendation": "Check analyzer configuration",
            }
        
        # Calculate aggregate metrics
        avg_improvement = sum(c.improvement_score for c in comparisons) / len(comparisons)
        max_regression_seen = min(c.improvement_score for c in comparisons)
        avg_latency_new = sum(c.latency_ms for c in comparisons) / len(comparisons)
        
        # Determine validity
        is_valid = avg_improvement >= min_improvement
        has_unacceptable_regression = max_regression_seen < -max_regression
        
        recommendation = "deploy" if is_valid else "iterate"
        if has_unacceptable_regression:
            recommendation = "reject"
        
        return {
            "valid": is_valid,
            "improvement": avg_improvement,
            "max_regression": max_regression_seen,
            "avg_latency_ms": avg_latency_new,
            "test_entries": len(entries),
            "comparisons": len(comparisons),
            "recommendation": recommendation,
            "details": {
                "entries_with_improvement": sum(1 for c in comparisons if c.improvement_score > 0),
                "entries_with_regression": sum(1 for c in comparisons if c.improvement_score < 0),
                "entries_neutral": sum(1 for c in comparisons if c.improvement_score == 0),
            },
        }


def create_replay_manager(db: Database) -> ReplayManager:
    """Factory function to create a replay manager."""
    return ReplayManager(db)
