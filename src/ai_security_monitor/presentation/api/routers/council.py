"""
API router for Multi-Agent Council in Shadow Mode (Workstream A2).
Provides endpoints to inspect the shadow review queue, query persona evaluations,
view citation-offset claim verification, and monitor the daily cost circuit breaker.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from ai_security_monitor.application.services.council_service import (
    CouncilCircuitBreaker,
    MultiAgentCouncilService,
)
from ai_security_monitor.domain.exceptions import EntityNotFoundError
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

council_router = APIRouter(prefix="/council", tags=["Multi-Agent Council"])
council_service = MultiAgentCouncilService()
circuit_breaker = CouncilCircuitBreaker()


@council_router.get("/reviews")
async def list_council_reviews(
    status: str | None = Query(
        None,
        description="Filter by review status: 'shadow', 'pending_review', 'approved', 'rejected', 'calibrated'",
    ),
    verdict: str | None = Query(
        None,
        description="Filter by consensus verdict (e.g. 'STRONG_CONSENSUS_ENDORSE', 'SPLIT_DECISION')",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max reviews to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> dict[str, Any]:
    """Retrieve shadow review queue items with persona breakdowns and claim verification telemetry."""
    reviews = await council_service.list_shadow_queue(
        status=status, verdict=verdict, limit=limit, offset=offset
    )
    return {
        "status_filter": status,
        "verdict_filter": verdict,
        "count": len(reviews),
        "reviews": [
            {
                "id": str(r.id),
                "entry_id": str(r.entry_id),
                "status": r.status,
                "consensus_verdict": r.consensus_verdict,
                "consensus_score": r.consensus_score,
                "consensus_summary": r.consensus_summary,
                "persona_evaluations": r.persona_evaluations,
                "verified_claims_count": len(r.verified_claims),
                "verified_claims": r.verified_claims,
                "receipt_keys_count": len(r.receipt_keys),
                "total_tokens": r.total_tokens,
                "total_latency_ms": r.total_latency_ms,
                "estimated_cost_usd": r.estimated_cost_usd,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
        ],
    }


@council_router.get("/entry/{entry_id}")
async def get_council_review_for_entry(entry_id: UUID) -> dict[str, Any]:
    """Retrieve existing council evaluation for a specific intelligence entry."""
    async with SqlAlchemyUnitOfWork() as uow:
        review = await uow.council.get_by_entry(entry_id)
        if not review:
            raise HTTPException(
                status_code=404,
                detail=f"No council review found for entry {entry_id}",
            )
        return {
            "id": str(review.id),
            "entry_id": str(review.entry_id),
            "status": review.status,
            "consensus_verdict": review.consensus_verdict,
            "consensus_score": review.consensus_score,
            "consensus_summary": review.consensus_summary,
            "persona_evaluations": review.persona_evaluations,
            "verified_claims": review.verified_claims,
            "receipt_keys": review.receipt_keys,
            "total_tokens": review.total_tokens,
            "total_latency_ms": review.total_latency_ms,
            "estimated_cost_usd": review.estimated_cost_usd,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        }


@council_router.post("/evaluate/{entry_id}")
async def evaluate_entry_in_shadow_mode(
    entry_id: UUID,
    force_refresh: bool = Query(
        False, description="Force re-evaluation even if review exists"
    ),
) -> dict[str, Any]:
    """
    Trigger multi-agent council shadow evaluation for an entry.
    Runs 4 personas, verifies claims with citation offsets, and stores in review queue without modifying alerts.
    """
    try:
        review = await council_service.evaluate_entry_in_shadow_mode(
            entry_id=entry_id, force_refresh=force_refresh
        )
        return {
            "status": "ok",
            "review": {
                "id": str(review.id),
                "entry_id": str(review.entry_id),
                "shadow_status": review.status,
                "consensus_verdict": review.consensus_verdict,
                "consensus_score": review.consensus_score,
                "consensus_summary": review.consensus_summary,
                "persona_evaluations": review.persona_evaluations,
                "verified_claims": review.verified_claims,
                "total_tokens": review.total_tokens,
                "total_latency_ms": review.total_latency_ms,
                "estimated_cost_usd": review.estimated_cost_usd,
            },
        }
    except EntityNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@council_router.post("/review/{review_id}/status")
async def update_council_review_status(
    review_id: UUID,
    status: str = Query(
        ...,
        description="New status for review: 'approved', 'rejected', 'calibrated', 'pending_review'",
    ),
) -> dict[str, Any]:
    """Human calibration action on a council review queue item."""
    valid_statuses = {"shadow", "pending_review", "approved", "rejected", "calibrated"}
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of {sorted(valid_statuses)}",
        )

    updated = await council_service.update_review_status(review_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")

    return {
        "status": "ok",
        "review_id": str(review_id),
        "new_status": updated.status,
    }


@council_router.get("/circuit-breaker")
async def get_council_circuit_breaker() -> dict[str, Any]:
    """Retrieve 24-hour cost spend, token counts, and circuit breaker trip telemetry."""
    async with SqlAlchemyUnitOfWork() as uow:
        return await circuit_breaker.get_circuit_status(uow)
