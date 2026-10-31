"""
Autonomous Research Loop Service (Pillar 4 / Step A.1).

Executes an autonomous multi-source hybrid retrieval and synthesis loop:
1. Multi-source hybrid retrieval:
   - Semantic Vector Search (sqlite-vec entries_vec KNN with cosine fallback)
   - Knowledge Graph Intersection (uow.entities model, benchmark, repo timeline matching)
   - Heat & Velocity Ranking (half-life decay and star/adoption velocity)
2. Strict 14-day news freshness window enforcement.
3. Structured research dossier synthesis:
   - Executive Summary
   - Synthesized Findings & Technical Implications
   - Corroborating Evidence & Knowledge Graph Entities
   - Source Citations with IDs & URLs
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ai_security_monitor.application.services.ai_entity_extractor import (
    AIEntityExtractor,
)
from ai_security_monitor.application.services.heat_ranking_service import (
    heat_ranking_service,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.repositories import (
    EntryFilters,
    PaginationParams,
)
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service,
)
from ai_security_monitor.infrastructure.analyzers.llm_analyzer import LLMAnalyzer
from ai_security_monitor.infrastructure.analyzers.slm_circuit_breaker import (
    slm_circuit_breaker,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

STATIC_RESEARCH_SYSTEM_PROMPT = """You are an Autonomous AI Principal Research Architect.
Synthesize an evidence-grounded, technical research dossier answering the user's research query.
Requirements:
1. Executive Summary: High-level technical takeaway and state of the art based strictly on the provided sources.
2. Technical Implications: Architectural patterns, inference runtimes (vLLM, SGLang, Ollama), compute constraints, and quantitative benchmark scores.
3. Be concise, dense with technical facts, and avoid marketing hype or buzzwords."""


def _is_fresh(pub: datetime | None, cutoff: datetime) -> bool:
    """Safe comparison between offset-aware and offset-naive datetimes."""
    if not pub:
        return False
    p = pub if pub.tzinfo is not None else pub.replace(tzinfo=UTC)
    c = cutoff if cutoff.tzinfo is not None else cutoff.replace(tzinfo=UTC)
    return p >= c


class AutonomousResearchService:
    """Orchestrates hybrid retrieval and synthesis for autonomous deep AI research."""

    def __init__(self, max_freshness_days: int = 14) -> None:
        self.max_freshness_days = min(max(1, max_freshness_days), 14)

    async def run_research_loop(
        self,
        query: str,
        max_sources: int = 10,
        include_entities: bool = True,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> str:
        """Run the end-to-end autonomous research loop and return a synthesized Markdown dossier."""
        clean_query = query.strip()
        if not clean_query:
            return "⚠️ Research query cannot be empty."

        safe_max_sources = min(max(1, max_sources), 30)
        retrieval_result = await self.retrieve_hybrid_context(
            query=clean_query,
            max_sources=safe_max_sources,
            include_entities=include_entities,
            uow=uow,
        )

        entries = retrieval_result["entries"]
        matched_entities = retrieval_result["matched_entities"]
        scores = retrieval_result["scores"]

        if not entries:
            return (
                f"# 🔬 Autonomous AI Research Dossier: {clean_query}\n\n"
                f"> **Freshness Window:** {self.max_freshness_days} Days | **Sources Found:** 0\n\n"
                "### 📌 Executive Summary\n"
                f"No verified intelligence entries matching '{clean_query}' were found in the database "
                f"within the {self.max_freshness_days}-day freshness window. Ingest newer dispatches or broaden search terms."
            )

        return await self.synthesize_dossier(
            query=clean_query,
            entries=entries,
            matched_entities=matched_entities,
            scores=scores,
        )

    async def retrieve_hybrid_context(
        self,
        query: str,
        max_sources: int = 10,
        include_entities: bool = True,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> dict[str, Any]:
        """Multi-source hybrid retrieval: Semantic search + Entity graph + Heat & velocity ranking."""
        now = datetime.now(UTC)
        since_date = now - timedelta(days=self.max_freshness_days)

        candidate_map: dict[UUID, Entry] = {}
        semantic_scores: dict[UUID, float] = {}
        entity_matches: list[dict[str, Any]] = []
        entity_match_counts: dict[UUID, int] = {}
        velocity_scores: dict[UUID, float] = {}

        query_vec = embedding_service.embed_text(query)

        # Context manager pattern: reuse existing UOW or instantiate fresh session
        if uow is not None:
            active_uow = uow
            owns_uow = False
        else:
            active_uow = SqlAlchemyUnitOfWork()
            owns_uow = True

        try:
            if owns_uow:
                await active_uow.__aenter__()

            # -------------------------------------------------------------
            # Leg 1: Semantic Vector Search (sqlite-vec KNN + Cosine fallback)
            # -------------------------------------------------------------
            try:
                from sqlalchemy import text

                vec_json = json.dumps(query_vec)
                knn_sql = text(
                    "SELECT entry_id, distance FROM entries_vec "
                    "WHERE embedding MATCH :vec "
                    "ORDER BY distance LIMIT :k"
                )
                res = await active_uow.session.execute(
                    knn_sql, {"vec": vec_json, "k": max_sources * 3}
                )
                rows = res.fetchall()
                for row in rows:
                    raw_id = str(row[0])
                    dist = float(row[1])
                    try:
                        entry_uuid = UUID(hex=raw_id.replace("-", ""))
                        cand_entry = await active_uow.entries.get(entry_uuid)
                        if (
                            cand_entry
                            and _is_fresh(cand_entry.published_at, since_date)
                            and not getattr(cand_entry, "is_purged", False)
                        ):
                            # Cosine / L2 distance conversion
                            sim = max(0.0, min(1.0, round(1.0 - (dist / 2.0), 3)))
                            semantic_scores[cand_entry.id] = sim
                            candidate_map[cand_entry.id] = cand_entry
                    except Exception as parse_err:
                        logger.debug(f"Row UUID parse error in vector KNN: {parse_err}")
            except Exception as vec_err:
                logger.debug(f"sqlite-vec KNN search unavailable: {vec_err}")

            # Fallback / Augment: scan recent entries if vector KNN yielded insufficient hits
            if len(candidate_map) < max_sources:
                try:
                    recent_entries = await active_uow.entries.list(
                        filters=EntryFilters(since=since_date),
                        pagination=PaginationParams(limit=40, offset=0),
                    )
                    for r_entry in recent_entries:
                        if (
                            _is_fresh(r_entry.published_at, since_date)
                            and not getattr(r_entry, "is_purged", False)
                        ):
                            if r_entry.id not in semantic_scores:
                                r_text = f"{r_entry.title or ''} {r_entry.summary or ''}".strip()
                                if r_text:
                                    r_vec = embedding_service.embed_text(r_text)
                                    sim = embedding_service.cosine_similarity(
                                        query_vec, r_vec
                                    )
                                    semantic_scores[r_entry.id] = round(sim, 3)
                                else:
                                    semantic_scores[r_entry.id] = 0.0
                            candidate_map[r_entry.id] = r_entry
                except Exception as list_err:
                    logger.debug(f"Recent entries list fallback error: {list_err}")

            # -------------------------------------------------------------
            # Leg 2: Entity Graph Intersection (Pillar 4 Knowledge Graph)
            # -------------------------------------------------------------
            if include_entities and hasattr(active_uow, "entities"):
                try:
                    # Extract entities from query
                    extracted_from_query = AIEntityExtractor.extract_from_text(
                        query, entry_id=uuid4()
                    )
                    query_terms: set[str] = {
                        e.name for e in extracted_from_query
                    }
                    query_terms.update(
                        e.display_name.lower() for e in extracted_from_query
                    )

                    # Also extract significant keyword tokens (length >= 3)
                    words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", query.lower())
                    stopwords = {
                        "the",
                        "and",
                        "for",
                        "with",
                        "from",
                        "what",
                        "how",
                        "recent",
                        "breakthroughs",
                        "analyze",
                        "analysis",
                        "report",
                    }
                    for w in words:
                        if w not in stopwords:
                            query_terms.add(w)

                    # Query timeline for candidate entity names
                    for term in list(query_terms)[:8]:
                        timeline_records = await active_uow.entities.query_timeline(
                            name=term,
                            days=self.max_freshness_days,
                            limit=max_sources,
                        )
                        for rec in timeline_records:
                            entity_matches.append(rec)
                            raw_eid = rec.get("entry_id")
                            if raw_eid:
                                try:
                                    eid = (
                                        raw_eid
                                        if isinstance(raw_eid, UUID)
                                        else UUID(str(raw_eid))
                                    )
                                    entity_match_counts[eid] = (
                                        entity_match_counts.get(eid, 0) + 1
                                    )
                                    if eid not in candidate_map:
                                        linked_entry = await active_uow.entries.get(
                                            eid
                                        )
                                        if (
                                            linked_entry
                                            and _is_fresh(linked_entry.published_at, since_date)
                                            and not getattr(
                                                linked_entry, "is_purged", False
                                            )
                                        ):
                                            candidate_map[eid] = linked_entry
                                except Exception as ent_link_err:
                                    logger.debug(
                                        f"Entity timeline entry lookup error: {ent_link_err}"
                                    )
                except Exception as ent_err:
                    logger.debug(f"Entity graph intersection error: {ent_err}")

            # -------------------------------------------------------------
            # Leg 3: Heat & Velocity Ranking
            # -------------------------------------------------------------
            try:
                high_velocity_candidates = await active_uow.entries.list(
                    filters=EntryFilters(
                        since=since_date, sort_by="velocity"
                    ),
                    pagination=PaginationParams(limit=max_sources, offset=0),
                )
                for hv_entry in high_velocity_candidates:
                    if (
                        _is_fresh(hv_entry.published_at, since_date)
                        and not getattr(hv_entry, "is_purged", False)
                    ):
                        candidate_map[hv_entry.id] = hv_entry
            except Exception as vel_err:
                logger.debug(f"High velocity query error: {vel_err}")

            # Calculate heat & velocity scores for all candidate entries
            for eid, entry in candidate_map.items():
                vel = 50
                if entry.analysis and hasattr(entry.analysis, "threat_velocity"):
                    vel = entry.analysis.threat_velocity
                elif hasattr(entry, "threat_velocity"):
                    vel = getattr(entry, "threat_velocity", 50) or 50
                velocity_scores[eid] = min(1.0, max(0.0, float(vel) / 100.0))

            # Attach decision brief and entities if not already attached
            for eid, entry in candidate_map.items():
                if entry.analysis is None and hasattr(active_uow, "analyses"):
                    try:
                        an = await active_uow.analyses.get_by_entry(eid)
                        if an:
                            entry.analysis = an
                    except Exception:
                        pass
                if (not entry.entities) and hasattr(active_uow, "entities"):
                    try:
                        ents = await active_uow.entities.get_by_entry(eid)
                        if ents:
                            entry.entities = ents
                    except Exception:
                        pass

        finally:
            if owns_uow:
                await active_uow.__aexit__(None, None, None)

        # -------------------------------------------------------------
        # Score Fusion & Top-K Ranking
        # -------------------------------------------------------------
        scored_candidates: list[tuple[float, Entry, dict[str, float]]] = []

        for eid, entry in candidate_map.items():
            # Invariant: Strict 14-day freshness window
            if (
                not _is_fresh(entry.published_at, since_date)
                or getattr(entry, "is_purged", False)
            ):
                continue

            s_sem = semantic_scores.get(eid, 0.0)
            ent_count = entity_match_counts.get(eid, 0)
            s_ent = min(0.30, ent_count * 0.15) if ent_count > 0 else 0.0
            s_vel = velocity_scores.get(eid, 0.5) * 0.20
            heat_val, _ = heat_ranking_service.compute_entry_heat(entry, now=now)
            s_heat = heat_val * 0.10

            # Fused score
            combined = round((0.40 * s_sem) + s_ent + s_vel + s_heat, 4)
            scored_candidates.append(
                (
                    combined,
                    entry,
                    {
                        "semantic": round(s_sem, 3),
                        "entity": round(s_ent, 3),
                        "velocity": round(s_vel, 3),
                        "heat": round(s_heat, 3),
                        "combined": combined,
                    },
                )
            )

        # Sort descending by fused score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        top_candidates = scored_candidates[:max_sources]

        top_entries = [c[1] for c in top_candidates]
        score_breakdown = {str(c[1].id): c[2] for c in top_candidates}

        # Deduplicate matched entities
        seen_entity_keys: set[tuple[str, str]] = set()
        deduped_entities: list[dict[str, Any]] = []
        for ent in entity_matches:
            ekey = (str(ent.get("entity_type")), str(ent.get("name")))
            if ekey not in seen_entity_keys:
                seen_entity_keys.add(ekey)
                deduped_entities.append(ent)

        # Also incorporate entities attached to top entries
        for entry in top_entries:
            for e in entry.entities:
                ekey = (e.entity_type.value, e.name)
                if ekey not in seen_entity_keys:
                    seen_entity_keys.add(ekey)
                    deduped_entities.append(
                        {
                            "entry_id": entry.id,
                            "entity_type": e.entity_type.value,
                            "name": e.name,
                            "display_name": e.display_name,
                            "metric_value": e.metric_value,
                            "context": e.context,
                            "confidence": e.confidence,
                            "entry_title": entry.title,
                            "entry_url": entry.url,
                            "category": entry.category.value
                            if hasattr(entry.category, "value")
                            else str(entry.category),
                            "published_at": entry.published_at.isoformat()
                            if entry.published_at
                            else None,
                        }
                    )

        return {
            "entries": top_entries,
            "matched_entities": deduped_entities,
            "scores": score_breakdown,
            "freshness_cutoff": since_date.isoformat(),
        }

    async def synthesize_dossier(
        self,
        query: str,
        entries: list[Entry],
        matched_entities: list[dict[str, Any]],
        scores: dict[str, dict[str, float]],
    ) -> str:
        """Synthesize structured research report containing all 4 required sections."""
        now = datetime.now(UTC)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M UTC")

        # 1. Executive Summary Synthesis
        exec_summary = await self._synthesize_executive_summary(query, entries)

        # 2. Synthesized Findings & Technical Implications
        findings_markdown = self._synthesize_technical_findings(entries)

        # 3. Corroborating Evidence & Knowledge Graph Entities
        evidence_markdown = self._format_entity_knowledge_graph(matched_entities)

        # 4. Source Citations with IDs & URLs
        citations_markdown = self._format_source_citations(entries, scores)

        # Assemble full dossier
        lines = [
            f"# 🔬 Autonomous AI Research Dossier: {query}",
            f"> **Generated:** {timestamp_str} | **Monitored Sources:** {len(entries)} | **Freshness Guard:** ≤ {self.max_freshness_days} Days (Active)",
            "",
            "## 📌 Executive Summary",
            exec_summary,
            "",
            "## ⚙️ Synthesized Findings & Technical Implications",
            findings_markdown,
            "",
            "## 🌐 Corroborating Evidence & Knowledge Graph Entities",
            evidence_markdown,
            "",
            "## 📚 Source Citations & References",
            citations_markdown,
        ]

        return "\n".join(lines)

    async def _synthesize_executive_summary(
        self, query: str, entries: list[Entry]
    ) -> str:
        """Generate high-level executive summary via LLM or deterministic fallback."""
        if not entries:
            return f"No recent dispatches found for query: '{query}'."

        # Compile compact source summaries
        context_snippets = []
        for i, e in enumerate(entries[:5], 1):
            brief_text = ""
            if e.analysis and e.analysis.decision_brief:
                brief = e.analysis.decision_brief
                brief_text = brief.get("event_summary") or brief.get(
                    "technical_significance", ""
                )
            snippet = brief_text or e.summary or e.title
            context_snippets.append(f"[{i}] {e.title}: {snippet[:200]}")

        context_str = "\n".join(context_snippets)

        # Attempt LLM synthesis if circuit breaker allows
        if not slm_circuit_breaker.is_tripped:
            try:
                analyzer = LLMAnalyzer(config={"tier": "cloud_frontier"})
                prompt = (
                    f"Research Topic: {query}\n"
                    f"Verified Recent Sources (Past 14 Days):\n{context_str}\n\n"
                    "Synthesize a concise 2-3 paragraph executive summary evaluating current progress, key breakthroughs, and operational status."
                )
                if (
                    analyzer.tier == "cloud_frontier"
                    and hasattr(analyzer, "_call_groq")
                    and analyzer.client is not None
                ):
                    raw = await analyzer._call_groq(prompt, user_prompt=prompt)
                    if isinstance(raw, dict) and "summary" in raw:
                        return str(raw["summary"]).strip()
                    elif isinstance(raw, tuple) and isinstance(raw[0], dict):
                        return str(
                            raw[0].get("summary")
                            or raw[0].get("executive_summary", "")
                        ).strip()
            except Exception as e:
                logger.debug(f"Research loop LLM summary bypassed: {e}")

        # Deterministic executive summary fallback
        primary = entries[0]
        primary_title = primary.title
        primary_summary = primary.summary or primary_title

        summary_bullets = [
            f"Recent technical developments centered on **{query}** reveal notable convergence across {len(entries)} verified dispatches within the 14-day freshness window.",
            f"Primary anchor: **{primary_title}** — {primary_summary[:280]}...",
        ]

        if len(entries) > 1:
            secondary_titles = ", ".join(f"'{e.title[:45]}...'" for e in entries[1:4])
            summary_bullets.append(
                f"Corroborating activity across the ecosystem is reinforced by releases including {secondary_titles}."
            )

        return "\n\n".join(summary_bullets)

    def _synthesize_technical_findings(self, entries: list[Entry]) -> str:
        """Synthesize technical implications, runtime dynamics, and decision briefs."""
        sections: list[str] = []

        for i, entry in enumerate(entries, 1):
            title = entry.title
            category = (
                entry.category.value
                if hasattr(entry.category, "value")
                else str(entry.category)
            )
            date_str = (
                entry.published_at.strftime("%Y-%m-%d")
                if entry.published_at
                else "Recent"
            )

            # Inspect decision brief if available
            brief = None
            if entry.analysis and entry.analysis.decision_brief:
                brief = entry.analysis.decision_brief

            lines = [f"### {i}. {title} ({date_str}) — `{category}`"]

            if brief:
                ev_sum = brief.get("event_summary")
                tech_sig = brief.get("technical_significance")
                nov = brief.get("novelty_assessment", {})
                rec_action = brief.get("recommended_action")

                if ev_sum:
                    lines.append(f"- **What Happened:** {ev_sum}")
                if tech_sig:
                    lines.append(f"- **Technical Significance:** {tech_sig}")
                if isinstance(nov, dict) and nov.get("novelty_type"):
                    lines.append(
                        f"- **Novelty Grounding:** `{nov.get('novelty_type')}` — {nov.get('summary', '')}"
                    )
                if rec_action:
                    lines.append(f"- **Decision Vector:** `{rec_action}`")
            else:
                summary_text = (entry.summary or "").strip()
                if summary_text:
                    lines.append(f"- **Core Finding:** {summary_text}")

            # Extract technical signals (engines, context, params)
            combined_text = f"{title} {entry.summary or ''}"
            engines = re.findall(
                r"\b(vLLM|SGLang|Ollama|llama\.cpp|PyTorch|Triton|TensorRT|CUDA)\b",
                combined_text,
                re.I,
            )
            if engines:
                lines.append(
                    f"- **Inference / Engine Stack:** {', '.join(sorted(set(engines)))}"
                )

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def _format_entity_knowledge_graph(
        self, matched_entities: list[dict[str, Any]]
    ) -> str:
        """Format knowledge graph entities (models, benchmarks, repos) into structured markdown."""
        if not matched_entities:
            return "_No structured entity nodes detected for this query in the 14-day knowledge graph._"

        # Organize by EntityType
        type_groups: dict[str, list[dict[str, Any]]] = {}
        for ent in matched_entities:
            etype = str(ent.get("entity_type", "entity")).upper()
            type_groups.setdefault(etype, []).append(ent)

        lines: list[str] = []

        # Models & Benchmarks table
        lines.append(
            "| Entity Name | Type | Metric / Benchmark Value | Source Context |"
        )
        lines.append(
            "|:---|:---|:---|:---|"
        )

        for ent in matched_entities[:15]:
            name = ent.get("display_name") or ent.get("name") or "Unknown"
            etype = str(ent.get("entity_type", "")).upper()
            metric = ent.get("metric_value") or "—"
            raw_ctx = str(ent.get("context") or ent.get("entry_title") or "")
            clean_ctx = raw_ctx.replace("|", "/").replace("\n", " ").strip()
            if len(clean_ctx) > 80:
                clean_ctx = clean_ctx[:77] + "..."
            lines.append(f"| **{name}** | `{etype}` | `{metric}` | {clean_ctx} |")

        return "\n".join(lines)

    def _format_source_citations(
        self, entries: list[Entry], scores: dict[str, dict[str, float]]
    ) -> str:
        """Format numbered citations with IDs, URLs, and fused scores."""
        citations: list[str] = []

        for i, entry in enumerate(entries, 1):
            date_str = (
                entry.published_at.strftime("%Y-%m-%d")
                if entry.published_at
                else "Recent"
            )
            cat = (
                entry.category.value
                if hasattr(entry.category, "value")
                else str(entry.category)
            )
            eid_str = str(entry.id)
            score_meta = scores.get(eid_str, {})
            score_tag = f"Score: {score_meta.get('combined', 0.0):.2f}"

            lines = [
                f"**[{i}] [{entry.title}]({entry.url})**",
                f"- **Published:** {date_str} | **Category:** `{cat}` | **{score_tag}**",
                f"- **Entry UUID:** `{eid_str}`",
            ]

            citations.append("\n".join(lines))

        return "\n\n".join(citations)


# Global singleton instance
autonomous_research_service = AutonomousResearchService()
