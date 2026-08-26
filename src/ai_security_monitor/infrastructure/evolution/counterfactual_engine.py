"""
Counterfactual Engine for the AI Security Monitor.

Implements the "Counterfactual Hermes" from the 0.1% plan — recording what else
could have been done after each decision, maintaining a model of alternative strategies.
This enables learning not just what works, but what would have worked better.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from src.database import Database


class OutcomeType(Enum):
    """Types of outcomes we track for counterfactual comparison."""
    ACTUAL_EXECUTION = "actual_execution"
    ALTERNATIVE_PROPOSED = "alternative_proposed"
    ALTERNATIVE_TESTED = "alternative_tested"
    CONFIRMED_FALSE_POSITIVE = "confirmed_false_positive"
    CONFIRMED_TRUE_POSITIVE = "confirmed_true_positive"


@dataclass
class CounterfactualAlternative:
    """Represents an alternative strategy that could have been used."""
    id: UUID = field(default_factory=uuid4)
    actual_strategy_id: UUID = None  # Strategy actually used
    alternative_strategy_id: UUID = None  # Strategy that could have been used
    predicted_benefit: str = ""  # Why this alternative might be better
    confidence: float = 0.5  # How confident we are this alternative is better
    evidence: Dict[str, Any] = field(default_factory=dict)  # Supporting evidence
    outcome: OutcomeType = OutcomeType.ALTERNATIVE_PROPOSED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DecisionRecord:
    """Records a decision made by the system with all context."""
    id: UUID = field(default_factory=uuid4)
    entry_id: int = None
    decision_type: str = ""  # "strategy_selection", "model_routing", "verification_skip"
    chosen_value: Any = None
    alternatives: List[CounterfactualAlternative] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)  # System state at decision time
    outcome: OutcomeType = OutcomeType.ACTUAL_EXECUTION
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class CounterfactualTracker:
    """
    Tracks counterfactual alternatives and outcomes over time.
    Maintains a model of what would have happened with different strategies.
    """
    
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._decisions: Dict[UUID, DecisionRecord] = {}
        self._outcomes: Dict[UUID, OutcomeType] = {}
    
    def record_decision(
        self,
        entry_id: int,
        decision_type: str,
        chosen_value: Any,
        alternatives: Optional[List[CounterfactualAlternative]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """
        Record a decision with alternatives.
        """
        decision = DecisionRecord(
            entry_id=entry_id,
            decision_type=decision_type,
            chosen_value=chosen_value,
            alternatives=alternatives or [],
            context=context or {},
        )
        
        with self._lock:
            self._decisions[decision.id] = decision
            
            # Persist to database
            with self.db.transaction() as conn:
                # Create table if not exists
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS counterfactual_decisions (
                        id TEXT PRIMARY KEY,
                        entry_id INTEGER,
                        decision_type TEXT,
                        chosen_value TEXT,
                        alternatives_json TEXT,
                        context_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (entry_id) REFERENCES entries(id)
                    )
                """)
                
                conn.execute("""
                    INSERT INTO counterfactual_decisions
                    (id, entry_id, decision_type, chosen_value, alternatives_json, context_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(decision.id),
                    decision.entry_id,
                    decision.decision_type,
                    str(chosen_value),
                    json.dumps([alt.__dict__ for alt in decision.alternatives]),
                    json.dumps(decision.context),
                ))
        
        return decision.id
    
    def record_outcome(self, decision_id: UUID, outcome: OutcomeType, evidence: Optional[Dict] = None):
        """Record the outcome of a decision."""
        with self._lock:
            if decision_id in self._decisions:
                self._decisions[decision_id].outcome = outcome
                self._outcomes[decision_id] = outcome
                
                # Update database
                with self.db.transaction() as conn:
                    conn.execute("""
                        UPDATE counterfactual_decisions
                        SET outcome = ?
                        WHERE id = ?
                    ""`, (outcome.value, str(decision_id)))
    
    def get_decisions_by_entry(self, entry_id: int) -> List[DecisionRecord]:
        """Get all decisions made for a specific entry."""
        with self._lock:
            return [d for d in self._decisions.values() if d.entry_id == entry_id]
    
    def get_most_surprising(self, top_n: int = 10) -> List[DecisionRecord]:
        """
        Get decisions where alternatives would have been better.
        These are learning opportunities.
        """
        with self._lock:
            # Look for decisions where alternatives had higher predicted confidence
            surprising = []
            for decision in self._decisions.values():
                for alt in decision.alternatives:
                    if alt.confidence > 0.7:  # High confidence alternative
                        surprising.append(decision)
                        break
            
            # Sort by timestamp (most recent first)
            surprising.sort(key=lambda d: d.timestamp, reverse=True)
            return surprising[:top_n]
    
    def calculate_counterfactual_regret(self, decision_id: UUID) -> float:
        """
        Calculate how much we "regret" a decision.
        Regret = best alternative outcome - actual outcome.
        """
        with self._lock:
            decision = self._decisions.get(decision_id)
            if not decision or not decision.alternatives:
                return 0.0
            
            # Simplified: use confidence as a proxy for expected value
            best_alternative_confidence = max(alt.confidence for alt in decision.alternatives)
            return best_alternative_confidence  # Higher = more regret


class OpportunityDetector:
    """
    Detects high-value opportunities based on counterfactual analysis.
    Finds repeated patterns where the system could improve.
    """
    
    def __init__(self, tracker: CounterfactualTracker):
        self.tracker = tracker
        self._lock = threading.Lock()
    
    def detect_patterns(self) -> List[Dict[str, Any]]:
        """
        Detect patterns in counterfactual outcomes.
        Returns a list of detected opportunities.
        """
        patterns = []
        
        with self._lock:
            # Pattern 1: Repeated false positives in specific categories
            category_fp_count = {}
            for decision in self.tracker._decisions.values():
                if decision.outcome == OutcomeType.CONFIRMED_FALSE_POSITIVE:
                    category = decision.context.get("category", "unknown")
                    category_fp_count[category] = category_fp_count.get(category, 0) + 1
            
            for category, count in category_fp_count.items():
                if count >= 3:  # Threshold for pattern
                    patterns.append({
                        "type": "repeated_false_positives",
                        "category": category,
                        "count": count,
                        "recommendation": f"Consider adjusting thresholds for {category} to reduce false positives",
                        "confidence": min(0.9, count / 10),
                    })
            
            # Pattern 2: Alternatives consistently outperforming
            alt_performance = {}
            for decision in self.tracker._decisions.values():
                if decision.alternatives:
                    best_alt = max(decision.alternatives, key=lambda a: a.confidence)
                    if best_alt.confidence > 0.7:
                        alt_strategy = best_alt.alternative_strategy_id
                        if alt_strategy not in alt_performance:
                            alt_performance[alt_strategy] = 0
                        alt_performance[alt_strategy] += 1
            
            for strategy_id, count in alt_performance.items():
                if count >= 5:
                    patterns.append({
                        "type": "alternative_outperforming",
                        "strategy_id": str(strategy_id),
                        "outperform_count": count,
                        "recommendation": f"Strategy {strategy_id} consistently outperforms in {count} cases",
                        "confidence": min(0.85, count / 20),
                    })
            
            # Pattern 3: High-severity threats consistently misclassified
            misclassify_count = 0
            for decision in self.tracker._decisions.values():
                if (decision.context.get("threat_velocity", 0) >= 70 and
                    decision.outcome == OutcomeType.CONFIRMED_FALSE_POSITIVE):
                    misclassify_count += 1
            
            if misclassify_count >= 5:
                patterns.append({
                    "type": "high_velocity_misclassification",
                    "count": misclassify_count,
                    "recommendation": "High-severity threats are being misclassified. Review velocity scoring logic.",
                    "confidence": 0.8,
                })
        
        return patterns
    
    def get_opportunities(self, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
        """Get actionable opportunities above confidence threshold."""
        patterns = self.detect_patterns()
        return [p for p in patterns if p["confidence"] >= min_confidence]


class CounterfactualEngine:
    """
    Unified interface for counterfactual reasoning.
    Combines decision tracking, outcome recording, and opportunity detection.
    """
    
    def __init__(self, db: Database):
        self.db = db
        self.tracker = CounterfactualTracker(db)
        self.opportunity_detector = OpportunityDetector(self.tracker)
    
    def record_analysis_decision(
        self,
        entry_id: int,
        strategy_used: UUID,
        alternative_strategies: Optional[List[Tuple[UUID, float]]] = None,  # (strategy_id, confidence)
        context: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """
        Record a strategy selection decision with alternatives.
        
        Args:
            entry_id: Entry being analyzed
            strategy_used: Strategy actually used
            alternative_strategies: List of (strategy_id, expected_benefit_confidence)
            context: System state at decision time
        """
        alternatives = []
        if alternative_strategies:
            for strat_id, confidence in alternative_strategies:
                alternatives.append(CounterfactualAlternative(
                    actual_strategy_id=strategy_used,
                    alternative_strategy_id=strat_id,
                    predicted_benefit=f"Strategy {strat_id} predicted to perform better",
                    confidence=confidence,
                    evidence={"alternative_confidence": confidence},
                ))
        
        return self.tracker.record_decision(
            entry_id=entry_id,
            decision_type="strategy_selection",
            chosen_value=str(strategy_used),
            alternatives=alternatives,
            context=context,
        )
    
    def record_model_routing(
        self,
        entry_id: int,
        model_chosen: str,
        alternatives: Optional[List[Tuple[str, float]]] = None,  # (model_name, confidence)
        context: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """Record a model routing decision with alternatives."""
        alternatives_list = []
        if alternatives:
            for model_name, confidence in alternatives:
                alternatives_list.append(CounterfactualAlternative(
                    alternative_strategy_id=UUID(),
                    predicted_benefit=f"Model {model_name} predicted to perform better",
                    confidence=confidence,
                    evidence={"model": model_name, "alternative_confidence": confidence},
                ))
        
        return self.tracker.record_decision(
            entry_id=entry_id,
            decision_type="model_routing",
            chosen_value=model_chosen,
            alternatives=alternatives_list,
            context=context,
        )
    
    def get_analysis_report(self) -> Dict[str, Any]:
        """Generate a report on counterfactual analysis."""
        patterns = self.opportunity_detector.detect_patterns()
        opportunities = self.opportunity_detector.get_opportunities()
        
        # Calculate overall regret
        total_regret = 0.0
        decision_count = 0
        for decision_id in self.tracker._decisions:
            regret = self.tracker.calculate_counterfactual_regret(decision_id)
            total_regret += regret
            decision_count += 1
        
        avg_regret = total_regret / decision_count if decision_count else 0.0
        
        return {
            "total_decisions": decision_count,
            "patterns_detected": len(patterns),
            "opportunities": opportunities,
            "average_regret": avg_regret,
            "regret_assessment": "high" if avg_regret > 0.7 else "medium" if avg_regret > 0.4 else "low",
        }


def create_counterfactual_engine(db: Database) -> CounterfactualEngine:
    """Factory function to create a counterfactual engine."""
    return CounterfactualEngine(db)
