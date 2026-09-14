"""
Multi-Agent Critique & Debate Triage Engine.
Simulates a multi-agent council (Creator/Analyst vs. Critic/Validator)
to scrutinize and score high-velocity AI intelligence before publication.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AgentCritiqueResult:
    creator_score: float
    critic_score: float
    consensus_score: float
    critique_summary: str
    approved: bool


class MultiAgentDebateEngine:
    """Orchestrates multi-perspective autonomous critique for incoming AI intelligence."""

    def __init__(self):
        self.name = "AetherGuard Multi-Agent Council"

    async def debate_and_critique(
        self, title: str, summary: str, category: str
    ) -> AgentCritiqueResult:
        """Run an asynchronous multi-agent evaluation on a piece of intelligence."""
        logger.info(f"Initiating multi-agent debate council for: {title[:60]}...")

        # 1. Analyst Agent (Creator / Impact Evaluation)
        text_lower = (title + " " + summary).lower()
        impact_keywords = (
            "breakthrough",
            "state-of-the-art",
            "release",
            "vulnerability",
            "agent",
            "scaling",
            "reasoning",
            "safety",
        )
        impact_matches = sum(1 for kw in impact_keywords if kw in text_lower)
        creator_score = min(100.0, 50.0 + (impact_matches * 8.0))

        # 2. Critic Agent (Rigor & Novelty Validation)
        hype_words = ("revolutionary", "game-changing", "unprecedented", "miracle")
        hype_count = sum(1 for hw in hype_words if hw in text_lower)
        critic_penalty = hype_count * 12.0
        critic_score = max(20.0, 90.0 - critic_penalty)

        # 3. Consensus Synthesis
        consensus_score = round((creator_score * 0.6) + (critic_score * 0.4), 1)
        approved = consensus_score >= 55.0

        summary_text = (
            f"Council Evaluation: Creator Impact Score {creator_score}/100, "
            f"Critic Rigor Score {critic_score}/100. Consensus: {consensus_score}/100. "
            f"{'Approved for publication and high-priority triage queue.': approved else 'Filtered out as low-signal/hype.'}"
        )

        return AgentCritiqueResult(
            creator_score=creator_score,
            critic_score=critic_score,
            consensus_score=consensus_score,
            critique_summary=summary_text,
            approved=approved,
        )


multi_agent_council = MultiAgentDebateEngine()
