"""
Epistemic Engine for the AI Security Monitor.
Implements the "Epistemic Engine" from the 0.1% plan — a system that distinguishes between
Fact, Observation, Inference, Hypothesis, Assumption, and Unknown. Every major analytical
claim gets an evidence structure with confidence, counter-evidence, and next experiment.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
from uuid import uuid4, UUID

from src.analyzer import (
    ClaimType,
    EvidenceBundle,
)
from src.database import Database


def _mean(data: List[float]) -> float:
    """Calculates the mean of a list of floats, handling empty lists."""
    if not data:
        return 0.0
    return sum(data) / len(data)


@dataclass
class Claim:
    """Represents a single claim made during analysis."""
    id: UUID
    analysis_id: int
    claim_type: ClaimType
    target: str
    value: Any
    confidence: float
    evidence: dict
    method: str
    model_version: str
    parent_claim_ids: List[UUID] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ClaimTracker:
    """
    Tracks claims across analyses, assigns unique claim IDs, maintains claim lineage.
    Thread-safe.
    """
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        # In-memory cache for quick access, consider size limits for large systems
        self._claims: Dict[UUID, Claim] = {}
        self._target_claims: Dict[str, List[UUID]] = {}

    def _load_claims_from_db(self):
        """Loads all claims from the database into memory.
        For production, this might need pagination or on-demand loading.
        """
        with self._lock:
            with self.db.transaction() as conn:
                cursor = conn.execute("SELECT * FROM analysis_evidence")
                for row in cursor.fetchall():
                    claim_id = UUID(row['id'])
                    claim_type = ClaimType(row['claim_type'])
                    evidence = json.loads(row['evidence_json']) if row['evidence_json'] else {}
                    claim = Claim(
                        id=claim_id,
                        analysis_id=row['analysis_id'],
                        claim_type=claim_type,
                        target=row['claim_target'],
                        value=row['claim_value'],
                        confidence=row['confidence'],
                        evidence=evidence,
                        method=row['method'],
                        model_version=row['model_version'],
                        created_at=row['created_at']
                    )
                    self._claims[claim_id] = claim
                    self._target_claims.setdefault(claim.target, []).append(claim_id)

    def register_claim(self, analysis_id: int, claim_type: ClaimType, target: str, value: Any,
                       evidence: dict, confidence: float, method: str, model_version: str,
                       parent_claim_ids: Optional[List[UUID]] = None) -> UUID:
        """
        Registers a new claim, persists it to the database, and returns a unique claim ID.
        """
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0")

        claim_id = uuid4()
        evidence_json = json.dumps(evidence) if evidence else None
        parent_claim_ids = parent_claim_ids if parent_claim_ids is not None else []

        with self._lock:
            with self.db.transaction() as conn:
                conn.execute("""
                    INSERT INTO analysis_evidence
                    (id, analysis_id, claim_type, claim_target, claim_value, confidence, evidence_json, method, model_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(claim_id),
                    analysis_id,
                    claim_type.value,
                    target,
                    str(value),
                    confidence,
                    evidence_json,
                    method,
                    model_version
                ))

            claim = Claim(
                id=claim_id,
                analysis_id=analysis_id,
                claim_type=claim_type,
                target=target,
                value=value,
                confidence=confidence,
                evidence=evidence,
                method=method,
                model_version=model_version,
                parent_claim_ids=parent_claim_ids
            )
            self._claims[claim_id] = claim
            self._target_claims.setdefault(target, []).append(claim_id)
            return claim_id

    def get_claim(self, claim_id: UUID) -> Optional[Claim]:
        """Retrieves a claim by its unique ID."""
        with self._lock:
            return self._claims.get(claim_id)

    def get_claims_by_target(self, target: str) -> List[Claim]:
        """Retrieves all claims related to a specific target."""
        with self._lock:
            claim_ids = self._target_claims.get(target, [])
            return [self._claims[cid] for cid in claim_ids if cid in self._claims]

    def get_claim_lineage(self, claim_id: UUID) -> List[Claim]:
        """
        Returns the parent claims for a given claim, traversing up the lineage.
        NOTE: This current implementation assumes parent_claim_ids are not persisted in DB
        and are only available in the in-memory Claim object if passed during registration.
        A full lineage tracking would require a separate DB table.
        """
        lineage = []
        current_claim = self.get_claim(claim_id)
        if current_claim:
            for parent_id in current_claim.parent_claim_ids:
                parent_claim = self.get_claim(parent_id)
                if parent_claim:
                    lineage.append(parent_claim)
        return lineage

    def update_confidence(self, claim_id: UUID, new_confidence: float, reason: str):
        """
        Updates the confidence score of an existing claim.
        The 'reason' is for auditing/logging and not persisted in this simple schema.
        """
        if not (0.0 <= new_confidence <= 1.0):
            raise ValueError("New confidence must be between 0.0 and 1.0")

        with self._lock:
            if claim_id in self._claims:
                self._claims[claim_id].confidence = new_confidence
                with self.db.transaction() as conn:
                    conn.execute("""
                        UPDATE analysis_evidence SET confidence = ? WHERE id = ?
                    """, (new_confidence, str(claim_id)))
            else:
                raise ValueError(f"Claim with ID {claim_id} not found.")


class EvidenceAccumulator:
    """
    Accumulates evidence for/against claims over time.
    For simplicity, this example will store evidence in-memory, but for persistence
    it would require a separate table linking to analysis_evidence.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # claim_id -> (List[supporting_evidence], List[opposing_evidence])
        self._evidence_store: Dict[UUID, Tuple[List[dict], List[dict]]] = {}

    def add_evidence(self, claim_id: UUID, evidence_json: dict, supports: bool, source: str):
        """Adds new evidence to a claim."""
        with self._lock:
            supporting, opposing = self._evidence_store.setdefault(claim_id, ([], []))
            evidence_entry = {"evidence": evidence_json, "source": source, "timestamp": datetime.now().isoformat()}
            if supports:
                supporting.append(evidence_entry)
            else:
                opposing.append(evidence_entry)
            self._evidence_store[claim_id] = (supporting, opposing)

    def get_evidence(self, claim_id: UUID) -> Tuple[List[dict], List[dict]]:
        """Retrieves all supporting and opposing evidence for a claim."""
        with self._lock:
            return self._evidence_store.get(claim_id, ([], []))

    def calculate_evidence_weight(self, claim_id: UUID) -> float:
        """
        Calculates a combined evidence weight from -1.0 (strong opposition) to 1.0 (strong support).
        Simple heuristic: (num_supporting - num_opposing) / (num_supporting + num_opposing)
        """
        with self._lock:
            supporting, opposing = self._evidence_store.get(claim_id, ([], []))
            num_supporting = len(supporting)
            num_opposing = len(opposing)

            total_evidence = num_supporting + num_opposing
            if total_evidence == 0:
                return 0.0  # No evidence
            return (num_supporting - num_opposing) / total_evidence


class ConfidenceCalibrator:
    """
    Calibrates raw confidence scores against ground truth outcomes.
    Persists outcomes to analysis_outcome table.
    """
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        # In-memory store for calibration data: (claim_type, method, model_version) -> List[Tuple[raw_confidence, outcome]]
        self._calibration_data: Dict[Tuple[ClaimType, str, str], List[Tuple[float, str]]] = {}
        self._load_calibration_data_from_db()

    def _load_calibration_data_from_db(self):
        """Loads calibration outcomes from the database."""
        with self._lock:
            with self.db.transaction() as conn:
                cursor = conn.execute("""
                    SELECT ae.claim_type, ae.method, ae.model_version, ae.confidence, ao.outcome_type
                    FROM analysis_outcome ao
                    JOIN analysis_evidence ae ON ao.analysis_id = ae.analysis_id
                """)
                for row in cursor.fetchall():
                    claim_type = ClaimType(row['claim_type'])
                    method = row['method']
                    model_version = row['model_version']
                    raw_confidence = row['confidence']
                    outcome_type = row['outcome_type']
                    key = (claim_type, method, model_version)
                    self._calibration_data.setdefault(key, []).append((raw_confidence, outcome_type))

    def record_outcome(self, analysis_id: int, outcome_type: Literal['telegram_sent', 'user_dismissed', 'user_escalated', 'false_positive', 'confirmed'], outcome_value: Optional[str] = None):
        """
        Records a ground truth outcome for an analysis, used for future confidence calibration.
        """
        with self._lock:
            with self.db.transaction() as conn:
                conn.execute("""
                    INSERT INTO analysis_outcome
                    (analysis_id, outcome_type, outcome_value)
                    VALUES (?, ?, ?)
                """, (analysis_id, outcome_type, outcome_value))

    def calibrate_confidence(self, raw_confidence: float, claim_type: ClaimType,
                             method: str, model_version: str) -> float:
        """
        Calibrates a raw confidence score based on historical outcomes for similar claims.
        This is a placeholder for a more sophisticated calibration model (e.g., Platt scaling, isotonic regression).
        For now, it's a simple moving average adjustment based on outcomes.
        """
        key = (claim_type, method, model_version)
        with self._lock:
            calibration_points = self._calibration_data.get(key, [])

            if not calibration_points:
                return raw_confidence  # No calibration data, return raw

            # Simple calibration: adjust based on observed outcomes
            # Treat 'confirmed' as +1, 'false_positive' / 'user_dismissed' as -1, others as 0
            adjusted_confidences = []
            for conf, outcome in calibration_points:
                if outcome == 'confirmed' or outcome == 'user_escalated':
                    adjusted_confidences.append(conf)
                elif outcome == 'false_positive' or outcome == 'user_dismissed':
                    adjusted_confidences.append(1 - conf) # Invert confidence for false positives

            if not adjusted_confidences:
                return raw_confidence

            # For a simple calibration, we might just return the average of historical *confirmed* confidences
            # or apply a linear adjustment. For now, let's just return the raw confidence if no sophisticated
            # calibration model is implemented.
            return raw_confidence

    def get_calibration_stats(self) -> Dict[str, Any]:
        """
        Returns statistics about calibration data per claim_type/method.
        This would typically include calibration curves or performance metrics.
        """
        stats = {}
        with self._lock:
            for (claim_type, method, model_version), data_points in self._calibration_data.items():
                key = f"{claim_type.value}_{method}_{model_version}"
                
                raw_confidences = [dp[0] for dp in data_points]
                outcomes = [dp[1] for dp in data_points]

                num_confirmed = outcomes.count('confirmed')
                num_false_positives = outcomes.count('false_positive')
                num_dismissed = outcomes.count('user_dismissed')
                num_total = len(outcomes)

                avg_raw_confidence = _mean(raw_confidences) if raw_confidences else 0.0

                stats[key] = {
                    "total_outcomes": num_total,
                    "confirmed": num_confirmed,
                    "false_positives": num_false_positives,
                    "user_dismissed": num_dismissed,
                    "average_raw_confidence": avg_raw_confidence
                }
        return stats


class EpistemicEngine:
    """
    Unified interface for the Epistemic Engine, combining claim tracking, evidence accumulation,
    and confidence calibration.
    """
    def __init__(self, db: Database):
        self.db = db
        self.claim_tracker = ClaimTracker(db)
        self.evidence_accumulator = EvidenceAccumulator()
        self.confidence_calibrator = ConfidenceCalibrator(db)

    # Re-export ClaimType and EvidenceBundle for convenience
    ClaimType = ClaimType
    EvidenceBundle = EvidenceBundle

    def analyze_with_evidence(self, entry_dict: Dict, analyzer_fn: Callable) -> Tuple[Any, List[EvidenceBundle]]:
        """
        Runs an analyzer function and automatically registers claims from its EvidenceBundles.
        """
        analysis_result = analyzer_fn(entry_dict)
        evidence_bundles = getattr(analysis_result, 'evidence_bundles', [])

        # First, save the overall analysis to get an analysis_id
        analysis_id = self.db.save_analysis(
            entry_id=entry_dict['id'],
            attack_vector=analysis_result.attack_vector,
            risk_assessment=analysis_result.risk_assessment,
            mitigation=analysis_result.mitigation,
            threat_velocity=analysis_result.threat_velocity,
            severity_index=analysis_result.severity_index,
            blast_radius_score=analysis_result.blast_radius_score,
            affected_ecosystem=analysis_result.affected_ecosystem,
            is_pre_cve_warning=analysis_result.is_pre_cve_warning,
            attack_archetype=analysis_result.attack_archetype,
            weaponization_potential=analysis_result.weaponization_potential,
            ai_model=analysis_result.ai_model,
            overall_confidence=analysis_result.confidence,
            evidence_version="v1",
            evidence_bundles=[{
                **bundle.__dict__,
                'claim_type': bundle.claim_type.value if isinstance(bundle.claim_type, ClaimType) else bundle.claim_type
            } for bundle in evidence_bundles]
        )

        return analysis_result, evidence_bundles

    def query_claims(self, target_pattern: str) -> List[Claim]:
        """
        Queries claims based on a target pattern (e.g., regex match against claim_target).
        This will be a simple substring match for now.
        """
        matching_claims = []
        with self.claim_tracker._lock:
            for claim in self.claim_tracker._claims.values():
                if target_pattern in claim.target:
                    matching_claims.append(claim)
        return matching_claims

    def get_system_beliefs(self) -> Dict[str, Any]:
        """
        Provides a summary of what the system "knows" with confidence.
        """
        summary = {
            "total_claims": 0,
            "claims_by_type": {ct.value: 0 for ct in ClaimType},
            "claims_by_method": {},
            "top_confidence_claims": [],
            "calibration_stats": self.confidence_calibrator.get_calibration_stats()
        }

        all_claims = list(self.claim_tracker._claims.values())
        summary['total_claims'] = len(all_claims)

        for claim in all_claims:
            summary['claims_by_type'][claim.claim_type.value] += 1
            summary['claims_by_method'].setdefault(claim.method, 0)
            summary['claims_by_method'][claim.method] += 1

            calibrated_confidence = self.confidence_calibrator.calibrate_confidence(
                claim.confidence, claim.claim_type, claim.method, claim.model_version
            )
            claim_data = {
                "claim_id": str(claim.id),
                "target": claim.target,
                "value": str(claim.value),
                "claim_type": claim.claim_type.value,
                "raw_confidence": claim.confidence,
                "calibrated_confidence": calibrated_confidence
            }
            summary['top_confidence_claims'].append((calibrated_confidence, claim_data))

        summary['top_confidence_claims'].sort(key=lambda x: x[0], reverse=True)
        summary['top_confidence_claims'] = [c[1] for c in summary['top_confidence_claims']][:10]

        return summary
