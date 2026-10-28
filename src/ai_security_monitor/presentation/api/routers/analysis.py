"""
Analysis API router.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.infrastructure.analyzers.base import analyzer_registry

analysis_router = APIRouter(prefix="/analysis")


class QuickAnalyzeRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Title or headline for analysis")
    summary: str | None = ""
    content: str | None = ""
    raw_text: str | None = None
    category: str = "ai_tech"
    model: str = "heuristic"
    tags: list[str] = Field(default_factory=list)


@analysis_router.post("/quick")
@analysis_router.post("/triage")
async def quick_analyze(req: QuickAnalyzeRequest):
    """Perform on-demand AI triage and architecture correlation on raw text using heuristic or real Ollama LLM."""
    analyzer_name = (
        "ollama"
        if req.model in ["ollama", "llm", "groq", "openrouter", "local"]
        else "heuristic"
    )
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
        "ai_models": Category.AI_MODELS,
        "cyber_tools": Category.CYBER_TOOLS,
    }
    cat = cat_map.get(req.category.lower(), Category.AI_TECH)
    summary_text = req.raw_text or req.summary or req.content or ""
    effective_title = req.title.strip()
    if not effective_title:
        first_line = summary_text.strip().split("\n")[0].strip()
        effective_title = first_line[:80] if first_line else "AI Technology Analysis"

    dummy_entry = Entry(
        source_id=uuid4(),
        title=effective_title,
        url="https://example.com/sandbox-triage",
        content_hash="sandbox_hash",
        summary=summary_text,
        published_at=datetime.now(UTC),
        category=cat,
        tags=req.tags,
    )

    from ai_security_monitor.application.services.multi_agent_council import (
        multi_agent_council,
    )

    triage_res = await triage_analyzer.analyze(dummy_entry)
    blast_res = await blast_analyzer.analyze(dummy_entry)
    council_res = await multi_agent_council.debate_and_critique(
        title=effective_title,
        summary=summary_text,
        category=cat.value,
    )

    return {
        "title": effective_title,
        "threat_velocity": triage_res.threat_velocity,
        "severity_index": triage_res.severity_index,
        "blast_radius_score": blast_res.blast_radius_score,
        "affected_ecosystem": blast_res.affected_ecosystem or [],
        "attack_vector": triage_res.attack_vector or "Unspecified attack vector",
        "risk_assessment": triage_res.risk_assessment or "Pending assessment",
        "mitigation": triage_res.mitigation
        or "Follow industry best practices and apply latest patches.",
        "attack_archetype": triage_res.attack_archetype,
        "weaponization_potential": triage_res.weaponization_potential,
        "model": triage_res.model or analyzer_name,
        "triage": triage_res,
        "blast_radius": blast_res,
        "council": council_res.to_dict(),
    }


async def _execute_batch_analysis(limit: int = 50) -> int:
    """Analyze unanalyzed entries in the database using the configured analyzer and blast engine."""
    from sqlalchemy import select

    from ai_security_monitor.config.settings import settings
    from ai_security_monitor.domain.entities import Analysis, AnalysisModel
    from ai_security_monitor.infrastructure.database.models import (
        AnalysisModel as AnalysisModelDB,
    )
    from ai_security_monitor.infrastructure.database.models import EntryModel
    from ai_security_monitor.infrastructure.database.unit_of_work import (
        SqlAlchemyUnitOfWork,
    )

    analyzer = analyzer_registry.create(settings.analyzer.default_model)
    blast_engine = analyzer_registry.create("blast_radius")

    async with SqlAlchemyUnitOfWork() as uow:
        stmt = (
            select(EntryModel)
            .outerjoin(AnalysisModelDB, EntryModel.id == AnalysisModelDB.entry_id)
            .where(AnalysisModelDB.id.is_(None))
            .order_by(EntryModel.created_at.desc())
            .limit(limit)
        )
        result = await uow.session.execute(stmt)
        models = result.scalars().all()
        entries = [uow.entries._model_to_entity(m) for m in models]

        analyzed_count = 0
        for entry in entries:
            analysis_res = await analyzer.analyze(entry)
            blast_res = await blast_engine.analyze(entry)

            combined_ecosystem = sorted(
                set(
                    (analysis_res.affected_ecosystem or [])
                    + (blast_res.affected_ecosystem or [])
                )
            )
            analysis = Analysis(
                entry_id=entry.id,
                attack_vector=analysis_res.attack_vector
                or "Standard Architecture Pattern",
                risk_assessment=analysis_res.risk_assessment
                or "Production / Stable Implementation",
                mitigation=analysis_res.mitigation
                or "Refer to official documentation and release notes.",
                threat_velocity=analysis_res.threat_velocity,
                severity_index=analysis_res.severity_index,
                blast_radius_score=blast_res.blast_radius_score,
                affected_ecosystem=combined_ecosystem,
                is_pre_cve_warning=False,
                attack_archetype=analysis_res.attack_archetype,
                weaponization_potential=analysis_res.weaponization_potential
                or "Production Ready",
                model=AnalysisModel.HEURISTIC,
                confidence=0.85,
            )
            await uow.analyses.add(analysis)
            analyzed_count += 1

        if analyzed_count > 0:
            await uow.commit()

        return analyzed_count


@analysis_router.post("/run-batch")
async def run_batch_analysis(
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of unanalyzed database entries to analyze",
    ),
):
    """Analyze unanalyzed entries in the database without running a network sweep."""
    analyzed_count = await _execute_batch_analysis(limit=limit)
    return {
        "status": "success",
        "analyzed_count": analyzed_count,
        "message": f"Successfully analyzed {analyzed_count} unanalyzed database entries.",
    }
