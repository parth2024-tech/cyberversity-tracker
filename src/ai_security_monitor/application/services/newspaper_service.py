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
from uuid import uuid4

import feedparser
import httpx
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
from ai_security_monitor.application.services.newspaper.fetcher import (
    NewspaperLiveFetcher,
)
from ai_security_monitor.application.services.newspaper.renderer import (
    NewspaperRenderer,
    NumberedCanvas,
)

COUNTRY_FLAGS: dict[str, str] = {
    "US": "🇺🇸",
    "CN": "🇨🇳",
    "HK": "🇭🇰",
    "IN": "🇮🇳",
    "IL": "🇮🇱",
    "JP": "🇯🇵",
    "KR": "🇰🇷",
    "GB": "🇬🇧",
    "EU": "🇪🇺",
    "SG": "🇸🇬",
    "TW": "🇹🇼",
    "AE": "🇦🇪",
    "CA": "🇨🇦",
    "DE": "🇩🇪",
    "FR": "🇫🇷",
    "NL": "🇳🇱",
    "FI": "🇫🇮",
    "SE": "🇸🇪",
    "CH": "🇨🇭",
    "AU": "🇦🇺",
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
        self._live_fetcher = NewspaperLiveFetcher()
        self._renderer = NewspaperRenderer()

    def _compute_edition_number(self, dt: datetime) -> int:
        """Compute epoch-based sequential edition number."""
        epoch = datetime(2026, 1, 1, tzinfo=UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        hours = int((dt - epoch).total_seconds() // 3600)
        return 1000 + (hours // 5)

    async def _fetch_live_ai_intelligence(self) -> list[Entry]:
        """Autonomously fetch live cutting-edge AI entries via NewspaperLiveFetcher."""
        return await self._live_fetcher.fetch_live_intelligence()

    async def generate_edition(self, window_hours: int = 5) -> dict[str, Any]:
        """Compile an authentic, 100% AI-focused 10-page intelligence broadsheet dossier."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=max(5, window_hours))
        logger.info(
            f"Initiating 10-page AI intelligence newspaper compilation (window={window_hours}h)..."
        )

        def is_security_item(e: Entry) -> bool:
            cat_val = (
                e.category.value if hasattr(e.category, "value") else str(e.category)
            )
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
            is_technical_id = bool(
                re.search(
                    r"[\w\-]+/[\w\-]+|\b(?:qwen|deepseek|llama|mistral|gpt|claude|gemini|vllm|ollama|sglang|gguf)\b",
                    t_lower,
                )
            )
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
                cat_val = (
                    e.category.value
                    if hasattr(e.category, "value")
                    else str(e.category)
                )
                if cat_val in (
                    "ai_models",
                    "ai_research",
                    "github_trending",
                    "cyber_tools",
                ):
                    return True
                combined = f"{(e.title or '').lower()} {(e.summary or '').lower()}"
                ai_keywords = (
                    "ai",
                    "artificial intelligence",
                    "llm",
                    "model",
                    "neural",
                    "deep learning",
                    "machine learning",
                    "gpu",
                    "tpu",
                    "agent",
                    "agentic",
                    "transformer",
                    "reasoning",
                    "dataset",
                    "inference",
                    "quantization",
                    "gguf",
                    "algorithm",
                    "compute",
                    "silicon",
                    "semiconductor",
                    "chip",
                    "chips",
                    "robot",
                    "robotics",
                    "vision",
                    "multimodal",
                    "prompt",
                    "token",
                    "weights",
                    "fine-tune",
                    "embedding",
                    "vector",
                    "rag",
                    "eval",
                    "framework",
                    "runtime",
                    "huggingface",
                    "openai",
                    "anthropic",
                    "meta ai",
                    "deepseek",
                    "qwen",
                    "mistral",
                    "google ai",
                    "gemini",
                    "claude",
                    "llama",
                    "data center",
                    "datacenter",
                    "open-source",
                    "open source",
                )
                return any(
                    re.search(rf"\b{re.escape(k)}\b", combined) for k in ai_keywords
                )

            # Strict AI isolation: purge all CVE/vulnerability/exploit entries and non-AI general news
            entries = [
                e
                for e in raw_entries
                if not is_security_item(e)
                and is_ai_relevant(e)
                and calculate_content_quality(e)
            ]

            # Rich backfill if overall volume is sparse — query purely AI-focused historical records
            if len(entries) < 100:
                logger.info(
                    "Backfilling historical AI intelligence to assemble comprehensive 10-page dossier."
                )
                for pillar_cat in (
                    Category.AI_MODELS,
                    Category.AI_RESEARCH,
                    Category.GITHUB_TRENDING,
                    Category.AI_TECH,
                ):
                    fallback_filters = EntryFilters(
                        category=pillar_cat, sort_by="velocity"
                    )
                    fallback_items = await uow.entries.list(
                        filters=fallback_filters,
                        pagination=PaginationParams(limit=60, offset=0),
                    )
                    for item in fallback_items:
                        if (
                            item.id not in existing_ids
                            and not is_security_item(item)
                            and is_ai_relevant(item)
                            and calculate_content_quality(item)
                        ):
                            entries.append(item)
                            existing_ids.add(item.id)

        # Autonomous Live Extraction Fallback: If database yielded fewer than 45 verified AI stories,
        # immediately execute a live sweep across arXiv, Hugging Face, and leading AI feeds.
        if len(entries) < 45:
            logger.info(
                f"Database contains only {len(entries)} stories; executing autonomous live AI intelligence sweep..."
            )
            try:
                live_items = await self._fetch_live_ai_intelligence()
                for item in live_items:
                    if (
                        item.id not in existing_ids
                        and not is_security_item(item)
                        and is_ai_relevant(item)
                    ):
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
            "lead_story": categorized["lead"].title
            if categorized["lead"]
            else "Global AI Intelligence Report",
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
        for meta_file in sorted(
            self._output_dir.glob("chronicle_*.json"), reverse=True
        )[:limit]:
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

        quant_match = re.search(
            r"\b(GGUF|AWQ|EXL2|FP8|FP4|INT4|INT8|UD-[A-Z0-9_]+)\b", text, re.I
        )
        quant = quant_match.group(1).upper() if quant_match else "Native / FP16"

        engine_match = re.search(
            r"\b(vLLM|SGLang|llama\.cpp|Ollama|MLX|MLX-serve|TensorRT-LLM|CUDA|PyTorch)\b",
            text,
            re.I,
        )
        engine = engine_match.group(1) if engine_match else "PyTorch / ONNX"

        thru_match = re.search(
            r"\b(\d+(?:\.\d+)?\s*(?:tok/s|t/s|tokens per second|GB/s))\b", text, re.I
        )
        thru = thru_match.group(1) if thru_match else "High Velocity"

        lang_match = re.search(
            r"\b(Python|Rust|C\+\+|TypeScript|Go|CUDA)\b", text, re.I
        )
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
        t = re.sub(
            r"^(?:Trending|Release|Tool|Update|RFC|Paper|PSA)\s*:\s*", "", t, flags=re.I
        )
        t = re.sub(
            r"^\[(?:D|R|P|News|Project|Discussion|Research|webapps|remote)\]\s*",
            "",
            t,
            flags=re.I,
        )
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
        text = re.sub(
            r"(?i)\b(?:submitted by|posted by)\b.*?(?:\[comments\]|\[link\]|$)",
            " ",
            text,
        )
        text = re.sub(r"(?i)\[(?:link|comments)\]", " ", text)
        text = re.sub(r"(?i)/u/\S+", " ", text)
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"\(http[^\)]+\)", " ", text)
        text = re.sub(
            r"\b(?:here|at|see|check|demo|demo here)\s*:\s*(?=[A-Z])",
            " ",
            text,
            flags=re.I,
        )

        # 3. Clean WeChat / sovereign news header clutter
        text = re.sub(
            r"^[A-Za-z\s]+ \d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Za-z\s]+", "", text
        )
        text = re.sub(
            r"^Original Leading the Digital Supply Chain.*?\bBeijing\b",
            "",
            text,
            flags=re.I,
        )

        # 4. Clean conversational forum slang and first-person informalities
        text = re.sub(
            r"(?i)\b(?:lol|lmao|rofl|imho|tbh|fyi|btw|y'all|hey guys)\b", "", text
        )
        text = re.sub(
            r"(?i)\b(?:i know lol|part 1 was|part 2 was|part 3 was|part 4 of the same box)\b",
            "",
            text,
        )
        text = re.sub(r"(?i)\b(?:upvote|downvote|karma|tldr|tl;dr)\b", "", text)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        words = text.split()
        # Fall back to deep technical synthesis if summary is too brief or contains repetitive canned boilerplate
        if (
            len(words) < min_words or article_extractor._is_generic_canned(text)
        ) and entry:
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

    def _generate_executive_directive(
        self, entry: Entry | None, vector: str | None = None
    ) -> str:
        """Synthesize tailored, context-specific executive directives for AI ecosystem categories."""
        if not entry:
            return "Review the latest AI developments and evaluate strategic alignment with organizational automation priorities."

        t = entry.title or ""
        t_clean = self._clean_title(t)
        match = re.search(
            r"\b(DeepSeek|Qwen|Llama|Mistral|OpenAI|Anthropic|Claude|Gemini|vLLM|Ollama|SGLang|Nvidia|TSMC|Apple|Meta|Google|Microsoft|Blackwell|Groq|Cerebras|Krutrim|Falcon)\b",
            t,
            re.I,
        )
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

        cat = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )
        title_l = t.lower()

        # AI Hardware & Compute
        if any(
            k in title_l
            for k in (
                "nvidia",
                "gpu",
                "tpu",
                "blackwell",
                "h100",
                "b200",
                "amd",
                "rocm",
                "cerebras",
                "groq",
                "silicon",
                "semiconductor",
                "tsmc",
                "asml",
                "datacenter",
                "hbm",
            )
        ):
            return f"Review infrastructure compute quotas with cloud providers; assess {subj} hardware efficiency benchmarks to reduce inference cost per token."
        # Autonomous Agents & Robotics
        elif any(
            k in title_l
            for k in (
                "agent",
                "swarm",
                "robot",
                "robotics",
                "embodied",
                "computer-use",
                "browser-use",
                "action model",
                "autogen",
                "crewai",
                "langgraph",
                "tool use",
                "mcp",
            )
        ):
            return f"Pilot {subj} agentic capabilities in sandboxed environments; enforce strict tool-execution schemas, rate limits, and human-in-the-loop validation."
        # Foundation Models
        elif cat == "ai_models" or any(
            k in title_l
            for k in (
                "model",
                "deepseek",
                "qwen",
                "llama",
                "claude",
                "gpt",
                "gemini",
                "mistral",
                "grok",
                "weights",
                "gguf",
            )
        ):
            return f"Benchmark {subj} model against current production baselines; evaluate token economics, quantization tradeoffs, and commercial license terms."
        # Trending GitHub repos
        elif cat == "github_trending" or "github" in (entry.url or ""):
            return f"Assess {subj} repository architecture and licensing (Apache/MIT); test deployment in an isolated staging environment before production integration."
        # AI Research & ArXiv
        elif cat == "ai_research" or "arxiv" in (entry.url or "") or "paper" in title_l:
            return f"Review research findings for {subj}; schedule ML engineering briefing to evaluate test-time compute scaling and algorithmic applicability."
        # Developer Tools & Inference Frameworks
        elif cat == "cyber_tools" or any(
            k in title_l
            for k in (
                "framework",
                "runtime",
                "sdk",
                "library",
                "tool",
                "engine",
                "inference",
                "rag",
                "vector",
                "vllm",
                "ollama",
                "sglang",
            )
        ):
            return f"Deploy {subj} runtime in a proof-of-concept environment; evaluate throughput gains, KV-cache memory efficiency, and API compatibility."
        # Sovereign AI
        elif any(
            k in title_l
            for k in (
                "sovereign",
                "national",
                "falcon",
                "kyutai",
                "tsmc",
                "france",
                "india",
                "japan",
                "germany",
                "china",
            )
        ):
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
            if any(
                k in t_lower
                for k in (
                    "deepseek",
                    "openai",
                    "anthropic",
                    "qwen",
                    "gemini",
                    "claude",
                    "vllm",
                    "ollama",
                    "llama",
                    "reasoning",
                    "breakthrough",
                    "sota",
                    "release",
                    "launch",
                    "open-source",
                    "open source",
                    "arxiv",
                    "paper",
                    "agent",
                    "hardware",
                    "nvidia",
                    "chip",
                )
            ):
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

            is_hardware = any(
                k in t_lower or k in s_lower
                for k in (
                    "nvidia",
                    "gpu",
                    "gpus",
                    "cuda",
                    "tpu",
                    "blackwell",
                    "h100",
                    "b200",
                    "h200",
                    "amd",
                    "rocm",
                    "cerebras",
                    "groq",
                    "silicon",
                    "semiconductor",
                    "tsmc",
                    "asml",
                    "tensor core",
                    "hardware",
                    "datacenter",
                    "data center",
                    "hbm",
                    "vram",
                    "rtx 4090",
                    "rtx 3090",
                    "apple silicon",
                    "m4",
                    "m5",
                    "npu",
                    "chip",
                    "chips",
                    "wafer",
                    "accelerator",
                    "inference chip",
                    "fp8",
                    "fp4",
                )
            )

            is_agent_robotics = any(
                k in t_lower or k in s_lower
                for k in (
                    "agent",
                    "agents",
                    "agentic",
                    "swarm",
                    "swarms",
                    "robot",
                    "robotics",
                    "embodied",
                    "humanoid",
                    "computer-use",
                    "computer use",
                    "browser-use",
                    "browser use",
                    "action model",
                    "autogen",
                    "crewai",
                    "langgraph",
                    "tool use",
                    "tool calling",
                    "mcp",
                    "multi-agent",
                    "vision-language-action",
                    "vla",
                    "autonomous workflow",
                    "operator",
                )
            )

            is_sovereign = (
                region
                in (
                    "china",
                    "south_asia",
                    "middle_east",
                    "nordic",
                    "europe",
                    "east_asia",
                )
                or country
                in (
                    "CN",
                    "HK",
                    "IN",
                    "IL",
                    "JP",
                    "KR",
                    "TW",
                    "AE",
                    "SG",
                    "DE",
                    "FR",
                    "NL",
                    "FI",
                    "SE",
                    "CH",
                    "CA",
                    "AU",
                    "GB",
                    "EU",
                )
                or any(
                    k in t_lower or k in s_lower
                    for k in (
                        "deepseek",
                        "qwen",
                        "falcon",
                        "mistral",
                        "kyutai",
                        "glm",
                        "baichuan",
                        "internlm",
                        "tii",
                        "sarvam",
                        "krutrim",
                        "sovereign",
                        "national ai",
                        "alicloud",
                        "alibaba",
                        "tsmc",
                        "asml",
                        "dfki",
                        "inria",
                        "kaist",
                        "riken",
                        "turing institute",
                        "iisc",
                    )
                )
            )

            is_research = (
                cat == "ai_research"
                or "arxiv" in (e.url or "").lower()
                or "arxiv" in t_lower
                or any(
                    k in t_lower
                    for k in (
                        "paper",
                        "preprint",
                        "benchmark",
                        "empirical",
                        "formalizing",
                        "scaling law",
                        "test-time compute",
                        "alignment",
                        "reasoning architecture",
                        "survey",
                    )
                )
            )

            is_model = cat == "ai_models" or any(
                k in t_lower
                for k in (
                    "foundation model",
                    "deepseek",
                    "qwen",
                    "llama",
                    "mistral",
                    "claude",
                    "gpt",
                    "gemini",
                    "weights",
                    "gguf",
                    "moe",
                    "mixture-of-experts",
                    "reasoning model",
                    "distill",
                    "fine-tune",
                    "70b",
                    "8b",
                    "7b",
                    "32b",
                    "671b",
                )
            )

            is_tool = cat == "cyber_tools" or any(
                k in t_lower
                for k in (
                    "vllm",
                    "ollama",
                    "sglang",
                    "llama.cpp",
                    "tensorrt",
                    "litellm",
                    "unsloth",
                    "axolotl",
                    "deepspeed",
                    "transformers",
                    "diffusers",
                    "torchtune",
                    "outlines",
                    "instructor",
                    "langchain",
                    "llamaindex",
                    "chromadb",
                    "qdrant",
                    "weaviate",
                    "milvus",
                    "eval harness",
                    "runtime",
                    "framework",
                    "library",
                    "sdk",
                    "toolkit",
                    "serving engine",
                    "rag pipeline",
                    "vector database",
                    "quantization",
                    "mlx",
                    "mlx-serve",
                    "open-webui",
                    "localai",
                )
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
                target_list.extend(candidates[: min_count - len(target_list)])
            if len(target_list) < min_count:
                fallback_candidates = [e for e in pool if e not in target_list]
                target_list.extend(fallback_candidates[: min_count - len(target_list)])

        fill_section(
            trending_repos,
            6,
            lambda e: (
                (e.category.value if hasattr(e.category, "value") else str(e.category))
                in ("github_trending", "ai_tech", "cyber_tools")
            ),
        )
        fill_section(
            ai_models_list,
            6,
            lambda e: (
                (e.category.value if hasattr(e.category, "value") else str(e.category))
                in ("ai_models", "ai_tech")
            ),
        )
        fill_section(
            ai_research_list,
            6,
            lambda e: (
                (e.category.value if hasattr(e.category, "value") else str(e.category))
                in ("ai_research", "ai_tech")
            ),
        )
        fill_section(
            ai_tools_list,
            6,
            lambda e: (
                (e.category.value if hasattr(e.category, "value") else str(e.category))
                in ("cyber_tools", "ai_tech")
            ),
        )
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
        overflow.sort(
            key=lambda e: e.analysis.threat_velocity if e.analysis else 0, reverse=True
        )
        overflow = overflow[:10]

        candidates_to_enrich = [e for e in all_dossier_entries + overflow if e]
        logger.info(
            f"Initiating deep autonomous extraction across all {len(candidates_to_enrich)} dossier stories..."
        )

        sem = asyncio.Semaphore(8)

        async def enrich_entry(entry: Entry):
            async with sem:
                try:
                    content = await article_extractor.extract_article_content(
                        entry, min_words=60
                    )
                    if content and len(content.split()) >= 30:
                        entry.summary = content
                except Exception as ex:
                    logger.debug(f"Web extraction skipped for {entry.title}: {ex}")

        if candidates_to_enrich:
            try:
                await asyncio.gather(
                    *[enrich_entry(e) for e in candidates_to_enrich],
                    return_exceptions=True,
                )
            except Exception:
                pass

        # Clean all titles and format summaries
        for item in all_dossier_entries:
            if item:
                item.title = self._clean_title(item.title)
                item.summary = self._clean_and_format_summary(
                    item.summary, entry=item, min_words=25, max_words=160
                )

        for item in overflow:
            item.title = self._clean_title(item.title)
            item.summary = self._clean_and_format_summary(
                item.summary, entry=item, min_words=20, max_words=120
            )

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
        """Delegate markdown rendering to NewspaperRenderer."""
        return self._renderer.render_markdown(
            entries=entries,
            categorized=categorized,
            edition_num=edition_num,
            generated_at=generated_at,
            window_hours=window_hours,
        )

    def _render_html(
        self,
        entries: list[Entry],
        categorized: dict[str, Any],
        edition_num: int,
        generated_at: datetime,
        window_hours: int,
        edition_id: str,
    ) -> str:
        """Delegate HTML broadsheet rendering to NewspaperRenderer."""
        return self._renderer.render_html(
            entries=entries,
            categorized=categorized,
            edition_num=edition_num,
            generated_at=generated_at,
            window_hours=window_hours,
            edition_id=edition_id,
        )

    def _render_pdf(
        self,
        pdf_path: Path,
        entries: list[Entry],
        categorized: dict[str, Any],
        edition_num: int,
        generated_at: datetime,
        window_hours: int,
    ) -> None:
        """Delegate 10-page broadsheet PDF compilation to NewspaperRenderer."""
        return self._renderer.render_pdf(
            pdf_path=pdf_path,
            entries=entries,
            categorized=categorized,
            edition_num=edition_num,
            generated_at=generated_at,
            window_hours=window_hours,
        )


_newspaper_service = NewspaperService()
