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
    content: str | None = ""
    category: str = "vulnerabilities"
    model: str = "heuristic"
    tags: list[str] = []


@analysis_router.post("/quick")
async def quick_analyze(req: QuickAnalyzeRequest):
    """Perform on-demand AI triage and blast radius correlation on raw text using heuristic or real Ollama LLM."""
    analyzer_name = "ollama" if req.model in ["ollama", "llm", "groq", "openrouter", "local"] else "heuristic"
    try:
        triage_analyzer = analyzer_registry.create(analyzer_name)
    except Exception:
        triage_analyzer = analyzer_registry.create("heuristic")

    blast_analyzer = analyzer_registry.create("blast_radius")

    cat_map = {
        "vulnerabilities": Category.VULNERABILITIES,
        "ai_tech": Category.AI_TECH,
        "ai_research": Category.AI_RESEARCH,
        "cybersecurity": Category.CYBERSECURITY,
        "github_trending": Category.GITHUB_TRENDING,
    }
    cat = cat_map.get(req.category.lower(), Category.VULNERABILITIES)
    summary_text = req.summary or req.content or ""

    dummy_entry = Entry(
        source_id=uuid4(),
        title=req.title,
        url="https://example.com/sandbox-triage",
        content_hash="sandbox_hash",
        summary=summary_text,
        published_at=None,
        category=cat,
        tags=req.tags
    )

    triage_res = await triage_analyzer.analyze(dummy_entry)
    blast_res = await blast_analyzer.analyze(dummy_entry)

    return {
        "title": req.title,
        "threat_velocity": triage_res.threat_velocity,
        "severity_index": triage_res.severity_index,
        "blast_radius_score": blast_res.blast_radius_score,
        "affected_ecosystem": blast_res.affected_ecosystem or [],
        "attack_vector": triage_res.attack_vector or "Unspecified attack vector",
        "risk_assessment": triage_res.risk_assessment or "Pending assessment",
        "mitigation": triage_res.mitigation or "Follow industry best practices and apply latest patches.",
        "attack_archetype": triage_res.attack_archetype,
        "weaponization_potential": triage_res.weaponization_potential,
        "model": triage_res.model or analyzer_name,
        "triage": triage_res,
        "blast_radius": blast_res
    }


@analysis_router.post("/run-batch")
async def run_batch_analysis(background_tasks: BackgroundTasks):
    """Trigger background batch analysis on any unanalyzed entries."""
    service = MonitorService()
    background_tasks.add_task(service.fetch_all)
    return {"status": "initiated", "message": "Batch analysis pipeline queued in background."}
