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
        return {"status": "already_queued", "message": "Entry is already in the LLM triage queue."}
    return {
        "status": "enqueued",
        "entry_id": str(entry_id),
        "queue_size": service.queue_size,
        "message": "Entry enqueued for deep LLM triage via Ollama."
    }


@triage_router.post("/backfill")
async def backfill_high_priority_triage(
    limit: int = Query(default=10, ge=1, le=50, description="Max high-velocity entries to enqueue")
):
    """Backfill and enqueue top high-velocity un-triaged entries for LLM processing."""
    service = get_triage_service()
    enqueued_count = await service.backfill_high_priority(limit=limit)
    return {
        "status": "success",
        "enqueued_count": enqueued_count,
        "queue_size": service.queue_size,
        "message": f"Enqueued {enqueued_count} high-priority threats for autonomous LLM triage."
    }
