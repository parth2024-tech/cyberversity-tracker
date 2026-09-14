"""
Autonomous Live Intelligence Fetcher for Newspaper Compilation.

Autonomously fetches live cutting-edge AI entries from arXiv, Hugging Face,
AWS Machine Learning Blog, and MarkTechPost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import feedparser
import httpx

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Analysis, Category, Entry
from ai_security_monitor.domain.value_objects import ContentHash

logger = get_logger(__name__)


class NewspaperLiveFetcher:
    """Autonomous Live AI Intelligence Fetcher for the Newspaper engine."""

    async def fetch_live_intelligence(self) -> list[Entry]:
        """Autonomously fetch live cutting-edge AI entries from arXiv, Hugging Face, and leading AI feeds."""
        live_entries: list[Entry] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIResearchBot/3.0"
        }

        async with httpx.AsyncClient(
            timeout=10.0, headers=headers, follow_redirects=True
        ) as client:
            # 1. arXiv cs.AI & cs.LG API
            try:
                r = await client.get(
                    "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=30"
                )
                if r.status_code == 200:
                    feed = feedparser.parse(r.content)
                    for item in feed.entries:
                        t = getattr(item, "title", "").replace("\n", " ").strip()
                        u = getattr(item, "link", "")
                        s = getattr(item, "summary", "").replace("\n", " ").strip()
                        now = datetime.now(UTC)
                        ch = str(ContentHash.from_content(t, u, str(now)))
                        e_id = uuid4()
                        live_entries.append(
                            Entry(
                                id=e_id,
                                source_id=uuid4(),
                                title=t,
                                url=u,
                                summary=s,
                                content_hash=ch,
                                category=Category.AI_RESEARCH,
                                published_at=now,
                                tags=["arxiv", "research", "cs.AI"],
                                analysis=Analysis(
                                    id=uuid4(),
                                    entry_id=e_id,
                                    attack_vector="Algorithmic Architecture",
                                    risk_assessment="Empirical research milestone",
                                    mitigation="Evaluate theoretical bounds and experimental architecture",
                                    threat_velocity=88,
                                    severity_index=84,
                                ),
                                metadata={"source_name": "arXiv.org"},
                            )
                        )
            except Exception as ex:
                logger.warning(f"Live arXiv fetch failed: {ex}")

            # 2. Hugging Face Trending Foundation Models
            try:
                r = await client.get(
                    "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=30"
                )
                if r.status_code == 200:
                    for m in r.json():
                        m_id = m.get("id", "")
                        likes = m.get("likes", 0)
                        now = datetime.now(UTC)
                        t = f"Trending Foundation Model: {m_id}"
                        u = f"https://huggingface.co/{m_id}"
                        s = f"{m_id} is trending across the global Hugging Face open-source ecosystem with {likes} developer likes."
                        ch = str(ContentHash.from_content(t, u, str(now)))
                        e_id = uuid4()
                        live_entries.append(
                            Entry(
                                id=e_id,
                                source_id=uuid4(),
                                title=t,
                                url=u,
                                summary=s,
                                content_hash=ch,
                                category=Category.AI_MODELS,
                                published_at=now,
                                tags=["huggingface", "weights", "open-source"],
                                analysis=Analysis(
                                    id=uuid4(),
                                    entry_id=e_id,
                                    attack_vector="Open-Weights Checkpoint",
                                    risk_assessment="High velocity developer adoption",
                                    mitigation="Benchmark in production vLLM and SGLang clusters",
                                    threat_velocity=92,
                                    severity_index=88,
                                ),
                                metadata={"source_name": "huggingface.co"},
                            )
                        )
            except Exception as ex:
                logger.warning(f"Live Hugging Face fetch failed: {ex}")

            # 3. AWS Machine Learning Blog RSS
            try:
                r = await client.get(
                    "https://aws.amazon.com/blogs/machine-learning/feed/"
                )
                if r.status_code == 200:
                    feed = feedparser.parse(r.content)
                    for item in feed.entries[:15]:
                        t = getattr(item, "title", "").strip()
                        u = getattr(item, "link", "")
                        s = getattr(item, "summary", "").strip()
                        now = datetime.now(UTC)
                        ch = str(ContentHash.from_content(t, u, str(now)))
                        e_id = uuid4()
                        live_entries.append(
                            Entry(
                                id=e_id,
                                source_id=uuid4(),
                                title=t,
                                url=u,
                                summary=s,
                                content_hash=ch,
                                category=Category.AI_TECH,
                                published_at=now,
                                tags=["aws", "infrastructure", "enterprise-ai"],
                                analysis=Analysis(
                                    id=uuid4(),
                                    entry_id=e_id,
                                    attack_vector="Cloud AI Infrastructure",
                                    risk_assessment="Hyperscale deployment patterns",
                                    mitigation="Optimize serving topology and GPU cluster allocation",
                                    threat_velocity=84,
                                    severity_index=80,
                                ),
                                metadata={"source_name": "aws.amazon.com"},
                            )
                        )
            except Exception as ex:
                logger.warning(f"Live AWS ML fetch failed: {ex}")

            # 4. MarkTechPost AI Engineering News RSS
            try:
                r = await client.get("https://www.marktechpost.com/feed/")
                if r.status_code == 200:
                    feed = feedparser.parse(r.content)
                    for item in feed.entries[:15]:
                        t = getattr(item, "title", "").strip()
                        u = getattr(item, "link", "")
                        s = getattr(item, "summary", "").strip()
                        now = datetime.now(UTC)
                        ch = str(ContentHash.from_content(t, u, str(now)))
                        e_id = uuid4()
                        live_entries.append(
                            Entry(
                                id=e_id,
                                source_id=uuid4(),
                                title=t,
                                url=u,
                                summary=s,
                                content_hash=ch,
                                category=Category.CYBER_TOOLS,
                                published_at=now,
                                tags=["engineering", "frameworks", "marktechpost"],
                                analysis=Analysis(
                                    id=uuid4(),
                                    entry_id=e_id,
                                    attack_vector="AI Software Framework",
                                    risk_assessment="Developer tooling capability",
                                    mitigation="Integrate into automated evaluation pipelines",
                                    threat_velocity=86,
                                    severity_index=82,
                                ),
                                metadata={"source_name": "marktechpost.com"},
                            )
                        )
            except Exception as ex:
                logger.warning(f"Live MarkTechPost fetch failed: {ex}")

        logger.info(
            f"Live AI intelligence sweep yielded {len(live_entries)} authoritative stories."
        )
        return live_entries
