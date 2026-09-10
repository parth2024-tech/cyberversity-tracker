"""
Autonomous 10-Page Comprehensive Intelligence Broadsheet Service ("The Cyber Intelligence Chronicle").
Compiles live security intelligence into authentic, publication-grade 10-page editorial dossiers (PDF, HTML, and Markdown).
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import feedparser
import httpx
from uuid import uuid4

from ai_security_monitor.application.services.article_extractor import article_extractor
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
)
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/newspapers")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for total page count, running headers, and security imprimaturs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 7)
        self.setFillColor(colors.HexColor("#475569"))

        # Running Header on pages > 1
        if self._pageNumber > 1:
            self.drawString(36, 756, "THE GLOBAL AI GAZETTE — WORLDWIDE AI ECOSYSTEM • 10-PAGE INTELLIGENCE DOSSIER")
            self.drawRightString(576, 756, f"PAGE {self._pageNumber} OF {page_count}")
            self.setStrokeColor(colors.HexColor("#94a3b8"))
            self.setLineWidth(0.75)
            self.line(36, 750, 576, 750)

        # Running Footer on all pages
        self.setStrokeColor(colors.HexColor("#94a3b8"))
        self.setLineWidth(0.75)
        self.line(36, 32, 576, 32)
        self.setFont("Helvetica", 7)
        self.drawString(36, 22, "THE GLOBAL AI GAZETTE • WORLDWIDE AI ECOSYSTEM INTELLIGENCE • ALL RIGHTS RESERVED")
        self.drawRightString(576, 22, f"PAGE {self._pageNumber} OF {page_count}")
        self.restoreState()


COUNTRY_FLAGS: dict[str, str] = {
    "US": "🇺🇸", "CN": "🇨🇳", "HK": "🇭🇰", "IN": "🇮🇳", "IL": "🇮🇱",
    "JP": "🇯🇵", "KR": "🇰🇷", "GB": "🇬🇧", "EU": "🇪🇺", "SG": "🇸🇬",
    "TW": "🇹🇼", "AE": "🇦🇪", "CA": "🇨🇦", "DE": "🇩🇪", "FR": "🇫🇷",
    "NL": "🇳🇱", "FI": "🇫🇮", "SE": "🇸🇪", "CH": "🇨🇭", "AU": "🇦🇺",
}


class NewspaperService:
    """Autonomous 10-Page Intelligence Broadsheet Compiler."""

    def __init__(
        self,
        uow_factory: type[SqlAlchemyUnitOfWork] | None = None,
        output_dir: Path | None = None,
    ):
        self._uow_factory = uow_factory or SqlAlchemyUnitOfWork
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _compute_edition_number(self, dt: datetime) -> int:
        """Compute epoch-based sequential edition number."""
        epoch = datetime(2026, 1, 1, tzinfo=UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        hours = int((dt - epoch).total_seconds() // 3600)
        return 1000 + (hours // 5)

    async def _fetch_live_ai_intelligence(self) -> list[Entry]:
        """Autonomously fetch live cutting-edge AI entries from arXiv, Hugging Face, and leading AI feeds."""
        live_entries: list[Entry] = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIResearchBot/3.0"}

        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
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
                        live_entries.append(Entry(
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
                            metadata={"source_name": "arXiv.org"}
                        ))
            except Exception as ex:
                logger.warning(f"Live arXiv fetch failed: {ex}")

            # 2. Hugging Face Trending Foundation Models
            try:
                r = await client.get("https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=30")
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
                        live_entries.append(Entry(
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
                            metadata={"source_name": "huggingface.co"}
                        ))
            except Exception as ex:
                logger.warning(f"Live Hugging Face fetch failed: {ex}")

            # 3. AWS Machine Learning Blog RSS
            try:
                r = await client.get("https://aws.amazon.com/blogs/machine-learning/feed/")
                if r.status_code == 200:
                    feed = feedparser.parse(r.content)
                    for item in feed.entries[:15]:
                        t = getattr(item, "title", "").strip()
                        u = getattr(item, "link", "")
                        s = getattr(item, "summary", "").strip()
                        now = datetime.now(UTC)
                        ch = str(ContentHash.from_content(t, u, str(now)))
                        e_id = uuid4()
                        live_entries.append(Entry(
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
                            metadata={"source_name": "aws.amazon.com"}
                        ))
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
                        live_entries.append(Entry(
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
                            metadata={"source_name": "marktechpost.com"}
                        ))
            except Exception as ex:
                logger.warning(f"Live MarkTechPost fetch failed: {ex}")

        logger.info(f"Live AI intelligence sweep yielded {len(live_entries)} authoritative stories.")
        return live_entries

    async def generate_edition(self, window_hours: int = 24) -> dict[str, Any]:
        """Compile an authentic, 100% AI-focused 10-page intelligence broadsheet dossier."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=max(24, window_hours))
        logger.info(f"Initiating 10-page AI intelligence newspaper compilation (window={window_hours}h)...")

        def is_security_item(e: Entry) -> bool:
            cat_val = e.category.value if hasattr(e.category, "value") else str(e.category)
            if cat_val in ("vulnerabilities", "exploits_tricks", "cybersecurity"):
                return True
            combined = f"{(e.title or '').lower()} {(e.summary or '').lower()}"
            sec_patterns = (
                r"\b(?:cve|cve-\d{4}-\d+|rce|zero-day|0-day|0day|buffer overflow|remote code execution)\b",
                r"\b(?:privilege escalation|authentication bypass|rootkit|backdoor|malware|ransomware|cisa kev)\b",
                r"\b(?:exploit-db|packet storm|vulnerability|vulnerabilities|exploit|exploits)\b",
                r"\b(?:security patch|patch release|monthly patch|patched \d+|fixed \d+ vulnerabilities)\b",
                r"\b(?:cyberattack|cyber attack|infosec|cybersecurity|data breach|threat actor|hacked by|shai-hulud)\b",
                r"\b(?:poisoning intelligence alert|emergency ai security intelligence|supply chain attack)\b",
            )
            return any(re.search(pat, combined) for pat in sec_patterns)

        def calculate_content_quality(e: Entry) -> bool:
            title = (e.title or "").strip()
            words = title.split()
            t_lower = title.lower()

            # Allow short titles if they are clearly a model/repo release
            is_technical_id = bool(re.search(r"[\w\-]+/[\w\-]+|\b(?:qwen|deepseek|llama|mistral|gpt|claude|gemini|vllm|ollama|sglang|gguf)\b", t_lower))
            if len(words) < 3 and not is_technical_id:
                return False

            reject_patterns = [
                r"(?i)\b(?:custom loop|fan curve|cable management|thermal paste|my setup|rebuild to custom loop|temps on the gpus)\b",
                r"(?i)\b(?:so relevant|anyone else notice|is anyone else|am i the only one|help needed|need advice|thoughts\b|is it just me|what do you think)\b",
                r"(?i)^(?:til\b|so relevant\b|interesting\b|thoughts\b|question\b|help\b|update:)",
            ]
            for pat in reject_patterns:
                if re.search(pat, t_lower):
                    return False
            return True

        async with self._uow_factory() as uow:
            # Query comprehensive recent entries from the AI monitoring horizon
            recent_filters = EntryFilters(since=cutoff, sort_by="velocity")
            raw_entries = await uow.entries.list(
                filters=recent_filters,
                pagination=PaginationParams(limit=400, offset=0),
            )

            existing_ids = {e.id for e in raw_entries}
            # Pure Worldwide AI Pillars: Trending Repos, Models, Research, Infrastructure, and Tech
            core_pillars = [
                Category.AI_MODELS,
                Category.AI_RESEARCH,
                Category.GITHUB_TRENDING,
                Category.AI_TECH,
                Category.CYBER_TOOLS,
            ]
            for pillar_cat in core_pillars:
                cat_filters = EntryFilters(category=pillar_cat, sort_by="velocity")
                cat_items = await uow.entries.list(
                    filters=cat_filters,
                    pagination=PaginationParams(limit=35, offset=0),
                )
                for item in cat_items:
                    if item.id not in existing_ids:
                        raw_entries.append(item)
                        existing_ids.add(item.id)

            def is_ai_relevant(e: Entry) -> bool:
                cat_val = e.category.value if hasattr(e.category, "value") else str(e.category)
                if cat_val in ("ai_models", "ai_research", "github_trending", "cyber_tools"):
                    return True
                combined = f"{(e.title or '').lower()} {(e.summary or '').lower()}"
                ai_keywords = (
                    "ai", "artificial intelligence", "llm", "model", "neural", "deep learning", "machine learning",
                    "gpu", "tpu", "agent", "agentic", "transformer", "reasoning", "dataset", "inference",
                    "quantization", "gguf", "algorithm", "compute", "silicon", "semiconductor", "chip", "chips",
                    "robot", "robotics", "vision", "multimodal", "prompt", "token", "weights", "fine-tune",
                    "embedding", "vector", "rag", "eval", "framework", "runtime", "huggingface", "openai",
                    "anthropic", "meta ai", "deepseek", "qwen", "mistral", "google ai", "gemini", "claude", "llama",
                    "data center", "datacenter", "open-source", "open source"
                )
                return any(re.search(rf"\b{re.escape(k)}\b", combined) for k in ai_keywords)

            # Strict AI isolation: purge all CVE/vulnerability/exploit entries and non-AI general news
            entries = [e for e in raw_entries if not is_security_item(e) and is_ai_relevant(e) and calculate_content_quality(e)]

            # Rich backfill if overall volume is sparse — query purely AI-focused historical records
            if len(entries) < 100:
                logger.info("Backfilling historical AI intelligence to assemble comprehensive 10-page dossier.")
                for pillar_cat in (Category.AI_MODELS, Category.AI_RESEARCH, Category.GITHUB_TRENDING, Category.AI_TECH):
                    fallback_filters = EntryFilters(category=pillar_cat, sort_by="velocity")
                    fallback_items = await uow.entries.list(
                        filters=fallback_filters,
                        pagination=PaginationParams(limit=60, offset=0),
                    )
                    for item in fallback_items:
                        if item.id not in existing_ids and not is_security_item(item) and is_ai_relevant(item) and calculate_content_quality(item):
                            entries.append(item)
                            existing_ids.add(item.id)

        # Autonomous Live Extraction Fallback: If database yielded fewer than 45 verified AI stories,
        # immediately execute a live sweep across arXiv, Hugging Face, and leading AI feeds.
        if len(entries) < 45:
            logger.info(f"Database contains only {len(entries)} stories; executing autonomous live AI intelligence sweep...")
            try:
                live_items = await self._fetch_live_ai_intelligence()
                for item in live_items:
                    if item.id not in existing_ids and not is_security_item(item) and is_ai_relevant(item):
                        entries.append(item)
                        existing_ids.add(item.id)
                logger.info(f"Total stories after live sweep: {len(entries)}")
            except Exception as live_err:
                logger.warning(f"Live AI intelligence sweep error: {live_err}")

        edition_num = self._compute_edition_number(now)
        timestamp_str = now.strftime("%Y%m%d_%H%M")
        edition_id = f"chronicle_{timestamp_str}"

        # Segment entries across all 10 specialized intelligence domains with deep extraction
        categorized = await self._categorize_entries(entries)

        # Generate Markdown Document
        markdown_content = self._render_markdown(
            entries=entries,
            categorized=categorized,
            edition_num=edition_num,
            generated_at=now,
            window_hours=window_hours,
        )

        # Generate HTML Newspaper Document
        html_content = self._render_html(
            entries=entries,
            categorized=categorized,
            edition_num=edition_num,
            generated_at=now,
            window_hours=window_hours,
            edition_id=edition_id,
        )

        # Persist files to disk
        md_file = self._output_dir / f"{edition_id}.md"
        html_file = self._output_dir / f"{edition_id}.html"
        pdf_file = self._output_dir / f"{edition_id}.pdf"
        latest_md = self._output_dir / "latest.md"
        latest_html = self._output_dir / "latest.html"
        latest_pdf = self._output_dir / "latest.pdf"
        meta_file = self._output_dir / f"{edition_id}.json"
        latest_meta = self._output_dir / "latest.json"

        md_file.write_text(markdown_content, encoding="utf-8")
        html_file.write_text(html_content, encoding="utf-8")
        latest_md.write_text(markdown_content, encoding="utf-8")
        latest_html.write_text(html_content, encoding="utf-8")

        # Generate 10-Page PDF Document
        try:
            self._render_pdf(
                pdf_path=pdf_file,
                entries=entries,
                categorized=categorized,
                edition_num=edition_num,
                generated_at=now,
                window_hours=window_hours,
            )
            shutil.copyfile(pdf_file, latest_pdf)
            has_pdf = True
        except Exception as pdf_err:
            logger.error(f"Failed to generate 10-page newspaper PDF: {pdf_err}")
            has_pdf = False

        metadata = {
            "edition_id": edition_id,
            "edition_number": edition_num,
            "title": f"The Global AI Gazette — 10-Page Edition #{edition_num}",
            "generated_at": now.isoformat(),
            "window_hours": window_hours,
            "total_stories": len(entries),
            "total_threats": len(entries),
            "pages_count": 10,
            "lead_story": categorized["lead"].title if categorized["lead"] else "Global AI Intelligence Report",
            "trending_repos_count": len(categorized.get("trending_repos", [])),
            "ai_models_count": len(categorized.get("ai_models", [])),
            "ai_research_count": len(categorized.get("ai_research", [])),
            "ai_tools_count": len(categorized.get("ai_tools", [])),
            "sovereign_ai_count": len(categorized.get("sovereign_ai", [])),
            "ai_hardware_count": len(categorized.get("ai_hardware", [])),
            "autonomous_agents_count": len(categorized.get("autonomous_agents", [])),
            "overflow_count": len(categorized.get("overflow", [])),
            "md_path": str(md_file),
            "html_path": str(html_file),
            "pdf_path": str(pdf_file) if has_pdf else None,
            "has_pdf": has_pdf,
        }

        meta_json = json.dumps(metadata, indent=2)
        meta_file.write_text(meta_json, encoding="utf-8")
        latest_meta.write_text(meta_json, encoding="utf-8")

        logger.info(
            f"Successfully published 10-Page Newspaper Edition #{edition_num} "
            f"({len(entries)} stories compiled into {md_file.name} & {pdf_file.name})"
        )
        return metadata

    def get_latest_edition(self) -> dict[str, Any] | None:
        """Retrieve metadata and content of latest newspaper edition."""
        latest_meta_file = self._output_dir / "latest.json"
        latest_md_file = self._output_dir / "latest.md"
        latest_html_file = self._output_dir / "latest.html"

        if not latest_meta_file.exists() or not latest_md_file.exists():
            return None

        try:
            meta = json.loads(latest_meta_file.read_text(encoding="utf-8"))
            meta["markdown"] = latest_md_file.read_text(encoding="utf-8")
            meta["has_html"] = latest_html_file.exists()
            return meta
        except Exception as e:
            logger.warning(f"Error reading latest newspaper edition: {e}")
            return None

    def get_latest_html(self) -> str | None:
        """Retrieve formatted HTML document."""
        latest_html_file = self._output_dir / "latest.html"
        if latest_html_file.exists():
            return latest_html_file.read_text(encoding="utf-8")
        return None

    def get_latest_pdf_path(self) -> Path | None:
        """Retrieve path to latest PDF document."""
        latest_pdf_file = self._output_dir / "latest.pdf"
        if latest_pdf_file.exists():
            return latest_pdf_file
        return None

    def list_editions(self, limit: int = 15) -> list[dict[str, Any]]:
        """List historical editions."""
        editions = []
        for meta_file in sorted(self._output_dir.glob("chronicle_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                editions.append(data)
            except Exception:
                continue
        return editions

    def extract_technical_specs(self, title: str, summary: str = "") -> dict[str, str]:
        """Extract concrete architecture parameters, context size, and throughput metrics."""
        text = f"{title} {summary}"
        size_match = re.search(r"\b(\d+B|\d+x\d+B|\d+\.\d+B|MoE)\b", text, re.I)
        size = size_match.group(1).upper() if size_match else "MoE / SOTA"

        ctx_match = re.search(r"\b(\d+[kK]|\d+[mM]|\d+\s*context)\b", text)
        ctx = ctx_match.group(1).upper() if ctx_match else "128K"

        quant_match = re.search(r"\b(GGUF|AWQ|EXL2|FP8|FP4|INT4|INT8|UD-[A-Z0-9_]+)\b", text, re.I)
        quant = quant_match.group(1).upper() if quant_match else "Native / FP16"

        engine_match = re.search(r"\b(vLLM|SGLang|llama\.cpp|Ollama|MLX|MLX-serve|TensorRT-LLM|CUDA|PyTorch)\b", text, re.I)
        engine = engine_match.group(1) if engine_match else "PyTorch / ONNX"

        thru_match = re.search(r"\b(\d+(?:\.\d+)?\s*(?:tok/s|t/s|tokens per second|GB/s))\b", text, re.I)
        thru = thru_match.group(1) if thru_match else "High Velocity"

        lang_match = re.search(r"\b(Python|Rust|C\+\+|TypeScript|Go|CUDA)\b", text, re.I)
        lang = lang_match.group(1) if lang_match else "Python"

        return {
            "size": size,
            "ctx": ctx,
            "quant": quant,
            "engine": engine,
            "thru": thru,
            "lang": lang,
        }

    # ─── Editorial Parsing & Classification ──────────────────────────────────

    def _clean_title(self, title: str | None) -> str:
        """Clean titles by stripping redundant tags, author prefixes, forum labels, and unescaping HTML."""
        if not title:
            return "Intelligence Dispatch"
        t = html.unescape(title).strip()
        # Strip prefixes and tags
        t = re.sub(r"^(?:Trending|Release|Tool|Update|RFC|Paper|PSA)\s*:\s*", "", t, flags=re.I)
        t = re.sub(r"^\[(?:D|R|P|News|Project|Discussion|Research|webapps|remote)\]\s*", "", t, flags=re.I)
        t = re.sub(r"^Security Tool\s*/\s*PoC:\s*", "", t, flags=re.I)
        t = re.sub(r"^Security Tool:\s*", "", t, flags=re.I)
        t = re.sub(r"^PoC:\s*", "", t, flags=re.I)
        # Strip LaTeX math artifacts often found in arXiv titles
        t = re.sub(r"\$(.*?)\$", r"\1", t)
        t = re.sub(r"\\(?:mathcal|mathbb|mathbf|text|mathrm)\{([^}]+)\}", r"\1", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _clean_and_format_summary(
        self,
        raw_text: str | None,
        entry: Entry | None = None,
        min_words: int = 20,
        max_words: int = 150,
    ) -> str:
        """Sanitize raw text, eliminate mid-word truncations, strip Reddit boilerplate, and format cleanly."""
        if not raw_text or len(raw_text.split()) < 6:
            if entry:
                return article_extractor.synthesize_technical_analysis(entry)
            return "Active advancement and technical progress tracked across global AI monitoring arrays."

        # 1. Multi-pass unescape HTML and remove tags
        text = raw_text
        for _ in range(2):
            text = html.unescape(text)
        text = re.sub(r"<[^<]+?>", " ", text)
        text = re.sub(r"&#\d+;", " ", text)

        # 2. Strip Reddit and RSS scrape junk
        text = re.sub(r"(?i)\b(?:submitted by|posted by)\b.*?(?:\[comments\]|\[link\]|$)", " ", text)
        text = re.sub(r"(?i)\[(?:link|comments)\]", " ", text)
        text = re.sub(r"(?i)/u/\S+", " ", text)
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"\(http[^\)]+\)", " ", text)
        text = re.sub(r"\b(?:here|at|see|check|demo|demo here)\s*:\s*(?=[A-Z])", " ", text, flags=re.I)

        # 3. Clean WeChat / sovereign news header clutter
        text = re.sub(r"^[A-Za-z\s]+ \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Za-z\s]+", "", text)
        text = re.sub(r"^Original Leading the Digital Supply Chain.*?\bBeijing\b", "", text, flags=re.I)

        # 4. Clean conversational forum slang and first-person informalities
        text = re.sub(r"(?i)\b(?:lol|lmao|rofl|imho|tbh|fyi|btw|y'all|hey guys)\b", "", text)
        text = re.sub(r"(?i)\b(?:i know lol|part 1 was|part 2 was|part 3 was|part 4 of the same box)\b", "", text)
        text = re.sub(r"(?i)\b(?:upvote|downvote|karma|tldr|tl;dr)\b", "", text)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        words = text.split()
        # Fall back to deep technical synthesis if summary is too brief or contains repetitive canned boilerplate
        if (len(words) < min_words or article_extractor._is_generic_canned(text)) and entry:
            return article_extractor.synthesize_technical_analysis(entry)
        if len(words) < 8:
            if entry:
                return article_extractor.synthesize_technical_analysis(entry)
            return text + ("." if not text.endswith((".", "!", "?")) else "")

        # Truncate at sentence boundary within max_words
        if len(words) > max_words:
            truncated_words = words[:max_words]
            candidate_text = " ".join(truncated_words)
            match = re.search(r"^(.*[\.\!\?])(?:\s+[^\.\!\?]*)$", candidate_text)
            if match and len(match.group(1).split()) >= 15:
                text = match.group(1).strip()
            else:
                text = " ".join(truncated_words).rstrip(" ,;:-—") + "."
        else:
            if not text.endswith((".", "!", "?", '"', "'")):
                match = re.search(r"^(.*[\.\!\?])(?:\s+[^\.\!\?]*)$", text)
                if match and len(match.group(1).split()) >= 12:
                    text = match.group(1).strip()
                else:
                    text = re.sub(r"\s+[\w\-]{1,5}$", "", text).rstrip(" ,;:-—") + "."

        return text

    def _generate_executive_directive(self, entry: Entry | None, vector: str | None = None) -> str:
        """Synthesize tailored, context-specific executive directives for AI ecosystem categories."""
        if not entry:
            return "Review the latest AI developments and evaluate strategic alignment with organizational automation priorities."

        t = entry.title or ""
        t_clean = self._clean_title(t)
        match = re.search(r"\b(DeepSeek|Qwen|Llama|Mistral|OpenAI|Anthropic|Claude|Gemini|vLLM|Ollama|SGLang|Nvidia|TSMC|Apple|Meta|Google|Microsoft|Blackwell|Groq|Cerebras|Krutrim|Falcon)\b", t, re.I)
        subj = match.group(1) if match else t_clean[:28]

        vector_map = {
            "Model Sourcing & Licensing": f"Audit open-weights licensing vs proprietary APIs; evaluate {subj} parameter efficiency and commercial distribution terms.",
            "Compute & Infrastructure CapEx": f"Review GPU cluster allocation and power envelopes; benchmark {subj} hardware efficiency to optimize cost per token.",
            "Agentic Autonomy & Governance": f"Implement deterministic sandboxes for {subj} autonomous tool execution, strict rate limiting, and human-in-the-loop validation.",
            "Inference Latency & Quantization": f"Benchmark KV-cache compression (FP8/INT4/GGUF) and modern inference engines for {subj} against TTFT SLAs.",
            "Open-Source Supply Chain": f"Inspect upstream repository dependencies; audit tokenizer code, weights provenance, and pinned runtime releases for {subj}.",
            "Data Residency & Sovereignty": f"Verify compliance with sovereign AI frameworks and regional data residency requirements for {subj} deployments.",
        }
        if vector and vector in vector_map:
            return vector_map[vector]

        cat = entry.category.value if hasattr(entry.category, "value") else str(entry.category)
        title_l = t.lower()

        # AI Hardware & Compute
        if any(k in title_l for k in ("nvidia", "gpu", "tpu", "blackwell", "h100", "b200", "amd", "rocm", "cerebras", "groq", "silicon", "semiconductor", "tsmc", "asml", "datacenter", "hbm")):
            return f"Review infrastructure compute quotas with cloud providers; assess {subj} hardware efficiency benchmarks to reduce inference cost per token."
        # Autonomous Agents & Robotics
        elif any(k in title_l for k in ("agent", "swarm", "robot", "robotics", "embodied", "computer-use", "browser-use", "action model", "autogen", "crewai", "langgraph", "tool use", "mcp")):
            return f"Pilot {subj} agentic capabilities in sandboxed environments; enforce strict tool-execution schemas, rate limits, and human-in-the-loop validation."
        # Foundation Models
        elif cat == "ai_models" or any(k in title_l for k in ("model", "deepseek", "qwen", "llama", "claude", "gpt", "gemini", "mistral", "grok", "weights", "gguf")):
            return f"Benchmark {subj} model against current production baselines; evaluate token economics, quantization tradeoffs, and commercial license terms."
        # Trending GitHub repos
        elif cat == "github_trending" or "github" in (entry.url or ""):
            return f"Assess {subj} repository architecture and licensing (Apache/MIT); test deployment in an isolated staging environment before production integration."
        # AI Research & ArXiv
        elif cat == "ai_research" or "arxiv" in (entry.url or "") or "paper" in title_l:
            return f"Review research findings for {subj}; schedule ML engineering briefing to evaluate test-time compute scaling and algorithmic applicability."
        # Developer Tools & Inference Frameworks
        elif cat == "cyber_tools" or any(k in title_l for k in ("framework", "runtime", "sdk", "library", "tool", "engine", "inference", "rag", "vector", "vllm", "ollama", "sglang")):
            return f"Deploy {subj} runtime in a proof-of-concept environment; evaluate throughput gains, KV-cache memory efficiency, and API compatibility."
        # Sovereign AI
        elif any(k in title_l for k in ("sovereign", "national", "falcon", "kyutai", "tsmc", "france", "india", "japan", "germany", "china")):
            return f"Monitor regional sovereign AI regulatory frameworks and data residency requirements for {subj} deployment."
        # General AI Tech
        else:
            return f"Evaluate {subj} intelligence dispatch; assess technological impact and relevance to your organizational AI adoption roadmap."

    def _get_country_flag(self, country_code: str | None) -> str:
        """Get national flag emoji for ISO country code."""
        if not country_code:
            return "🌐"
        return COUNTRY_FLAGS.get(country_code.upper(), "🌐")

    def _get_curated_fallback_entries(self, category_type: str) -> list[Entry]:
        """Return empty list — backfill is handled dynamically from live pool entries."""
        return []

    def _get_source_name(self, entry: Entry | None) -> str:
        if not entry:
            return "Global Radar"
        if entry.metadata and "source_name" in entry.metadata:
            return str(entry.metadata["source_name"])
        if entry.url:
            try:
                from urllib.parse import urlparse
                host = urlparse(entry.url).netloc.replace("www.", "")
                if host:
                    return host
            except Exception:
                pass
        return "Global Radar"

    async def _categorize_entries(self, raw_entries: list[Entry]) -> dict[str, Any]:
        """Classify entries into 10 distinct AI ecosystem editorial sections with translation & deep extraction."""
        if not raw_entries:
            return {
                "lead": None,
                "secondary_anchor": None,
                "front_page_briefs": [],
                "ciso_briefs": [],
                "trending_repos": [],
                "ai_models": [],
                "ai_research": [],
                "ai_tools": [],
                "sovereign_ai": [],
                "ai_hardware": [],
                "autonomous_agents": [],
                "overflow": [],
            }

        # 1. De-duplicate
        seen_titles = set()
        filtered_entries = []
        for e in raw_entries:
            t_clean = (e.title or "").strip().lower()
            if not t_clean or t_clean in seen_titles:
                continue
            seen_titles.add(t_clean)
            filtered_entries.append(e)
        if len(filtered_entries) < 15:
            filtered_entries = raw_entries

        # 2. Auto-translate foreign language entries
        from ai_security_monitor.application.services.translation_service import (
            translation_service,
        )
        for e in filtered_entries:
            # Only trigger translation if genuine non-ASCII text is present
            if re.search(r"[^\x00-\x7F]", (e.title or "") + " " + (e.summary or "")):
                try:
                    await translation_service.translate_entry_async(e)
                except Exception:
                    pass

        def priority_score(e: Entry) -> int:
            score = 0
            t_lower = (e.title or "").lower()
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            if e.analysis:
                score += e.analysis.threat_velocity * 2
                score += e.analysis.severity_index
            if cat in ("ai_models", "github_trending", "ai_research", "cyber_tools"):
                score += 260
            if any(k in t_lower for k in ("deepseek", "openai", "anthropic", "qwen", "gemini", "claude", "vllm", "ollama", "llama", "reasoning", "breakthrough", "sota", "release", "launch", "open-source", "open source", "arxiv", "paper", "agent", "hardware", "nvidia", "chip")):
                score += 200
            return score

        sorted_entries = sorted(filtered_entries, key=priority_score, reverse=True)
        lead = sorted_entries[0] if sorted_entries else None
        secondary_anchor = sorted_entries[1] if len(sorted_entries) > 1 else None
        remaining = sorted_entries[2:] if len(sorted_entries) > 2 else []

        front_page_briefs = []
        ciso_briefs = []
        trending_repos = []
        ai_models_list = []
        ai_research_list = []
        ai_tools_list = []
        sovereign_ai = []
        ai_hardware = []
        autonomous_agents = []

        for e in remaining:
            region = (e.metadata.get("region") if e.metadata else "") or ""
            country = (e.metadata.get("country") if e.metadata else "") or ""
            t_lower = (e.title or "").lower()
            s_lower = (e.summary or "").lower()
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            tags_lower = [t.lower() for t in (e.tags or [])]

            is_hardware = any(k in t_lower or k in s_lower for k in (
                "nvidia", "gpu", "gpus", "cuda", "tpu", "blackwell", "h100", "b200", "h200", "amd", "rocm",
                "cerebras", "groq", "silicon", "semiconductor", "tsmc", "asml", "tensor core", "hardware",
                "datacenter", "data center", "hbm", "vram", "rtx 4090", "rtx 3090", "apple silicon", "m4", "m5",
                "npu", "chip", "chips", "wafer", "accelerator", "inference chip", "fp8", "fp4"
            ))

            is_agent_robotics = any(k in t_lower or k in s_lower for k in (
                "agent", "agents", "agentic", "swarm", "swarms", "robot", "robotics", "embodied",
                "humanoid", "computer-use", "computer use", "browser-use", "browser use", "action model",
                "autogen", "crewai", "langgraph", "tool use", "tool calling", "mcp", "multi-agent",
                "vision-language-action", "vla", "autonomous workflow", "operator"
            ))

            is_sovereign = (
                region in ("china", "south_asia", "middle_east", "nordic", "europe", "east_asia")
                or country in ("CN", "HK", "IN", "IL", "JP", "KR", "TW", "AE", "SG", "DE", "FR", "NL", "FI", "SE", "CH", "CA", "AU", "GB", "EU")
                or any(k in t_lower or k in s_lower for k in (
                    "deepseek", "qwen", "falcon", "mistral", "kyutai", "glm", "baichuan", "internlm",
                    "tii", "sarvam", "krutrim", "sovereign", "national ai", "alicloud", "alibaba",
                    "tsmc", "asml", "dfki", "inria", "kaist", "riken", "turing institute", "iisc"
                ))
            )

            is_research = (
                cat == "ai_research"
                or "arxiv" in (e.url or "").lower()
                or "arxiv" in t_lower
                or any(k in t_lower for k in ("paper", "preprint", "benchmark", "empirical", "formalizing", "scaling law", "test-time compute", "alignment", "reasoning architecture", "survey"))
            )

            is_model = (
                cat == "ai_models"
                or any(k in t_lower for k in ("foundation model", "deepseek", "qwen", "llama", "mistral", "claude", "gpt", "gemini", "weights", "gguf", "moe", "mixture-of-experts", "reasoning model", "distill", "fine-tune", "70b", "8b", "7b", "32b", "671b"))
            )

            is_tool = (
                cat == "cyber_tools"
                or any(k in t_lower for k in (
                    "vllm", "ollama", "sglang", "llama.cpp", "tensorrt", "litellm", "unsloth", "axolotl",
                    "deepspeed", "transformers", "diffusers", "torchtune", "outlines", "instructor",
                    "langchain", "llamaindex", "chromadb", "qdrant", "weaviate", "milvus", "eval harness",
                    "runtime", "framework", "library", "sdk", "toolkit", "serving engine", "rag pipeline",
                    "vector database", "quantization", "mlx", "mlx-serve", "open-webui", "localai"
                ))
            )

            is_trending = (
                cat == "github_trending"
                or "github.com" in (e.url or "").lower()
                or "github" in tags_lower
                or "trending repo" in t_lower
            )

            # Route into distinct AI pillars (with caps)
            if is_hardware and len(ai_hardware) < 12:
                ai_hardware.append(e)
            elif is_agent_robotics and len(autonomous_agents) < 12:
                autonomous_agents.append(e)
            elif is_trending and len(trending_repos) < 12:
                trending_repos.append(e)
            elif is_model and len(ai_models_list) < 12:
                ai_models_list.append(e)
            elif is_research and len(ai_research_list) < 12:
                ai_research_list.append(e)
            elif is_tool and len(ai_tools_list) < 12:
                ai_tools_list.append(e)
            elif is_sovereign and len(sovereign_ai) < 12:
                sovereign_ai.append(e)
            elif len(trending_repos) < 12 and cat in ("github_trending", "ai_tech"):
                trending_repos.append(e)
            elif len(ai_models_list) < 12 and cat in ("ai_models", "ai_tech"):
                ai_models_list.append(e)
            elif len(ai_research_list) < 12 and cat in ("ai_research", "ai_tech"):
                ai_research_list.append(e)
            elif len(ai_tools_list) < 12:
                ai_tools_list.append(e)
            elif len(autonomous_agents) < 12:
                autonomous_agents.append(e)
            elif len(ai_hardware) < 12:
                ai_hardware.append(e)
            elif len(sovereign_ai) < 12:
                sovereign_ai.append(e)

        # Backfill any sparsely populated categories from remaining pool
        pool = remaining[:]
        def fill_section(target_list, min_count, predicate):
            if len(target_list) < min_count:
                candidates = [e for e in pool if predicate(e) and e not in target_list]
                target_list.extend(candidates[:min_count - len(target_list)])
            if len(target_list) < min_count:
                fallback_candidates = [e for e in pool if e not in target_list]
                target_list.extend(fallback_candidates[:min_count - len(target_list)])

        fill_section(trending_repos, 6, lambda e: (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("github_trending", "ai_tech", "cyber_tools"))
        fill_section(ai_models_list, 6, lambda e: (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("ai_models", "ai_tech"))
        fill_section(ai_research_list, 6, lambda e: (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("ai_research", "ai_tech"))
        fill_section(ai_tools_list, 6, lambda e: (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("cyber_tools", "ai_tech"))
        fill_section(sovereign_ai, 6, lambda e: True)
        fill_section(ai_hardware, 6, lambda e: True)
        fill_section(autonomous_agents, 6, lambda e: True)

        front_page_briefs = remaining[:6]
        ciso_briefs = remaining[6:12] if len(remaining) >= 12 else remaining[:6]

        # Universal Deep Web Extraction across ALL sections and overflow stories
        all_dossier_entries = (
            [lead, secondary_anchor]
            + front_page_briefs
            + ciso_briefs
            + trending_repos
            + ai_models_list
            + ai_research_list
            + ai_tools_list
            + sovereign_ai
            + ai_hardware
            + autonomous_agents
        )

        used_ids = {e.id for e in all_dossier_entries if e}
        overflow = [e for e in remaining if e.id not in used_ids]
        overflow.sort(key=lambda e: e.analysis.threat_velocity if e.analysis else 0, reverse=True)
        overflow = overflow[:10]

        candidates_to_enrich = [e for e in all_dossier_entries + overflow if e]
        logger.info(f"Initiating deep autonomous extraction across all {len(candidates_to_enrich)} dossier stories...")

        sem = asyncio.Semaphore(8)

        async def enrich_entry(entry: Entry):
            async with sem:
                try:
                    content = await article_extractor.extract_article_content(entry, min_words=60)
                    if content and len(content.split()) >= 30:
                        entry.summary = content
                except Exception as ex:
                    logger.debug(f"Web extraction skipped for {entry.title}: {ex}")

        if candidates_to_enrich:
            try:
                await asyncio.gather(*[enrich_entry(e) for e in candidates_to_enrich], return_exceptions=True)
            except Exception:
                pass

        # Clean all titles and format summaries
        for item in all_dossier_entries:
            if item:
                item.title = self._clean_title(item.title)
                item.summary = self._clean_and_format_summary(item.summary, entry=item, min_words=25, max_words=160)

        for item in overflow:
            item.title = self._clean_title(item.title)
            item.summary = self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=120)

        return {
            "lead": lead,
            "secondary_anchor": secondary_anchor,
            "front_page_briefs": front_page_briefs,
            "ciso_briefs": ciso_briefs,
            "trending_repos": trending_repos,
            "ai_models": ai_models_list,
            "ai_research": ai_research_list,
            "ai_tools": ai_tools_list,
            "sovereign_ai": sovereign_ai,
            "ai_hardware": ai_hardware,
            "autonomous_agents": autonomous_agents,
            "overflow": overflow,
        }

    # ─── Markdown Document Renderer ──────────────────────────────────────────

    def _render_markdown(
        self,
        entries: list[Entry],
        categorized: dict[str, Any],
        edition_num: int,
        generated_at: datetime,
        window_hours: int,
    ) -> str:
        date_str = generated_at.strftime("%A, %B %d, %Y • %H:%M UTC")
        lead = categorized["lead"]
        secondary = categorized.get("secondary_anchor")

        lead_title = self._clean_title(lead.title if lead else "Global AI Ecosystem Intelligence Report")
        lead_summary = self._clean_and_format_summary(lead.summary, entry=lead, min_words=40, max_words=160) if lead else "Continuous monitoring active across global AI intelligence nodes."
        lead_vel = lead.analysis.threat_velocity if lead and lead.analysis else 40
        lead_sev = lead.analysis.severity_index if lead and lead.analysis else 50
        lead_src = self._get_source_name(lead)

        sec_title = self._clean_title(secondary.title if secondary else "")
        sec_summary = self._clean_and_format_summary(secondary.summary, entry=secondary, min_words=30, max_words=120) if secondary else ""

        md = f"""# 📰 THE GLOBAL AI GAZETTE
**Comprehensive Worldwide AI Ecosystem Broadsheet • Edition #{edition_num}**  
*{date_str} • Coverage Window: {window_hours}h • {len(entries)} verified AI stories analyzed*

---

## 🏛️ [PAGE 1] FRONT PAGE: TODAY'S LEAD AI & TECHNOLOGY STORIES

### 🚨 {lead_title}
- **Velocity**: `{lead_vel}/100` | **Impact Score**: `{lead_sev}/100` | **Source**: `{lead_src}`

{lead_summary}

"""
        if secondary:
            md += f"""### ⚡ {sec_title}
{sec_summary}

"""

        md += "#### Top Flash Bulletins\n"
        for item in categorized.get("front_page_briefs", [])[:6]:
            vel = item.analysis.threat_velocity if item.analysis else 35
            item_sum = self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=80)
            md += f"- **{self._clean_title(item.title)}** (VEL `{vel}`) — {item_sum}\n"

        md += """
---

## 👔 [PAGE 2] EXECUTIVE AI BRIEFING: STRATEGIC ROADMAP & DIRECTIVES

> **Executive Macro Intelligence Synthesis:**  
> Global enterprise AI adoption is pivoting decisively toward test-time reasoning architectures and private-cloud quantization. Technology leadership must actively balance proprietary frontier model APIs with sovereign, open-weight deployments (e.g. DeepSeek, Qwen) to reduce token expenditure while strictly sandboxing autonomous agent tool-calling boundaries.

| Strategic Operational Vector | Priority Development | Source | Boardroom Action Directive |
| :--- | :--- | :--- | :--- |
"""
        vector_labels = [
            "Model Sourcing & Licensing",
            "Compute & Infrastructure CapEx",
            "Agentic Autonomy & Governance",
            "Inference Latency & Quantization",
            "Open-Source Supply Chain",
            "Data Residency & Sovereignty",
        ]
        for idx, item in enumerate(categorized.get("ciso_briefs", [])[:6]):
            vec = vector_labels[idx % len(vector_labels)]
            directive = self._generate_executive_directive(item, vector=vec)
            md += f"| **{vec}** | {self._clean_title(item.title)[:50]} | `{self._get_source_name(item)[:18]}` | {directive} |\n"

        md += "\n### Key Strategic Dispatches\n"
        for idx, item in enumerate(categorized.get("ciso_briefs", [])[:6], 1):
            vec = vector_labels[(idx - 1) % len(vector_labels)]
            directive = self._generate_executive_directive(item, vector=vec)
            item_sum = self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=80)
            md += f"{idx}. **{self._clean_title(item.title)}** — {item_sum}  \n   *Directive: {directive}*\n\n"

        md += """
---

## 🚀 [PAGE 3] TRENDING OPEN-SOURCE AI & GITHUB INNOVATIONS

| Repository / Project | Source | Primary Stack | Velocity | Core Architectural Focus |
| :--- | :--- | :--- | :--- | :--- |
"""
        for r in categorized.get("trending_repos", [])[:8]:
            vel = r.analysis.threat_velocity if r.analysis else 75
            specs = self.extract_technical_specs(r.title, r.summary or "")
            brief = self._clean_and_format_summary(r.summary, entry=r, min_words=8, max_words=20)
            md += f"| **{self._clean_title(r.title)[:50]}** | `{self._get_source_name(r)[:18]}` | `{specs['lang']}` | `{vel}/100` | {brief} |\n"

        md += "\n### Featured Repository Deep-Dives\n"
        for r in categorized.get("trending_repos", [])[:6]:
            vel = r.analysis.threat_velocity if r.analysis else 85
            specs = self.extract_technical_specs(r.title, r.summary or "")
            r_sum = self._clean_and_format_summary(r.summary, entry=r, min_words=30, max_words=130)
            md += f"### 🚀 {self._clean_title(r.title)}\n- **Velocity**: `{vel}/100` | **Stack**: `{specs['lang']}` | **Source**: `{self._get_source_name(r)}`\n\n{r_sum}\n\n"

        md += """
---

## 🤖 [PAGE 4] FRONTIER FOUNDATION MODELS & REASONING BREAKTHROUGHS

| Foundation Model | Source | Size / Context | Impact | Key Architectural Highlight |
| :--- | :--- | :--- | :--- | :--- |
"""
        for m in categorized.get("ai_models", [])[:8]:
            sev = m.analysis.severity_index if m.analysis else 80
            specs = self.extract_technical_specs(m.title, m.summary or "")
            brief = self._clean_and_format_summary(m.summary, entry=m, min_words=8, max_words=20)
            md += f"| **{self._clean_title(m.title)[:50]}** | `{self._get_source_name(m)[:18]}` | `{specs['size']} / {specs['ctx']}` | `{sev}/100` | {brief} |\n"

        md += "\n### Frontier Model Dispatches\n"
        for m in categorized.get("ai_models", [])[:6]:
            vel = m.analysis.threat_velocity if m.analysis else 90
            specs = self.extract_technical_specs(m.title, m.summary or "")
            m_sum = self._clean_and_format_summary(m.summary, entry=m, min_words=30, max_words=130)
            md += f"### 🤖 {self._clean_title(m.title)}\n- **Velocity**: `{vel}/100` | **Architecture**: `{specs['size']} • {specs['quant']}` | **Source**: `{self._get_source_name(m)}`\n\n{m_sum}\n\n"

        md += """
---

## 🔬 [PAGE 5] TOP AI RESEARCH PAPERS & ARXIV BREAKTHROUGHS

"""
        for paper in categorized.get("ai_research", [])[:6]:
            vel = paper.analysis.threat_velocity if paper.analysis else 80
            p_sum = self._clean_and_format_summary(paper.summary, entry=paper, min_words=30, max_words=130)
            md += f"### 🔬 {self._clean_title(paper.title)}\n- **Research Velocity**: `{vel}/100` | **Source**: `{self._get_source_name(paper)}`\n\n{p_sum}\n\n"

        md += """
---

## 🛠️ [PAGE 6] DEVELOPER TOOLS, FRAMEWORKS & AI INFRASTRUCTURE

"""
        for tool in categorized.get("ai_tools", [])[:6]:
            vel = tool.analysis.threat_velocity if tool.analysis else 75
            specs = self.extract_technical_specs(tool.title, tool.summary or "")
            t_sum = self._clean_and_format_summary(tool.summary, entry=tool, min_words=30, max_words=130)
            md += f"### 🛠️ {self._clean_title(tool.title)}\n- **Adoption Index**: `{vel}/100` | **Engine**: `{specs['engine']}` | **Source**: `{self._get_source_name(tool)}`\n\n{t_sum}\n\n"

        md += """
---

## 🌐 [PAGE 7] SOVEREIGN AI & GLOBAL REGIONAL ECOSYSTEMS

"""
        for ch in categorized.get("sovereign_ai", [])[:6]:
            c_code = (ch.metadata.get("country") if ch.metadata else "") or "SOV"
            flag = self._get_country_flag(c_code)
            ch_sum = self._clean_and_format_summary(ch.summary, entry=ch, min_words=25, max_words=120)
            md += f"### 🌐 {flag} [{c_code}] {self._clean_title(ch.title)}\n- **Source**: `{self._get_source_name(ch)}`\n\n{ch_sum}\n\n"

        md += """
---

## ⚡ [PAGE 8] AI HARDWARE, COMPUTE CLUSTERS & SILICON

"""
        if categorized.get("ai_hardware"):
            md += "| Silicon / System | Source | Compute Specs | Velocity | Telemetry / Benchmark |\n"
            md += "| :--- | :--- | :--- | :--- | :--- |\n"
            for hw in categorized.get("ai_hardware", [])[:6]:
                vel = hw.analysis.threat_velocity if hw.analysis else 70
                specs = self.extract_technical_specs(hw.title, hw.summary or "")
                brief = self._clean_and_format_summary(hw.summary, entry=hw, min_words=8, max_words=20)
                md += f"| **{self._clean_title(hw.title)[:50]}** | `{self._get_source_name(hw)[:18]}` | `{specs['thru']}` | `{vel}/100` | {brief} |\n"
            md += "\n"

        for hw in categorized.get("ai_hardware", [])[:6]:
            hw_sum = self._clean_and_format_summary(hw.summary, entry=hw, min_words=25, max_words=120)
            md += f"### ⚡ {self._clean_title(hw.title)}\n- **Source**: `{self._get_source_name(hw)}`\n\n{hw_sum}\n\n"

        md += """
---

## 🦾 [PAGE 9] AUTONOMOUS AGENTS, MULTI-AGENT SWARMS & ROBOTICS

"""
        if categorized.get("autonomous_agents"):
            md += "| Agent / Framework | Source | Protocol / Architecture | Velocity | Core Capability Domain |\n"
            md += "| :--- | :--- | :--- | :--- | :--- |\n"
            for ag in categorized.get("autonomous_agents", [])[:6]:
                vel = ag.analysis.threat_velocity if ag.analysis else 75
                specs = self.extract_technical_specs(ag.title, ag.summary or "")
                brief = self._clean_and_format_summary(ag.summary, entry=ag, min_words=8, max_words=20)
                md += f"| **{self._clean_title(ag.title)[:50]}** | `{self._get_source_name(ag)[:18]}` | `{specs['engine']}` | `{vel}/100` | {brief} |\n"
            md += "\n"

        for ag in categorized.get("autonomous_agents", [])[:6]:
            ag_sum = self._clean_and_format_summary(ag.summary, entry=ag, min_words=25, max_words=120)
            md += f"### 🦾 {self._clean_title(ag.title)}\n- **Source**: `{self._get_source_name(ag)}`\n\n{ag_sum}\n\n"

        overflow = categorized.get("overflow", [])
        md += f"""
---

## 📋 [PAGE 10] GLOBAL AI COMMUNITY WIRE & OVERFLOW DIGEST

*{len(overflow)} high-velocity AI stories from today's intelligence sweep that didn't fit earlier sections.*

"""
        for i, item in enumerate(overflow, 1):
            vel = item.analysis.threat_velocity if item.analysis else 50
            item_sum = self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=100)
            md += f"### {i}. {self._clean_title(item.title)}\n- **Source**: `{self._get_source_name(item)}` | **Velocity**: `{vel}/100`\n\n{item_sum}\n\n"

        md += f"""
---
*Compiled autonomously • {date_str} • Edition #{edition_num} • {len(entries)} items processed from worldwide AI feeds*
"""
        return md

    # ─── HTML Document Renderer ──────────────────────────────────────────────

    def _render_html(
        self,
        entries: list[Entry],
        categorized: dict[str, Any],
        edition_num: int,
        generated_at: datetime,
        window_hours: int,
        edition_id: str,
    ) -> str:
        date_str = generated_at.strftime("%A, %B %d, %Y")
        time_str = generated_at.strftime("%H:%M UTC")
        lead = categorized["lead"]
        secondary = categorized.get("secondary_anchor")

        lead_title = self._clean_title(lead.title if lead else "Global AI Ecosystem Intelligence Report")
        lead_summary = lead.summary if lead else "Continuous monitoring active across global AI intelligence nodes."
        lead_vel = lead.analysis.threat_velocity if lead and lead.analysis else 40
        lead_sev = lead.analysis.severity_index if lead and lead.analysis else 50
        lead_vec = lead.analysis.attack_vector if lead and lead.analysis else "Frontier model scaling"
        lead_mit = lead.analysis.mitigation if lead and lead.analysis else "Evaluate integration into production workflows"
        lead_src = self._get_source_name(lead)

        def card(item: Entry, badge: str, badge_color: str, stat: str = "VEL", limit: int = 120) -> str:
            vel = item.analysis.threat_velocity if item.analysis else 50
            sev = item.analysis.severity_index if item.analysis else 50
            stat_val = vel if stat == "VEL" else sev
            summary_text = html.escape(self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=limit))
            title_text = html.escape(self._clean_title(item.title))
            url = item.url or "#"
            src = html.escape(self._get_source_name(item))
            return f"""
        <div class="p-3.5 bg-white/80 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold" style="color:{badge_color}">{badge} • {stat} {stat_val}/100</span>
          <h4 class="font-serif font-bold text-xs mt-1 text-[#0f172a]"><a href="{html.escape(url)}" target="_blank" class="hover:underline">{title_text}</a></h4>
          <p class="text-[9.5px] text-[#6b7280] font-mono mt-0.5">SOURCE: {src}</p>
          <p class="text-[11px] text-[#4b5563] mt-1.5 leading-relaxed">{summary_text}</p>
        </div>"""

        def section_grid(items: list, badge: str, badge_color: str, stat: str = "VEL", limit_items: int = 6) -> str:
            if not items:
                return '<p class="text-xs text-[#9ca3af] italic">No stories in this category for this edition.</p>'
            return '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">\n' + "".join(
                card(item, badge, badge_color, stat) for item in items[:limit_items]
            ) + "\n    </div>"

        def dyn_table(headers: list[str], rows: list[list[str]]) -> str:
            th_cells = "".join(f'<th class="p-2 border border-[#d1cbba]">{h}</th>' for h in headers)
            tr_rows = ""
            for row in rows:
                td_cells = "".join(f'<td class="p-2">{cell}</td>' for cell in row)
                tr_rows += f"<tr>{td_cells}</tr>\n"
            return f"""<div class="overflow-x-auto mb-6">
      <table class="w-full text-left font-mono text-[11px] border border-[#d1cbba]">
        <thead class="bg-[#e2e8f0] text-[#0f172a]"><tr>{th_cells}</tr></thead>
        <tbody class="divide-y divide-[#d1cbba] bg-white/50">{tr_rows}</tbody>
      </table>
    </div>"""

        def page_header_row(section_label: str, topic_label: str, page_num: int) -> str:
            return f"""<div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>{section_label}</div><div>{topic_label}</div><div>PAGE {page_num} OF 10</div>
    </div>"""

        vector_labels = [
            "Model Sourcing & Licensing",
            "Compute & Infrastructure CapEx",
            "Agentic Autonomy & Governance",
            "Inference Latency & Quantization",
            "Open-Source Supply Chain",
            "Data Residency & Sovereignty",
        ]
        ciso_rows = [
            [f"<b>{vector_labels[idx % len(vector_labels)]}</b>",
             f"<b>{html.escape(self._clean_title(b.title)[:45])}</b>",
             html.escape(self._get_source_name(b)),
             html.escape(self._generate_executive_directive(b, vector=vector_labels[idx % len(vector_labels)]))]
            for idx, b in enumerate(categorized.get("ciso_briefs", [])[:6])
        ]
        repo_rows = [
            [f"<b>{html.escape(self._clean_title(r.title)[:45])}</b>",
             html.escape(self._get_source_name(r)),
             html.escape(self.extract_technical_specs(r.title, r.summary or "")["lang"]),
             f"{r.analysis.threat_velocity if r.analysis else 75}/100",
             html.escape(self._clean_and_format_summary(r.summary, entry=r, min_words=8, max_words=20))]
            for r in categorized.get("trending_repos", [])[:6]
        ]
        model_rows = [
            [f"<b>{html.escape(self._clean_title(m.title)[:45])}</b>",
             html.escape(self._get_source_name(m)),
             f"{self.extract_technical_specs(m.title, m.summary or '')['size']} / {self.extract_technical_specs(m.title, m.summary or '')['ctx']}",
             f"{m.analysis.severity_index if m.analysis else 85}/100",
             html.escape(self._clean_and_format_summary(m.summary, entry=m, min_words=8, max_words=20))]
            for m in categorized.get("ai_models", [])[:6]
        ]
        hardware_rows = [
            [f"<b>{html.escape(self._clean_title(h.title)[:45])}</b>",
             html.escape(self._get_source_name(h)),
             html.escape(self.extract_technical_specs(h.title, h.summary or "")["thru"]),
             f"{h.analysis.threat_velocity if h.analysis else 75}/100",
             html.escape(self._clean_and_format_summary(h.summary, entry=h, min_words=8, max_words=20))]
            for h in categorized.get("ai_hardware", [])[:6]
        ]
        agent_rows = [
            [f"<b>{html.escape(self._clean_title(a.title)[:45])}</b>",
             html.escape(self._get_source_name(a)),
             html.escape(self.extract_technical_specs(a.title, a.summary or "")["engine"]),
             f"{a.analysis.threat_velocity if a.analysis else 75}/100",
             html.escape(self._clean_and_format_summary(a.summary, entry=a, min_words=8, max_words=20))]
            for a in categorized.get("autonomous_agents", [])[:6]
        ]
        overflow = categorized.get("overflow", [])

        html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Global AI Gazette — Edition #{edition_num}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Cinzel:wght@700;900&family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {{ --paper: #fbf9f1; --ink: #0d1117; --border-ink: #1e2430; }}
    body {{ background-color: #0b0f17; color: var(--ink); font-family: 'Merriweather', Georgia, serif; }}
    .newspaper-sheet {{ background-color: var(--paper); box-shadow: 0 25px 60px rgba(0,0,0,0.65); border: 1px solid #d1cbba; page-break-after: always; break-after: page; min-height: 1050px; }}
    .masthead-title {{ font-family: 'Cinzel', serif; letter-spacing: -0.02em; }}
    .headline-font {{ font-family: 'Playfair Display', serif; line-height: 1.1; }}
    .editorial-col {{ column-count: 2; column-gap: 28px; column-rule: 1px solid #d8d3c5; text-align: justify; }}
    .double-rule-thick {{ border-top: 3px double var(--border-ink); border-bottom: 1px solid var(--border-ink); height: 6px; }}
    @media print {{ body {{ background: transparent !important; }} .no-print {{ display: none !important; }} .newspaper-sheet {{ box-shadow: none !important; border: none !important; }} }}
  </style>
</head>
<body class="py-8 px-2 sm:px-6">

  <!-- Print & Download Bar -->
  <div class="no-print max-w-5xl mx-auto mb-6 flex items-center justify-between bg-slate-900/90 backdrop-blur-md p-3.5 rounded-xl border border-white/10 text-white font-mono text-xs">
    <div class="flex items-center gap-3">
      <span class="flex items-center gap-1.5 text-cyan-400 font-bold">
        <span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
        THE GLOBAL AI GAZETTE — 10-PAGE DOSSIER
      </span>
      <span class="text-slate-500">|</span>
      <span class="text-slate-300">Edition #{edition_num} • {len(entries)} stories</span>
    </div>
    <div class="flex items-center gap-2">
      <button onclick="window.print()" class="px-3.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-slate-100 transition font-bold">🖨️ Print / Save PDF</button>
      <a href="/api/newspaper/download?format=pdf" class="px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition font-bold">📥 Download PDF</a>
    </div>
  </div>

  <!-- PAGE 1: FRONT PAGE -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("THE GLOBAL AI GAZETTE", "BREAKING WORLDWIDE AI INTELLIGENCE", 1)}
    <header class="text-center py-5 border-b border-[#1e2430]">
      <h1 class="masthead-title text-3xl sm:text-5xl md:text-6xl font-black uppercase text-[#0d1117] tracking-tight">The Global AI Gazette</h1>
      <p class="text-xs sm:text-sm italic text-[#4b5563] mt-1 font-serif">Worldwide AI Ecosystem Intelligence — Open Source, Research, Models, Tools & Sovereign AI</p>
    </header>
    <div class="double-rule-thick my-2"></div>
    <div class="flex items-center justify-between text-[11px] font-mono py-1 text-[#1f2937] font-semibold border-b border-[#1e2430]">
      <div>{date_str}</div><div>NO. {edition_num} • {len(entries)} STORIES ANALYZED</div><div>{time_str}</div>
    </div>

    <section class="mt-6 mb-6">
      <div class="text-[11px] font-mono font-bold uppercase tracking-widest text-cyan-800 mb-1">🔥 LEAD STORY — GLOBAL AI DISPATCH</div>
      <h2 class="headline-font text-2xl sm:text-4xl font-black text-[#0a0d13] mb-3 leading-tight">{html.escape(lead_title)}</h2>
      <p class="text-sm font-serif italic text-[#374151] mb-4 pb-2 border-b border-[#d1cbba]">
        Velocity {lead_vel}/100 · Impact {lead_sev}/100 · Source: {html.escape(lead_src)}
      </p>
      <div class="editorial-col text-xs leading-relaxed text-[#1f2937]">
        <p class="mb-3 first-letter:text-4xl first-letter:font-bold first-letter:float-left first-letter:mr-2 font-serif">{html.escape(lead_summary)}</p>
        <div class="my-2 p-2.5 bg-[#f2eedf] border-l-4 border-cyan-700 font-mono text-[10.5px]">
          <strong>INNOVATION FOCUS:</strong> {html.escape(lead_vec)}<br>
          <strong>ACTION MANDATE:</strong> {html.escape(lead_mit)}
        </div>
      </div>
    </section>

    {f'<section class="mb-6 p-4 bg-white/70 border border-[#d1cbba]"><div class="text-[10px] font-mono font-bold text-cyan-800 uppercase">⚡ SECONDARY ANCHOR</div><h3 class="font-serif font-bold text-base mt-1 text-[#0f172a]">{html.escape(self._clean_title(secondary.title))}</h3><p class="text-xs text-[#374151] mt-1 leading-relaxed">{html.escape(secondary.summary or "")}</p></section>' if secondary else ""}

    <div class="border-t-2 border-[#1e2430] pt-4">
      <h3 class="font-mono text-xs font-bold uppercase text-cyan-800 mb-3">⚡ Flash Bulletins</h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3.5 text-xs">
        {"".join([f'''
          <div class="p-2.5 bg-white/60 border border-[#d1cbba]">
            <span class="text-[9.5px] font-mono font-bold text-cyan-700">VEL {item.analysis.threat_velocity if item.analysis else 35}/100</span>
            <h4 class="font-serif font-bold text-xs mt-1"><a href="{item.url}" target="_blank" class="hover:text-cyan-700">{html.escape(self._clean_title(item.title))}</a></h4>
            <p class="text-[11px] text-[#4b5563] mt-1 leading-normal">{html.escape(self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=55))}</p>
          </div>''' for item in categorized.get("front_page_briefs", [])[:6]])}
      </div>
    </div>
  </article>

  <!-- PAGE 2: EXECUTIVE BRIEFING -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION II: EXECUTIVE BRIEFING", "STRATEGIC HORIZON & DIRECTIVES", 2)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Executive AI Strategic Briefing</h2>
    <div class="p-3.5 bg-[#f2eedf] border border-[#d1cbba] text-xs font-serif leading-relaxed mb-4 text-[#1e293b]">
      <strong>Executive Macro Intelligence Synthesis:</strong> Global enterprise AI adoption is pivoting decisively toward test-time reasoning architectures and private-cloud quantization. Technology leadership must actively balance proprietary frontier model APIs with sovereign, open-weight deployments to reduce token expenditure while strictly sandboxing autonomous agent tool-calling boundaries.
    </div>
    {dyn_table(["OPERATIONAL VECTOR", "KEY DEVELOPMENT", "SOURCE", "STRATEGIC DIRECTIVE"], ciso_rows)}
    <div class="space-y-2.5 text-xs font-mono">
      {"".join([f'''
        <div class="p-2.5 bg-white/60 border border-[#d1cbba] flex items-baseline gap-2">
          <span class="text-cyan-700 font-bold">{idx}.</span>
          <div><strong>{html.escape(self._clean_title(b.title))}:</strong> {html.escape(self._clean_and_format_summary(b.summary, entry=b, min_words=25, max_words=80))}</div>
        </div>''' for idx, b in enumerate(categorized.get("ciso_briefs", [])[:6], start=1)])}
    </div>
  </article>

  <!-- PAGE 3: TRENDING REPOS -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION III: OPEN SOURCE INNOVATIONS", "GITHUB VELOCITY & REPOSITORY TELEMETRY", 3)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Trending Open-Source AI & GitHub Innovations</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Top repositories from today's global developer community intelligence sweep.</p>
    {dyn_table(["PROJECT / REPO", "SOURCE", "PRIMARY STACK", "VELOCITY", "CORE ARCHITECTURAL FOCUS"], repo_rows)}
    {section_grid(categorized.get("trending_repos", []), "🚀 TRENDING REPO", "#0891b2", "VEL")}
  </article>

  <!-- PAGE 4: FRONTIER AI MODELS -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION IV: FRONTIER AI MODELS", "REASONING BREAKTHROUGHS & CAPABILITY BENCHMARKS", 4)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Frontier Foundation Models & Reasoning Breakthroughs</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Foundation models, reasoning breakthroughs, and open-weight releases from today's feeds.</p>
    {dyn_table(["FOUNDATION MODEL", "SOURCE", "SIZE / CONTEXT", "IMPACT", "KEY ARCHITECTURAL HIGHLIGHT"], model_rows)}
    {section_grid(categorized.get("ai_models", []), "🤖 FRONTIER MODEL", "#7c3aed", "IMPACT")}
  </article>

  <!-- PAGE 5: AI RESEARCH -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION V: ACADEMIC & ARXIV RESEARCH", "SCIENTIFIC INQUIRIES & ALIGNMENT BREAKTHROUGHS", 5)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Top AI Research Papers & arXiv Breakthroughs</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Seminal preprints and peer-reviewed papers from today's research intelligence sweep.</p>
    {section_grid(categorized.get("ai_research", []), "🔬 AI RESEARCH", "#4338ca", "VEL", 8)}
  </article>

  <!-- PAGE 6: DEVELOPER TOOLS -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION VI: DEVELOPER TOOLS & FRAMEWORKS", "AI RUNTIMES & INFERENCE INFRASTRUCTURE", 6)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Developer Tools, Frameworks & AI Infrastructure</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Inference runtimes, evaluation harnesses, vector databases, and local execution engines.</p>
    {section_grid(categorized.get("ai_tools", []), "🛠️ AI TOOL", "#0d9488", "VEL", 8)}
  </article>

  <!-- PAGE 7: SOVEREIGN AI -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION VII: SOVEREIGN RADAR", "TIER 1 & TIER 2 SOVEREIGN TELEMETRY", 7)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Sovereign AI & Worldwide Regional Ecosystems</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">National AI labs, regional foundation models, and sovereign compute ecosystems.</p>
    {section_grid(categorized.get("sovereign_ai", []), "🌐 SOVEREIGN WIRE", "#b91c1c", "VEL", 8)}
  </article>

  <!-- PAGE 8: AI HARDWARE -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION VIII: AI HARDWARE & SILICON", "COMPUTE CLUSTERS, ACCELERATORS & CHIPS", 8)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">AI Hardware, Compute Clusters & Silicon</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">GPU clusters, AI accelerators, datacenter infrastructure, and custom silicon.</p>
    {dyn_table(["SILICON / SYSTEM", "SOURCE", "COMPUTE SPECS", "VELOCITY", "TELEMETRY / BENCHMARK"], hardware_rows) if hardware_rows else ""}
    {section_grid(categorized.get("ai_hardware", []), "⚡ AI SILICON", "#d97706", "VEL", 6)}
  </article>

  <!-- PAGE 9: AUTONOMOUS AGENTS -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION IX: AUTONOMOUS AGENTS & ROBOTICS", "MULTI-AGENT SWARMS & EMBODIED INTELLIGENCE", 9)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Autonomous Agents, Multi-Agent Swarms & Robotics</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Agent orchestration, computer-use frameworks, action models, and embodied robotics.</p>
    {dyn_table(["AGENT / FRAMEWORK", "SOURCE", "PROTOCOL / ARCHITECTURE", "VELOCITY", "CORE CAPABILITY DOMAIN"], agent_rows) if agent_rows else ""}
    {section_grid(categorized.get("autonomous_agents", []), "🦾 AGENT SYSTEM", "#059669", "VEL", 6)}
  </article>

  <!-- PAGE 10: OVERFLOW DIGEST -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    {page_header_row("SECTION X: COMMUNITY WIRE", "TOP STORIES YOU MAY HAVE MISSED", 10)}
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Global AI Community Wire & Overflow Digest</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">{len(overflow)} high-velocity AI stories from today's intelligence sweep that didn't fit earlier sections.</p>
    <div class="space-y-3 text-xs">
      {"".join([f'''
        <div class="p-3 bg-white/60 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-slate-600">VEL {item.analysis.threat_velocity if item.analysis else 50}/100 • {html.escape(self._get_source_name(item))}</span>
          <h4 class="font-serif font-bold text-xs mt-1"><a href="{item.url}" target="_blank" class="hover:underline">{html.escape(self._clean_title(item.title))}</a></h4>
          <p class="text-[11px] text-[#4b5563] mt-1 leading-relaxed">{html.escape(self._clean_and_format_summary(item.summary, entry=item, min_words=20, max_words=80))}</p>
        </div>''' for item in overflow])}
    </div>
    <div class="p-4 bg-[#f2eedf] border border-[#d1cbba] text-[11px] leading-relaxed text-[#4b5563] font-mono mt-6">
      <strong>COLOPHON:</strong> The Global AI Gazette is compiled autonomously. Data is aggregated across authoritative global AI sources including Hugging Face, GitHub Trending, arXiv, and leading AI research lab feeds. Edition #{edition_num} • {len(entries)} items processed. All rights reserved.
    </div>
  </article>

  <footer class="text-center font-mono text-[10px] text-[#4b5563] pt-4 pb-8">
    PUBLISHED AUTONOMOUSLY BY THE GLOBAL AI GAZETTE ENGINE • EDITION #{edition_num} • {date_str} • ALL RIGHTS RESERVED
  </footer>

</body>
</html>
"""
        return html_out

    # ─── 10-Page PDF Document Renderer ───────────────────────────────────────

    def _render_pdf(
        self,
        pdf_path: Path,
        entries: list[Entry],
        categorized: dict[str, Any],
        edition_num: int,
        generated_at: datetime,
        window_hours: int,
    ) -> None:
        """Render an authoritative 10-page executive intelligence PDF broadsheet dossier."""
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            leftMargin=36, rightMargin=36, topMargin=38, bottomMargin=40,
        )

        masthead_title = ParagraphStyle("MastheadTitle", fontName="Helvetica-Bold", fontSize=21, leading=24, alignment=1, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
        masthead_sub = ParagraphStyle("MastheadSub", fontName="Helvetica-Oblique", fontSize=7.5, leading=9.5, alignment=1, textColor=colors.HexColor("#475569"), spaceAfter=4)
        page_header = ParagraphStyle("PageHeader", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
        page_sub = ParagraphStyle("PageSub", fontName="Helvetica-Oblique", fontSize=8, leading=10, textColor=colors.HexColor("#475569"), spaceAfter=6)
        dateline_style = ParagraphStyle("Dateline", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor("#1e293b"))
        headline_style = ParagraphStyle("Headline", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#0a0d13"), spaceAfter=2)
        body_style = ParagraphStyle("Body", fontName="Times-Roman", fontSize=8, leading=10.5, textColor=colors.HexColor("#1f2937"), alignment=4, spaceAfter=3)
        item_title = ParagraphStyle("ItemTitle", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.HexColor("#0f172a"))
        item_meta = ParagraphStyle("ItemMeta", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.HexColor("#0891b2"))
        item_summary = ParagraphStyle("ItemSummary", fontName="Times-Roman", fontSize=7.5, leading=10, textColor=colors.HexColor("#334155"), alignment=4)
        callout_box_text = ParagraphStyle("CalloutBoxText", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.HexColor("#0f172a"))

        date_str = generated_at.strftime("%A, %B %d, %Y • %H:%M UTC")
        story = []

        def render_article_card(item: Entry, tag_color: str, tag_label: str, stat_label: str = "VEL") -> list:
            src = self._get_source_name(item)
            vel = item.analysis.threat_velocity if item.analysis else 50
            sev = item.analysis.severity_index if item.analysis else 50
            stat_val = vel if stat_label == "VEL" else sev
            title_text = f"<b>{html.escape(self._clean_title(item.title))}</b>"
            meta_text = (
                f"<font color='{tag_color}'><b>[{tag_label}]</b></font> "
                f"<b>SOURCE:</b> {html.escape(src[:24])} | <b>{stat_label}:</b> {stat_val}/100"
            )
            specs = self.extract_technical_specs(item.title, item.summary or "")
            specs_text = (
                f"<font color='#047857'><b>ARCH:</b> {html.escape(specs['size'])}</font> • "
                f"<font color='#4338ca'><b>CTX:</b> {html.escape(specs['ctx'])}</font> • "
                f"<font color='#b45309'><b>QUANT:</b> {html.escape(specs['quant'])}</font> • "
                f"<font color='#0e7490'><b>STACK:</b> {html.escape(specs['engine'])}</font>"
            )
            body_text = html.escape(self._clean_and_format_summary(item.summary, entry=item, min_words=25, max_words=115))
            return [
                Paragraph(meta_text, item_meta),
                Paragraph(title_text, item_title),
                Paragraph(specs_text, ParagraphStyle("SpecBadge", fontName="Helvetica", fontSize=6.5, leading=8.5, textColor=colors.HexColor("#334155"))),
                Spacer(1, 1),
                Paragraph(body_text, item_summary),
                Spacer(1, 4),
            ]

        def make_table(headers: list, rows: list, col_widths: list) -> Table:
            data = [[Paragraph(f"<b>{h}</b>", dateline_style) for h in headers]]
            for row in rows:
                data.append([Paragraph(str(cell), item_summary) for cell in row])
            t = Table(data, colWidths=col_widths)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            return t

        # ═══ PAGE 1: FRONT PAGE ═══
        story.append(Table([[
            Paragraph("THE GLOBAL AI GAZETTE", dateline_style),
            Paragraph("WORLDWIDE AI ECOSYSTEM INTELLIGENCE", dateline_style),
            Paragraph(f"PAGE 1 OF 10 • EDITION {edition_num}", ParagraphStyle("R", fontName="Helvetica-Bold", fontSize=7.5, alignment=2, textColor=colors.HexColor("#1e293b"))),
        ]], colWidths=[180, 190, 170]))
        story.append(Spacer(1, 2))
        story.append(Paragraph("THE GLOBAL AI GAZETTE", masthead_title))
        story.append(Paragraph("Worldwide AI Ecosystem Intelligence • Open Source • Research • Models • Tools • Sovereign AI", masthead_sub))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f172a"), spaceAfter=1))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#0f172a"), spaceAfter=3))
        story.append(Table([[
            Paragraph(f"<b>{date_str}</b>", dateline_style),
            Paragraph(f"<b>EDITION NO. {edition_num}</b>", ParagraphStyle("C", fontName="Helvetica-Bold", fontSize=7.5, alignment=1, textColor=colors.HexColor("#1e293b"))),
            Paragraph(f"<b>{len(entries)} STORIES ANALYZED</b>", ParagraphStyle("R", fontName="Helvetica-Bold", fontSize=7.5, alignment=2, textColor=colors.HexColor("#1e293b"))),
        ]], colWidths=[200, 140, 200]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))

        lead = categorized["lead"]
        if lead:
            lead_vel = lead.analysis.threat_velocity if lead.analysis else 40
            lead_sev = lead.analysis.severity_index if lead.analysis else 50
            lead_vec = lead.analysis.attack_vector if lead.analysis else "Frontier AI development"
            lead_mit = lead.analysis.mitigation if lead.analysis else "Evaluate integration into production workflows"
            story.append(Paragraph("<font color='#0891b2'><b>🔥 LEAD STORY</b></font>", dateline_style))
            story.append(Paragraph(html.escape(self._clean_title(lead.title)), headline_style))
            story.append(Paragraph(f"Velocity {lead_vel}/100 · Impact {lead_sev}/100 · Source: {html.escape(self._get_source_name(lead))}", dateline_style))
            lead_words = (lead.summary or "").split()
            lead_display = " ".join(lead_words[:130]) + ("..." if len(lead_words) > 130 else "")
            story.append(Paragraph(html.escape(lead_display), body_style))
            lead_box = Table([[Paragraph(f"<b>INNOVATION:</b> {html.escape(lead_vec)}<br/><b>ACTION:</b> {html.escape(lead_mit)}", callout_box_text)]], colWidths=[540])
            lead_box.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")), ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")), ("PADDING", (0,0), (-1,-1), 3)]))
            story.append(lead_box)

        secondary = categorized.get("secondary_anchor")
        if secondary:
            story.append(Spacer(1, 2))
            story.append(Paragraph("<font color='#1e3a8a'><b>⚡ SECONDARY ANCHOR</b></font>", dateline_style))
            story.append(Paragraph(html.escape(self._clean_title(secondary.title)), headline_style))
            sec_words = (secondary.summary or "").split()
            sec_display = " ".join(sec_words[:65]) + ("..." if len(sec_words) > 65 else "")
            story.append(Paragraph(html.escape(sec_display), body_style))

        story.append(Spacer(1, 2))
        story.append(Paragraph("<b>⚡ TOP FLASH BULLETINS</b>", page_header))
        bulletin_data = []
        for b in categorized.get("front_page_briefs", [])[:5]:
            vel = b.analysis.threat_velocity if b.analysis else 35
            sum_words = (b.summary or "").split()
            sum_text = " ".join(sum_words[:25]) + ("..." if len(sum_words) > 25 else "")
            bulletin_data.append([Paragraph(f"<font color='#0891b2'><b>[VEL {vel}]</b></font> <b>{html.escape(self._clean_title(b.title))}</b> — {html.escape(sum_text)}", item_summary)])
        if bulletin_data:
            bt = Table(bulletin_data, colWidths=[540])
            bt.setStyle(TableStyle([("LINEBELOW", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")), ("PADDING", (0,0), (-1,-1), 2)]))
            story.append(bt)
        story.append(PageBreak())

        # ═══ PAGE 2: EXECUTIVE BRIEFING ═══
        story.append(Paragraph("👔 SECTION II: EXECUTIVE AI STRATEGIC BRIEFING", page_header))
        story.append(Paragraph("Strategic Horizons & Action Directives for Enterprise Leadership", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        story.append(Paragraph("<b>EXECUTIVE MACRO INTELLIGENCE SYNTHESIS:</b> Global enterprise AI adoption is pivoting decisively toward test-time reasoning architectures and private-cloud quantization. Technology leadership must actively balance proprietary frontier model APIs with sovereign, open-weight deployments to reduce token expenditure while strictly sandboxing autonomous agent tool-calling boundaries.", body_style))
        story.append(Spacer(1, 3))
        vector_labels = [
            "Model Sourcing & Licensing",
            "Compute & Infrastructure CapEx",
            "Agentic Autonomy & Governance",
            "Inference Latency & Quantization",
            "Open-Source Supply Chain",
            "Data Residency & Sovereignty",
        ]
        matrix_rows = [
            [vector_labels[idx % len(vector_labels)],
             self._clean_title(item.title)[:40],
             self._get_source_name(item)[:15],
             self._generate_executive_directive(item, vector=vector_labels[idx % len(vector_labels)])[:70]]
            for idx, item in enumerate(categorized.get("ciso_briefs", [])[:6])
        ]
        story.append(make_table(["VECTOR", "DEVELOPMENT", "SOURCE", "DIRECTIVE"], matrix_rows, [120, 150, 90, 180]))
        story.append(Spacer(1, 4))
        for idx, item in enumerate(categorized.get("ciso_briefs", [])[:6], 1):
            vec = vector_labels[(idx - 1) % len(vector_labels)]
            directive = self._generate_executive_directive(item, vector=vec)
            story.append(Paragraph(f"<b>{idx}. {html.escape(self._clean_title(item.title))}:</b> {html.escape(directive)}", ParagraphStyle("Dir", fontName="Times-Roman", fontSize=8, leading=11, textColor=colors.HexColor("#1f2937"), spaceAfter=4)))
        story.append(PageBreak())

        # ═══ PAGE 3: TRENDING REPOS ═══
        story.append(Paragraph("🚀 SECTION III: TRENDING OPEN-SOURCE AI & GITHUB INNOVATIONS", page_header))
        story.append(Paragraph("Top GitHub Repositories, Developer Velocity & Architecture Dissections", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        if categorized.get("trending_repos"):
            repo_table_data = [
                [self._clean_title(r.title)[:45], self._get_source_name(r)[:16],
                 self.extract_technical_specs(r.title, r.summary or "")["lang"],
                 f"{r.analysis.threat_velocity if r.analysis else 75}/100",
                 self._clean_and_format_summary(r.summary, entry=r, min_words=8, max_words=18)]
                for r in categorized.get("trending_repos", [])[:6]
            ]
            story.append(make_table(["PROJECT / REPO", "SOURCE", "STACK", "VELOCITY", "CORE ARCHITECTURAL FOCUS"], repo_table_data, [150, 85, 65, 60, 180]))
            story.append(Spacer(1, 4))
        for item in categorized.get("trending_repos", [])[:5]:
            for element in render_article_card(item, tag_color="#0891b2", tag_label="TRENDING REPO", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 4: FRONTIER AI MODELS ═══
        story.append(Paragraph("🤖 SECTION IV: FRONTIER FOUNDATION MODELS & REASONING BREAKTHROUGHS", page_header))
        story.append(Paragraph("Reasoning Architectures, Open Weights & Capability Benchmarks", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        if categorized.get("ai_models"):
            model_table_data = [
                [self._clean_title(m.title)[:45], self._get_source_name(m)[:16],
                 f"{self.extract_technical_specs(m.title, m.summary or '')['size']} / {self.extract_technical_specs(m.title, m.summary or '')['ctx']}",
                 f"{m.analysis.severity_index if m.analysis else 85}/100",
                 self._clean_and_format_summary(m.summary, entry=m, min_words=8, max_words=18)]
                for m in categorized.get("ai_models", [])[:6]
            ]
            story.append(make_table(["FOUNDATION MODEL", "SOURCE", "SIZE / CTX", "IMPACT", "ARCHITECTURAL HIGHLIGHT"], model_table_data, [150, 85, 75, 50, 180]))
            story.append(Spacer(1, 4))
        for item in categorized.get("ai_models", [])[:5]:
            for element in render_article_card(item, tag_color="#7c3aed", tag_label="FRONTIER MODEL", stat_label="IMPACT"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 5: AI RESEARCH ═══
        story.append(Paragraph("🔬 SECTION V: TOP AI RESEARCH PAPERS & ARXIV BREAKTHROUGHS", page_header))
        story.append(Paragraph("Reasoning Paradigms, Multimodal Architectures & Algorithmic Design", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        for item in categorized.get("ai_research", [])[:6]:
            for element in render_article_card(item, tag_color="#4338ca", tag_label="AI RESEARCH", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 6: DEVELOPER TOOLS ═══
        story.append(Paragraph("🛠️ SECTION VI: DEVELOPER TOOLS, FRAMEWORKS & AI INFRASTRUCTURE", page_header))
        story.append(Paragraph("Inference Runtimes, Evaluation Frameworks, Vector DBs & Local Execution Engines", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        for item in categorized.get("ai_tools", [])[:6]:
            for element in render_article_card(item, tag_color="#0d9488", tag_label="AI TOOL", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 7: SOVEREIGN AI ═══
        story.append(Paragraph("🌐 SECTION VII: SOVEREIGN AI & WORLDWIDE REGIONAL ECOSYSTEMS", page_header))
        story.append(Paragraph("National AI Labs, Regional Models & Sovereign Compute Ecosystems", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        for item in categorized.get("sovereign_ai", [])[:6]:
            c_code = (item.metadata.get("country") if item.metadata else "") or "SOV"
            for element in render_article_card(item, tag_color="#b91c1c", tag_label=f"SOVEREIGN [{c_code}]", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 8: AI HARDWARE ═══
        story.append(Paragraph("⚡ SECTION VIII: AI HARDWARE, COMPUTE CLUSTERS & SILICON", page_header))
        story.append(Paragraph("GPU Clusters, Custom Accelerators, Datacenter Infrastructure & Silicon", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        if categorized.get("ai_hardware"):
            hw_table_data = [
                [self._clean_title(h.title)[:45], self._get_source_name(h)[:16],
                 self.extract_technical_specs(h.title, h.summary or "")["thru"],
                 f"{h.analysis.threat_velocity if h.analysis else 75}/100",
                 self._clean_and_format_summary(h.summary, entry=h, min_words=8, max_words=18)]
                for h in categorized.get("ai_hardware", [])[:6]
            ]
            story.append(make_table(["SILICON / SYSTEM", "SOURCE", "COMPUTE SPECS", "VELOCITY", "BENCHMARK / TELEMETRY"], hw_table_data, [150, 85, 75, 50, 180]))
            story.append(Spacer(1, 4))
        for item in categorized.get("ai_hardware", [])[:5]:
            for element in render_article_card(item, tag_color="#d97706", tag_label="AI HARDWARE", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 9: AUTONOMOUS AGENTS ═══
        story.append(Paragraph("🦾 SECTION IX: AUTONOMOUS AGENTS, MULTI-AGENT SWARMS & ROBOTICS", page_header))
        story.append(Paragraph("Agent Orchestration, Computer-Use Primitives, Action Models & Robotics", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        if categorized.get("autonomous_agents"):
            agent_table_data = [
                [self._clean_title(a.title)[:45], self._get_source_name(a)[:16],
                 self.extract_technical_specs(a.title, a.summary or "")["engine"],
                 f"{a.analysis.threat_velocity if a.analysis else 75}/100",
                 self._clean_and_format_summary(a.summary, entry=a, min_words=8, max_words=18)]
                for a in categorized.get("autonomous_agents", [])[:6]
            ]
            story.append(make_table(["AGENT / FRAMEWORK", "SOURCE", "PROTOCOL", "VELOCITY", "CORE CAPABILITY DOMAIN"], agent_table_data, [150, 85, 75, 50, 180]))
            story.append(Spacer(1, 4))
        for item in categorized.get("autonomous_agents", [])[:5]:
            for element in render_article_card(item, tag_color="#059669", tag_label="AGENT SYSTEM", stat_label="VEL"):
                story.append(element)
        story.append(PageBreak())

        # ═══ PAGE 10: OVERFLOW DIGEST ═══
        story.append(Paragraph("📋 SECTION X: GLOBAL AI COMMUNITY WIRE & OVERFLOW DIGEST", page_header))
        story.append(Paragraph("High-velocity AI stories from today's sweep that didn't fit earlier sections", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))
        for item in categorized.get("overflow", [])[:8]:
            for element in render_article_card(item, tag_color="#64748b", tag_label="OVERFLOW", stat_label="VEL"):
                story.append(element)

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"<b>COLOPHON & SENSOR METHODOLOGY:</b> The Global AI Gazette is compiled autonomously. "
            f"Data is aggregated across authoritative global AI sources including Hugging Face, GitHub Trending, arXiv, and leading AI research lab feeds. "
            f"Edition #{edition_num} • {len(entries)} items processed • {date_str}. All rights reserved.",
            body_style
        ))

        # Build PDF with NumberedCanvas for exact page count
        doc.build(story, canvasmaker=NumberedCanvas)




_newspaper_service = NewspaperService()
