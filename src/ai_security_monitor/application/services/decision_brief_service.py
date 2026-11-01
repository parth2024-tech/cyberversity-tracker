"""
Personal Intelligence Decision Brief Service.
Transforms high-value intelligence items into concise, evidence-grounded,
personalized decisions answering the five core questions:
1. What happened? (Factual summary)
2. Why does it matter? (Technical significance)
3. What's new? (Novelty grounded in local vector memory)
4. What is the impact on my stack/watchlist? (Personalized relevance)
5. What should I do next? (Validated action enum)
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ai_security_monitor.application.services.claim_verifier import (
    ScopedSubstringVerifier,
    extract_grounding_corpus,
    normalize_text,
)
from ai_security_monitor.application.services.triage_scoring_pipeline import (
    SourceAuthoritySignal,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Analysis, Entry
from ai_security_monitor.domain.repositories import PaginationParams
from ai_security_monitor.domain.value_objects import (
    DecisionAction,
    EvidenceAssessment,
    EvidenceConfidence,
    HistoricalComparison,
    NoveltyAssessment,
    NoveltyType,
    PersonalDecisionBrief,
    StackImpactLevel,
    StackRelevance,
)
from ai_security_monitor.infrastructure.analyzers.blast_radius_analyzer import (
    BlastRadiusAnalyzer,
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

STATIC_DECISION_BRIEF_SYSTEM_PROMPT = """You are an Elite Personal Intelligence Decision Architect.
Generate an evidence-grounded, highly personalized Decision Brief for a technical practitioner.
Do NOT output marketing hype, vague filler, or ungrounded claims.

Answer three core questions in strict JSON format:
1. "event_summary": Concise factual summary of what happened. Separate source-reported facts from inferred implications. Identify the project, model, version, or paper. Include dates and links if available.
2. "significance": Practical technical significance. Focus on performance, memory/compute constraints, developer productivity, hardware requirements, or adoption barriers.
3. "novelty_summary": Distinct explanation of what is genuinely novel versus an incremental update compared to the provided historical context. Explicitly note what remains uncertain.

Output MUST be a JSON object with keys:
{
  "event_summary": "...",
  "significance": "...",
  "novelty_summary": "...",
  "uncertainties": ["..."]
}"""


class DecisionBriefService:
    """Orchestrates structured 5-question personal decision briefs."""

    def __init__(self) -> None:
        self.claim_verifier = ScopedSubstringVerifier()
        self.authority_signal = SourceAuthoritySignal()

    async def get_or_generate_brief(
        self,
        entry: Entry,
        uow: SqlAlchemyUnitOfWork | None = None,
        force: bool = False,
    ) -> PersonalDecisionBrief:
        """Retrieve existing decision brief from analysis or generate a fresh one."""
        # 1. Caching check: reuse valid existing brief if not forced
        if not force and entry.analysis and entry.analysis.decision_brief:
            try:
                cached = PersonalDecisionBrief.from_dict(entry.analysis.decision_brief)
                if cached and cached.analysis_version == "v1-decision-brief":
                    return cached
            except Exception as e:
                logger.debug(f"Failed to parse cached decision brief: {e}")

        # 2. Generate fresh brief
        return await self.generate_decision_brief(entry, uow=uow)

    async def generate_decision_brief(
        self,
        entry: Entry,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> PersonalDecisionBrief:
        """Synthesize a complete 5-question Decision Brief."""
        # Step A: Retrieve historical vector comparisons (Q3 context)
        historical_comparisons = await self.retrieve_historical_comparisons(
            entry, uow=uow, limit=3
        )

        # Step B: Personal Stack & Watchlist Relevance (Q4)
        stack_relevance = await self.evaluate_stack_relevance(entry, uow=uow)

        # Step C: Deterministic Evidence Assessment & Confidence (Section 3)
        evidence_assessment = self.evaluate_evidence(entry)

        # Step D: Deterministic Recommended Action (Q5)
        recommended_action, action_rationale = self.determine_recommended_action(
            entry=entry,
            evidence=evidence_assessment,
            stack_relevance=stack_relevance,
        )

        # Step E: Factual Synthesis via LLM (Q1, Q2, and Novelty nuance Q3)
        event_summary, significance, novelty_assessment = await self._synthesize_q1_q2_q3(
            entry=entry,
            historical_comparisons=historical_comparisons,
            stack_relevance=stack_relevance,
            evidence=evidence_assessment,
        )

        # Step F: Assemble Source References
        source_refs = []
        if entry.url:
            source_refs.append(entry.url)
        for comp in historical_comparisons:
            if comp.source_url and comp.source_url not in source_refs:
                source_refs.append(comp.source_url)

        brief = PersonalDecisionBrief(
            event_summary=event_summary,
            significance=significance,
            novelty_assessment=novelty_assessment,
            historical_comparisons=historical_comparisons,
            stack_relevance=stack_relevance,
            evidence_assessment=evidence_assessment,
            recommended_action=recommended_action,
            action_rationale=action_rationale,
            source_references=source_refs,
            generated_at=datetime.now(UTC).isoformat(),
            analysis_version="v1-decision-brief",
        )

        # Step G: Persist to database if UOW is available
        await self._persist_brief(entry, brief, uow=uow)

        return brief

    async def retrieve_historical_comparisons(
        self,
        entry: Entry,
        uow: SqlAlchemyUnitOfWork | None = None,
        limit: int = 3,
    ) -> list[HistoricalComparison]:
        """Search local vector index (sqlite-vec entries_vec) and database for similar historical records."""
        entry_text = f"{entry.title or ''} {entry.summary or ''}".strip()
        if not entry_text:
            return []

        cand_vec = embedding_service.embed_text(entry_text)
        comparisons: list[HistoricalComparison] = []

        if uow is None:
            # Standalone fallback without UOW (e.g. unit test or memory mode)
            return comparisons

        try:
            # 1. Try sqlite-vec entries_vec virtual table
            from sqlalchemy import text

            vec_json = json.dumps(cand_vec)
            # Query nearest neighbors in entries_vec
            query_sql = text(
                "SELECT entry_id, distance FROM entries_vec "
                "WHERE embedding MATCH :vec "
                "ORDER BY distance LIMIT :k"
            )
            result = await uow.session.execute(query_sql, {"vec": vec_json, "k": limit + 5})
            rows = result.fetchall()

            for row in rows:
                hist_id_str = str(row[0])
                if hist_id_str == str(entry.id):
                    continue  # Skip self
                try:
                    hist_uuid = UUID(hex=hist_id_str.replace("-", ""))
                    hist_entry = await uow.entries.get(hist_uuid)
                    if hist_entry:
                        # Convert L2 or cosine distance to similarity score in [0.0, 1.0]
                        dist = float(row[1])
                        # sqlite-vec L2 distance: sim ~= max(0.0, 1.0 - dist / 2.0)
                        sim = max(0.0, min(1.0, round(1.0 - (dist / 2.0), 3)))
                        if sim >= 0.45:
                            pub_str = (
                                hist_entry.published_at.strftime("%Y-%m-%d")
                                if hist_entry.published_at
                                else None
                            )
                            comparisons.append(
                                HistoricalComparison(
                                    entry_id=str(hist_entry.id),
                                    title=hist_entry.title,
                                    published_at=pub_str,
                                    similarity_score=sim,
                                    relation="prior_work" if sim >= 0.70 else "related_ecosystem",
                                    source_url=hist_entry.url,
                                )
                            )
                        if len(comparisons) >= limit:
                            break
                except Exception as row_err:
                    logger.debug(f"Row extraction error in vector search: {row_err}")

        except Exception as vec_err:
            logger.debug(f"sqlite-vec KNN query unavailable or not populated: {vec_err}")

        # 2. Fallback to querying recent database entries if entries_vec had insufficient matches
        if len(comparisons) < limit:
            try:
                # Retrieve recent non-purged entries from same category or general pool
                recent_entries = await uow.entries.list(
                    filters=None,
                    pagination=PaginationParams(limit=40, offset=0),
                )
                for h_entry in recent_entries:
                    if h_entry.id == entry.id:
                        continue
                    if any(c.entry_id == str(h_entry.id) for c in comparisons):
                        continue

                    h_text = f"{h_entry.title or ''} {h_entry.summary or ''}".strip()
                    if not h_text:
                        continue

                    h_vec = embedding_service.embed_text(h_text)
                    sim = embedding_service.cosine_similarity(cand_vec, h_vec)
                    threshold = 0.15 if embedding_service.is_fallback else 0.50
                    if sim >= threshold:
                        pub_str = (
                            h_entry.published_at.strftime("%Y-%m-%d")
                            if h_entry.published_at
                            else None
                        )
                        comparisons.append(
                            HistoricalComparison(
                                entry_id=str(h_entry.id),
                                title=h_entry.title,
                                published_at=pub_str,
                                similarity_score=round(sim, 3),
                                relation="prior_work" if sim >= 0.75 else "related_topic",
                                source_url=h_entry.url,
                            )
                        )
                    if len(comparisons) >= limit:
                        break
            except Exception as fb_err:
                logger.debug(f"Database historical search fallback error: {fb_err}")

        # Index candidate entry vector into entries_vec for future lookups
        try:
            from sqlalchemy import text

            upsert_sql = text(
                "INSERT OR REPLACE INTO entries_vec(entry_id, embedding) VALUES (:id, :vec)"
            )
            await uow.session.execute(
                upsert_sql,
                {"id": str(entry.id), "vec": json.dumps(cand_vec)},
            )
        except Exception:
            pass

        return comparisons[:limit]

    async def evaluate_stack_relevance(
        self,
        entry: Entry,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> StackRelevance:
        """Evaluate personal stack impact against active watchlist rules and ecosystem components."""
        text_corpus = f"{entry.title or ''} {entry.summary or ''} {' '.join(entry.tags or [])}".lower()
        if entry.metadata:
            text_corpus += f" {str(entry.metadata).lower()}"

        matched_rules: list[str] = []
        matched_technologies: set[str] = set()
        reasons: list[str] = []

        # 1. Check against active Watchlist Rules in DB
        active_rules = []
        if uow is not None:
            try:
                active_rules = await uow.watchlist.list(enabled_only=True)
            except Exception as e:
                logger.debug(f"Failed to fetch watchlist rules: {e}")

        for rule in active_rules:
            if rule.matches(entry):
                matched_rules.append(rule.name)
                for kw in rule.keywords:
                    kw_clean = kw.strip().lower()
                    if kw_clean and kw_clean in text_corpus:
                        matched_technologies.add(kw.strip())
                reasons.append(f"Direct match against watchlist rule '{rule.name}'")

        # 2. Correlate with AI Ecosystem Stack Map
        for tech_name, synonyms in BlastRadiusAnalyzer.AI_ECOSYSTEM_MAP.items():
            for syn in synonyms:
                pattern = r"\b" + re.escape(syn.lower()) + r"\b"
                if re.search(pattern, text_corpus):
                    matched_technologies.add(tech_name)
                    break

        # 3. Detect affected components
        affected_comps = sorted(matched_technologies)

        # 4. Determine Impact Level & Suggested Priority
        if matched_rules:
            impact_level = StackImpactLevel.DIRECT
            suggested_priority = "P0" if any("critical" in r.lower() or "production" in r.lower() for r in matched_rules) else "P1"
            direct_impact = (
                f"Modifies or updates tracked components ({', '.join(sorted(matched_technologies)[:3])}) "
                f"matching your active watchlist ({', '.join(matched_rules[:2])})."
            )
            indirect_impact = None
        elif matched_technologies:
            impact_level = StackImpactLevel.INDIRECT
            suggested_priority = "P1" if any(t in ("vLLM", "SGLang", "Ollama", "llama.cpp", "ONNX") for t in matched_technologies) else "P2"
            direct_impact = None
            indirect_impact = (
                f"Pertains to ecosystem frameworks ({', '.join(sorted(matched_technologies)[:3])}) "
                "relevant to local AI serving or developer infrastructure."
            )
            reasons.append(f"Framework overlap: {', '.join(sorted(matched_technologies)[:3])}")
        else:
            impact_level = StackImpactLevel.NO_MATCH
            suggested_priority = "P2"
            direct_impact = None
            indirect_impact = None
            reasons.append("No configured watchlist rules or tracked core technologies matched.")

        return StackRelevance(
            impact_level=impact_level,
            matching_watchlist_rules=matched_rules,
            matched_technologies=sorted(matched_technologies),
            direct_impact=direct_impact,
            indirect_impact=indirect_impact,
            affected_components=affected_comps[:5],
            suggested_priority=suggested_priority,
            reasons=reasons,
        )

    def evaluate_evidence(self, entry: Entry) -> EvidenceAssessment:
        """Deterministic evaluation of claim truth and source corroboration."""
        url = (entry.url or "").lower()
        title_lower = (entry.title or "").lower()
        meta = entry.metadata or {}

        # 1. Source type identification
        if "arxiv.org" in url:
            primary_source_type = "academic_preprint (arXiv)"
            is_official = True
        elif "github.com" in url:
            primary_source_type = "source_code_repository (GitHub)"
            is_official = True
        elif "huggingface.co" in url:
            primary_source_type = "model_weights_registry (Hugging Face)"
            is_official = True
        elif any(lab in url for lab in ("openai.com", "anthropic.com", "deepseek.com", "mistral.ai", "meta.com")):
            primary_source_type = "official_lab_dispatch"
            is_official = True
        elif any(social in url for social in ("twitter.com", "x.com", "t.co", "reddit.com")):
            primary_source_type = "social_media_discussion"
            is_official = False
        else:
            primary_source_type = "news_syndication"
            is_official = False

        # 2. Check reproducible artifacts
        has_artifact = bool(
            "github.com" in url
            or "huggingface.co" in url
            or meta.get("has_weights")
            or meta.get("has_code")
            or any(kw in title_lower for kw in ("open weights", "source code", "released", "weights release"))
        )

        # 3. Corroboration Count
        corroboration_count = int(meta.get("source_count", 1))

        # 4. Claim Verification Grounding Score
        corpus = extract_grounding_corpus(entry)
        corpus_norm = normalize_text(corpus)
        claim_tokens = re.findall(
            r"\b(?:\d+(?:\.\d+)?%?|\d+[bB]|mmlu|aime|gpqa|swe-bench)\b",
            f"{entry.title or ''} {entry.summary or ''}".lower(),
        )

        conflicting_signals = []
        if claim_tokens:
            verified_count = 0
            for tok in claim_tokens:
                present, _ = self.claim_verifier.check_substring_presence(tok, corpus_norm)
                if present:
                    verified_count += 1
                else:
                    conflicting_signals.append(
                        f"Numeric/benchmark claim '{tok}' lacked grounding in primary source corpus"
                    )
            claim_score = round(verified_count / len(claim_tokens), 2)
        else:
            claim_score = 1.0

        if any(w in title_lower for w in ("alleged", "rumor", "unconfirmed", "leak")):
            conflicting_signals.append("Headline contains unverified rumor indicators")

        # 5. Deterministic Confidence Assignment
        if conflicting_signals and claim_score < 0.50:
            confidence = EvidenceConfidence.CONTRADICTED
            notes = "Unverified claims contradict primary source grounding or represent ungrounded marketing."
        elif primary_source_type == "social_media_discussion" and not has_artifact and corroboration_count == 1:
            confidence = EvidenceConfidence.INSUFFICIENT_EVIDENCE
            notes = "Single-source social media discussion without independent technical artifacts or source code."
        elif is_official and has_artifact and corroboration_count >= 2 and claim_score >= 0.85:
            confidence = EvidenceConfidence.VERIFIED
            notes = "Corroborated across multiple independent sources with verified primary source code/weights and grounded claims."
        elif is_official and claim_score >= 0.70:
            confidence = EvidenceConfidence.SUPPORTED
            notes = "Supported by primary technical source (repository or preprint); pending third-party independent benchmark replication."
        else:
            confidence = EvidenceConfidence.PRELIMINARY
            notes = "Preliminary technical disclosure requiring independent replication or reproducible test-time harness."

        return EvidenceAssessment(
            confidence=confidence,
            primary_source_type=primary_source_type,
            corroboration_count=corroboration_count,
            has_reproducible_artifact=has_artifact,
            claim_verification_score=claim_score,
            notes=notes,
            conflicting_signals=conflicting_signals,
        )

    def determine_recommended_action(
        self,
        entry: Entry,
        evidence: EvidenceAssessment,
        stack_relevance: StackRelevance,
    ) -> tuple[DecisionAction, str]:
        """Determine validated action enum with safety and evidence constraints."""
        cat_val = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )
        title_lower = (entry.title or "").lower()

        # Rule 1: UPGRADE_DEPENDENCY strictly requires identified affected components
        # and security/patch context
        is_patch_or_sec = (
            cat_val == "vulnerabilities"
            or any(kw in title_lower for kw in ("patch", "security update", "cve-", "vulnerability fix", "advisory"))
        )
        if is_patch_or_sec and stack_relevance.affected_components and stack_relevance.impact_level == StackImpactLevel.DIRECT:
            return (
                DecisionAction.UPGRADE_DEPENDENCY,
                f"Critical advisory or patch directly affecting configured stack component(s): {', '.join(stack_relevance.affected_components[:2])}.",
            )

        # Rule 2: Research breakthroughs with supported evidence -> READ_PAPER
        if cat_val == "ai_research" or "arxiv.org" in (entry.url or "").lower():
            if evidence.confidence in (EvidenceConfidence.VERIFIED, EvidenceConfidence.SUPPORTED):
                return (
                    DecisionAction.READ_PAPER,
                    "High-significance foundational research preprint with verified methodology. Study architectural improvements.",
                )

        # Rule 3: Open-source developer tools, runtimes, or models with artifacts -> TEST_IN_SANDBOX
        if evidence.has_reproducible_artifact or cat_val in ("github_trending", "ai_models"):
            if evidence.confidence in (EvidenceConfidence.VERIFIED, EvidenceConfidence.SUPPORTED):
                return (
                    DecisionAction.TEST_IN_SANDBOX,
                    "Verified open-source weights or code available. Benchmark throughput and integration in an isolated sandbox runtime.",
                )

        # Rule 4: Marketing hype / low-signal / no-match items with no technical artifacts -> IGNORE_HYPE
        is_tech_artifact_or_repo = (
            evidence.has_reproducible_artifact
            or cat_val in ("github_trending", "ai_research", "ai_models")
            or any(d in (entry.url or "").lower() for d in ("github.com", "huggingface.co", "arxiv.org"))
        )
        if (
            stack_relevance.impact_level == StackImpactLevel.NO_MATCH
            and not is_patch_or_sec
            and not is_tech_artifact_or_repo
        ):
            return (
                DecisionAction.IGNORE_HYPE,
                "No direct relevance to configured watchlist or production stack; marketing claims unverified.",
            )

        # Rule 5: Preliminary or ungrounded claims -> MONITOR_CLAIMS
        if evidence.confidence in (EvidenceConfidence.PRELIMINARY, EvidenceConfidence.INSUFFICIENT_EVIDENCE, EvidenceConfidence.CONTRADICTED):
            return (
                DecisionAction.MONITOR_CLAIMS,
                "Evidence is preliminary or pending independent verification. Wait for reproducible code, checkpoints, or peer validation.",
            )

        # Default safe action
        return (
            DecisionAction.MONITOR_CLAIMS,
            "Track technical disclosures and monitor ecosystem discussions for reproducible evidence.",
        )

    async def _synthesize_q1_q2_q3(
        self,
        entry: Entry,
        historical_comparisons: list[HistoricalComparison],
        stack_relevance: StackRelevance,
        evidence: EvidenceAssessment,
    ) -> tuple[str, str, NoveltyAssessment]:
        """Synthesize Q1 (What happened?), Q2 (Why it matters?), and Q3 (Novelty nuance) via LLM or deterministic fallback."""
        # Check if local SLM or Frontier LLM can be invoked
        hist_text_blocks = []
        if historical_comparisons:
            for i, h in enumerate(historical_comparisons, 1):
                hist_text_blocks.append(
                    f"[{i}] {h.title} (Published: {h.published_at or 'Unknown'}, Sim: {h.similarity_score}, ID: {h.entry_id})"
                )
            hist_context_str = "\n".join(hist_text_blocks)
            novelty_type_default = NoveltyType.INCREMENTAL_UPDATE if any(h.similarity_score >= 0.70 for h in historical_comparisons) else NoveltyType.GENUINE_NOVELTY
        else:
            hist_context_str = "No prior related entries found in local database (INSUFFICIENT_HISTORY)."
            novelty_type_default = NoveltyType.INSUFFICIENT_HISTORY

        user_prompt = (
            f"Title: {entry.title}\n"
            f"Summary: {entry.summary}\n"
            f"Category: {entry.category.value if hasattr(entry.category, 'value') else str(entry.category)}\n"
            f"Source URL: {entry.url}\n"
            f"Evidence Confidence: {evidence.confidence.value}\n"
            f"Primary Source: {evidence.primary_source_type}\n"
            f"Stack Relevance: {stack_relevance.impact_level.value} (Matched: {', '.join(stack_relevance.matched_technologies) or 'None'})\n\n"
            f"Local Database Historical Comparison Context:\n{hist_context_str}"
        )

        llm_data: dict[str, Any] | None = None
        # Attempt LLM synthesis if available
        try:
            analyzer = LLMAnalyzer(config={"tier": "cloud_frontier"})
            if analyzer.client is not None or not slm_circuit_breaker.is_tripped:
                if analyzer.tier == "cloud_frontier" and hasattr(analyzer, "_call_groq") and analyzer.client is not None:
                    raw_res = await analyzer._call_groq(user_prompt, user_prompt=user_prompt)
                    if isinstance(raw_res, tuple):
                        llm_data = raw_res[0]
                    elif isinstance(raw_res, dict):
                        llm_data = raw_res
                elif not slm_circuit_breaker.is_tripped:
                    llm_data = await analyzer._call_ollama(user_prompt, user_prompt=user_prompt)
        except Exception as e:
            logger.debug(f"Decision brief LLM synthesis bypassed: {e}")

        # Extract or construct Q1, Q2, Q3
        if llm_data and isinstance(llm_data, dict):
            event_summary = str(llm_data.get("event_summary") or "").strip()
            significance = str(llm_data.get("significance") or "").strip()
            novelty_summary = str(llm_data.get("novelty_summary") or "").strip()
            uncertainties = list(llm_data.get("uncertainties") or [])
        else:
            event_summary = ""
            significance = ""
            novelty_summary = ""
            uncertainties = []

        # Heuristic fallbacks if LLM output was empty or unavailable
        if not event_summary:
            event_summary = (
                f"Source reported event: '{entry.title}'. "
                f"{entry.summary or 'Primary technical details published at official source.'}"
            )
        if not significance:
            tech_list = ", ".join(stack_relevance.matched_technologies) or "AI ecosystem infrastructure"
            significance = (
                f"Technical milestone impacting {tech_list}. "
                "Presents practical performance, compute efficiency, or architectural improvements for practitioners."
            )
        if not novelty_summary:
            if novelty_type_default == NoveltyType.INSUFFICIENT_HISTORY:
                novelty_summary = (
                    "New to local intelligence database. Insufficient prior historical records in local memory to establish incremental lineage."
                )
            elif novelty_type_default == NoveltyType.INCREMENTAL_UPDATE:
                comp_titles = [c.title for c in historical_comparisons[:2]]
                novelty_summary = (
                    f"Represents an incremental development building directly upon earlier recorded work: {'; '.join(comp_titles)}."
                )
            else:
                novelty_summary = (
                    "Substantial divergence in architectural approach or capabilities compared to prior records in local database."
                )

        novelty_assessment = NoveltyAssessment(
            novelty_type=novelty_type_default,
            summary=novelty_summary,
            comparison_notes=(
                f"Compared against {len(historical_comparisons)} historical vector records. "
                "Distinguishes local database novelty from broader global industry claims."
            ),
            uncertainties=uncertainties or [
                "Awaiting third-party replication benchmarks and production load measurements."
            ],
        )

        return event_summary, significance, novelty_assessment

    async def _persist_brief(
        self,
        entry: Entry,
        brief: PersonalDecisionBrief,
        uow: SqlAlchemyUnitOfWork | None,
    ) -> None:
        """Persist generated decision brief into analysis record."""
        if uow is None:
            return

        try:
            # Pillar 4: Extract and persist structured AI entities to knowledge graph
            from ai_security_monitor.application.services.ai_entity_extractor import (
                ai_entity_extractor,
            )

            extracted_entities = ai_entity_extractor.extract_entities(entry)
            if extracted_entities and hasattr(uow, "entities"):
                await uow.entities.add_all(extracted_entities)
                entry.entities = extracted_entities

            brief_dict = brief.to_dict()
            existing_analysis = await uow.analysis.get_by_entry(entry.id)
            if existing_analysis:
                existing_analysis.decision_brief = brief_dict
                await uow.analysis.update(existing_analysis)
            else:
                new_analysis = Analysis(
                    entry_id=entry.id,
                    attack_vector=entry.title[:100],
                    risk_assessment=brief.significance[:250],
                    mitigation=brief.action_rationale[:250],
                    threat_velocity=75 if brief.stack_relevance.suggested_priority == "P0" else 50,
                    severity_index=70,
                    blast_radius_score=60,
                    affected_ecosystem=brief.stack_relevance.matched_technologies or ["AI Ecosystem"],
                    attack_archetype="Decision Intelligence",
                    weaponization_potential="Production Ready",
                    decision_brief=brief_dict,
                )
                await uow.analysis.add(new_analysis)
            await uow.commit()
        except Exception as pe:
            logger.debug(f"Failed to persist decision brief to database: {pe}")


# Global singleton instance
decision_brief_service = DecisionBriefService()
