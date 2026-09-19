"""
Autonomous LLM Triage API Router.
Controls the high-priority queue and backfilling operations.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from ai_security_monitor.application.services.autonomous_triage_service import (
    get_triage_service,
)

triage_router = APIRouter(prefix="/triage")


@triage_router.get("/queue")
async def get_queue_status():
    """Get current telemetry of the Autonomous LLM Triage Queue."""
    service = get_triage_service()
    return service.get_status()


@triage_router.post("/enqueue/{entry_id}")
async def enqueue_entry_for_triage(entry_id: UUID):
    """Enqueue a specific entry for deep autonomous LLM triage."""
    service = get_triage_service()
    success = await service.enqueue(entry_id)
    if not success:
        return {
            "status": "already_queued",
            "message": "Entry is already in the LLM triage queue.",
        }
    return {
        "status": "enqueued",
        "entry_id": str(entry_id),
        "queue_size": service.queue_size,
        "message": "Entry enqueued for deep LLM triage via Ollama.",
    }


@triage_router.post("/clear")
async def clear_triage_queue():
    """Flush the in-memory triage queue to eliminate backlogs."""
    service = get_triage_service()
    cleared = service.clear_queue()
    return {
        "status": "success",
        "cleared_count": cleared,
        "queue_size": service.queue_size,
        "message": f"Successfully flushed {cleared} entries from the triage queue.",
    }


@triage_router.post("/prioritize-frontier")
async def prioritize_frontier_models(
    limit: int = Query(
        default=25, ge=1, le=100, description="Max frontier models & breakthrough research to enqueue"
    )
):
    """Clear stale queue items and prioritize frontier models and landmark arXiv research."""
    service = get_triage_service()
    enqueued = await service.backfill_high_priority(limit=limit)
    return {
        "status": "success",
        "enqueued_count": enqueued,
        "queue_size": service.queue_size,
        "message": f"Prioritized {enqueued} frontier models & landmark arXiv papers for autonomous GPU/LLM triage.",
    }


@triage_router.post("/push-all")
async def push_all_queued():
    """Push and process all queued entries to the website immediately."""
    service = get_triage_service()
    pushed = await service.push_all_queued()
    return {
        "status": "success",
        "pushed_count": pushed,
        "queue_size": service.queue_size,
        "message": f"Successfully pushed {pushed} queued items to website.",
    }


@triage_router.post("/mode")
async def toggle_hold_mode(
    hold: bool = Query(
        default=True,
        description="True = hold queue until live sweep; False = continuous background worker",
    )
):
    """Toggle triage queue hold mode."""
    service = get_triage_service()
    current = service.set_hold_mode(hold)
    return {
        "status": "success",
        "hold_until_sweep": current,
        "message": f"Queue hold mode set to {current}.",
    }


