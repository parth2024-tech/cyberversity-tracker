"""
Analysis API router.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from ai_security_monitor.application.services.monitor_service import MonitorService
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.base import analyzer_registry

analysis_router = APIRouter(prefix="/analysis")


class QuickAnalyzeRequest(BaseModel):
    title: str
    summary: str | None = ""
    category: str = "vulnerabilities"
    tags: list[str] = []


@analysis_router.post("/quick")
async def quick_analyze(req: QuickAnalyzeRequest):
    """Perform on-demand AI triage and blast radius correlation on raw text."""
    triage_analyzer = analyzer_registry.create("heuristic")
    blast_analyzer = analyzer_registry.create("blast_radius")

    dummy_entry = Entry(
        source_id=uuid4(),
        title=req.title,
        url="https://example.com",
        content_hash="test",
        summary=req.summary or "",
        published_at=None,
        category=Category.VULNERABILITIES,
        tags=req.tags
    )

    triage_res = await triage_analyzer.analyze(dummy_entry)
    blast_res = await blast_analyzer.analyze(dummy_entry)

    return {
        "title": req.title,
        "triage": triage_res,
        "blast_radius": blast_res
    }


@analysis_router.post("/run-batch")
async def run_batch_analysis(background_tasks: BackgroundTasks):
    """Trigger background batch analysis on any unanalyzed entries."""
    service = MonitorService()
    background_tasks.add_task(service.fetch_all)
    return {"status": "initiated", "message": "Batch analysis pipeline queued in background."}
