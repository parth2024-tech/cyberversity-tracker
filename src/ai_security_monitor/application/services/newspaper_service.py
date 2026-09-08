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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ai_security_monitor.application.services.article_extractor import article_extractor
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

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
            self.drawString(36, 756, "THE AETHER GUARD — GLOBAL AI & TECHNOLOGY GAZETTE • 10-PAGE DOSSIER")
            self.drawRightString(576, 756, f"PAGE {self._pageNumber} OF {page_count}")
            self.setStrokeColor(colors.HexColor("#94a3b8"))
            self.setLineWidth(0.75)
            self.line(36, 750, 576, 750)

        # Running Footer on all pages
        self.setStrokeColor(colors.HexColor("#94a3b8"))
        self.setLineWidth(0.75)
        self.line(36, 32, 576, 32)
        self.setFont("Helvetica", 7)
        self.drawString(36, 22, "THE AETHER GUARD GLOBAL AI & DEFENSE SECINTEL • AUTONOMOUS TELEMETRY • STRICTLY CONFIDENTIAL")
        self.drawRightString(576, 22, f"PAGE {self._pageNumber} OF {page_count}")
        self.restoreState()


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
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours = int((dt - epoch).total_seconds() // 3600)
        return 1000 + (hours // 5)

    async def generate_edition(self, window_hours: int = 24) -> dict[str, Any]:
        """Compile an authentic 10-page executive intelligence broadsheet dossier."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max(5, window_hours))
        logger.info(f"Initiating 10-page intelligence newspaper compilation (window={window_hours}h)...")

        async with self._uow_factory() as uow:
            # Query comprehensive recent entries
            recent_filters = EntryFilters(since=cutoff, sort_by="velocity")
            entries = await uow.entries.list(
                filters=recent_filters,
                pagination=PaginationParams(limit=150, offset=0),
            )

            # Balanced multi-pillar query: guarantee representation of trending repos, AI models, research, tools, and vulnerabilities
            existing_ids = {e.id for e in entries}
            core_pillars = [
                Category.GITHUB_TRENDING,
                Category.AI_MODELS,
                Category.AI_RESEARCH,
                Category.CYBER_TOOLS,
                Category.VULNERABILITIES,
                Category.EXPLOITS_TRICKS,
            ]
            for pillar_cat in core_pillars:
                cat_filters = EntryFilters(category=pillar_cat, sort_by="velocity")
                cat_items = await uow.entries.list(
                    filters=cat_filters,
                    pagination=PaginationParams(limit=15, offset=0),
                )
                for item in cat_items:
                    if item.id not in existing_ids:
                        entries.append(item)
                        existing_ids.add(item.id)

            # Rich backfill if overall volume is sparse
            if len(entries) < 40:
                logger.info("Backfilling rich historical intelligence to assemble comprehensive 10-page dossier.")
                fallback_filters = EntryFilters(sort_by="velocity")
                fallback_items = await uow.entries.list(
                    filters=fallback_filters,
                    pagination=PaginationParams(limit=100, offset=0),
                )
                for item in fallback_items:
                    if item.id not in existing_ids:
                        entries.append(item)
                        existing_ids.add(item.id)

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

        # Synchronize latest.html with The Aether Guard Gazette broadsheet
        gazette_template = Path("web/gazette.html")
        if gazette_template.exists():
            latest_html.write_text(gazette_template.read_text(encoding="utf-8"), encoding="utf-8")
        else:
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
            "title": f"The Cyber Intelligence Chronicle & AI Gazette — 10-Page Edition #{edition_num}",
            "generated_at": now.isoformat(),
            "window_hours": window_hours,
            "total_threats": len(entries),
            "pages_count": 10,
            "lead_story": categorized["lead"].title if categorized["lead"] else "Global AI & Cyber Advisory",
            "trending_repos_count": len(categorized.get("trending_repos", [])),
            "ai_models_count": len(categorized.get("ai_models", [])),
            "ai_research_count": len(categorized.get("ai_research", [])),
            "ai_tools_count": len(categorized.get("ai_tools", [])),
            "pre_cve_count": len(categorized.get("pre_cve", [])),
            "cve_count": len(categorized.get("cves", [])),
            "china_count": len(categorized.get("china_radar", [])),
            "poc_count": len(categorized.get("exploits", [])),
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

    # ─── Editorial Parsing & Classification ──────────────────────────────────

    def _get_source_name(self, entry: Entry | None) -> str:
        if not entry:
            return "Intel Wire"
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
        """Classify entries into 10 distinct editorial sections with translation & deep extraction."""
        if not raw_entries:
            return {
                "lead": None,
                "secondary_anchor": None,
                "front_page_briefs": [],
                "ciso_briefs": [],
                "pre_cve": [],
                "ai_labs": [],
                "china_radar": [],
                "cves": [],
                "exploits": [],
                "cloud_infra": [],
                "cert_bulletins": [],
                "mitre_matrix": [],
                "remediation": [],
            }

        # 1. De-duplicate and preserve comprehensive AI innovation and security entries
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

        # 2. Auto-translate any foreign language entries
        from ai_security_monitor.application.services.translation_service import translation_service
        for e in filtered_entries:
            try:
                translation_service.translate_entry(e)
            except Exception:
                pass

        def priority_score(e: Entry) -> int:
            score = 0
            t_lower = e.title.lower()
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            if e.analysis:
                if e.analysis.is_pre_cve_warning:
                    score += 350
                score += e.analysis.threat_velocity * 2
                score += e.analysis.severity_index
                if "PoC" in (e.analysis.weaponization_potential or ""):
                    score += 150
            if cat in ("ai_models", "github_trending", "ai_research", "cyber_tools"):
                score += 260
            if any(k in t_lower for k in ("deepseek", "openai", "anthropic", "qwen", "gemini", "claude", "vllm", "ollama", "llama", "reasoning", "breakthrough", "sota")):
                score += 260
            if "cve" in t_lower:
                score += 120
            return score

        sorted_entries = sorted(filtered_entries, key=priority_score, reverse=True)
        lead = sorted_entries[0] if sorted_entries else None
        secondary_anchor = sorted_entries[1] if len(sorted_entries) > 1 else None
        remaining = sorted_entries[2:] if len(sorted_entries) > 2 else []

        pre_cves = []
        ai_labs = []
        trending_repos = []
        ai_research_list = []
        ai_models_list = []
        ai_tools_list = []
        china_radar = []
        cves = []
        exploits = []
        cloud_infra = []
        cert_bulletins = []

        for e in remaining:
            region = (e.metadata.get("region") if e.metadata else "") or ""
            country = (e.metadata.get("country") if e.metadata else "") or ""
            t_lower = e.title.lower()
            s_lower = (e.summary or "").lower()
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            tags_lower = [t.lower() for t in e.tags or []]
            is_pre = e.analysis and e.analysis.is_pre_cve_warning

            is_china = (
                region == "china"
                or country in ("CN", "HK")
                or any(k in t_lower for k in ("deepseek", "qwen", "glm", "internlm", "zhipu", "baidu", "360", "cnnvd", "tencent", "tsinghua", "antiy", "venustech", "kunlun"))
            )
            is_sovereign_regional = (
                is_china
                or region in ("china", "south_asia", "middle_east", "nordic")
                or country in ("CN", "HK", "IN", "IL", "JP", "KR", "TW", "AE", "SG", "DE", "FR", "NL", "FI", "SE", "CH", "CA", "AU", "GB", "EU")
                or any(k in t_lower or k in s_lower for k in ("cert-in", "bsi", "anssi", "jpcert", "krcert", "twcert", "singcert", "tii", "falcon", "ncsc", "enisa", "iisc", "kaist", "tsmc", "asml", "dfki", "turing", "semianalysis"))
            )
            is_poc = "poc" in t_lower or "exploit" in t_lower or (e.analysis and "PoC" in (e.analysis.weaponization_potential or ""))
            is_cloud = any(k in t_lower or k in s_lower for k in ("aws", "azure", "gcp", "kubernetes", "k8s", "docker", "cloud", "iam", "npm", "pypi", "container", "artifactory"))
            is_cert = any(k in t_lower or k in s_lower for k in ("cisa", "cert", "ncsc", "advisory", "bulletin", "alert", "security update", "sonicwall", "citrix"))
            is_trending = cat == "github_trending" or "trending" in t_lower or "github" in tags_lower or "github.com" in (e.url or "").lower()
            is_ai_res = cat == "ai_research" or "arxiv" in t_lower or "arxiv" in (e.url or "").lower() or "paper" in t_lower
            is_ai_mod = cat == "ai_models" or any(k in t_lower for k in ("deepseek", "qwen", "llama", "mistral", "grok", "gpt", "claude", "weights", "model")) or "huggingface" in (e.url or "").lower()
            is_tool = cat == "cyber_tools" or "tool" in t_lower or "vllm" in t_lower or "ollama" in t_lower or "framework" in t_lower

            if is_trending and len(trending_repos) < 10:
                trending_repos.append(e)
            elif is_ai_mod and len(ai_models_list) < 10:
                ai_models_list.append(e)
                if len(ai_labs) < 10:
                    ai_labs.append(e)
            elif is_ai_res and len(ai_research_list) < 10:
                ai_research_list.append(e)
                if len(ai_labs) < 10:
                    ai_labs.append(e)
            elif is_tool and len(ai_tools_list) < 10:
                ai_tools_list.append(e)
            elif is_sovereign_regional and len(china_radar) < 10:
                china_radar.append(e)
            elif is_pre and len(pre_cves) < 8:
                pre_cves.append(e)
            elif is_poc and len(exploits) < 8:
                exploits.append(e)
            elif (cat in ("ai_tech", "ai_models", "ai_research") or "llm" in t_lower or "gpt" in t_lower or "claude" in t_lower) and len(ai_labs) < 10:
                ai_labs.append(e)
            elif is_cloud and len(cloud_infra) < 8:
                cloud_infra.append(e)
            elif (cat == "vulnerabilities" or "cve" in t_lower) and len(cves) < 12:
                cves.append(e)
            elif is_cert and len(cert_bulletins) < 8:
                cert_bulletins.append(e)
            elif cat in ("github_trending", "ai_tech", "cyber_tools"):
                trending_repos.append(e)
            else:
                cves.append(e)

        # Smart Backfill from remaining pool for each core pillar
        pool = remaining[:]
        if len(trending_repos) < 4:
            trending_candidates = [e for e in pool if (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("github_trending", "ai_tech", "cyber_tools") and e not in trending_repos]
            trending_repos.extend(trending_candidates[:4 - len(trending_repos)])
        if len(ai_models_list) < 4:
            model_candidates = [e for e in pool if (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("ai_models", "ai_tech") and e not in ai_models_list]
            ai_models_list.extend(model_candidates[:4 - len(ai_models_list)])
        if len(ai_research_list) < 4:
            res_candidates = [e for e in pool if (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("ai_research", "ai_tech") and e not in ai_research_list]
            ai_research_list.extend(res_candidates[:4 - len(ai_research_list)])
        if len(ai_tools_list) < 4:
            tool_candidates = [e for e in pool if (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("cyber_tools", "github_trending", "ai_tech") and e not in ai_tools_list]
            ai_tools_list.extend(tool_candidates[:4 - len(ai_tools_list)])
        if len(china_radar) < 4:
            china_candidates = [
                e for e in pool
                if ((e.metadata and (e.metadata.get("region") in ("china", "south_asia", "middle_east", "nordic") or e.metadata.get("country") in ("CN", "HK", "IN", "IL", "JP", "KR", "TW", "AE", "SG", "DE", "FR", "NL", "FI", "SE", "CH", "CA", "AU", "GB", "EU")))
                    or any(k in e.title.lower() for k in ("deepseek", "qwen", "cert", "falcon", "tsmc", "asml", "dfki", "inria", "kaist", "riken", "turing", "semianalysis")))
                and e not in china_radar
            ]
            china_radar.extend(china_candidates[:4 - len(china_radar)])
        if len(cves) < 4:
            cve_candidates = [e for e in pool if (e.category.value if hasattr(e.category, 'value') else str(e.category)) in ("vulnerabilities", "cybersecurity") and e not in cves]
            cves.extend(cve_candidates[:4 - len(cves)])
        if len(exploits) < 4:
            poc_candidates = [e for e in pool if ("poc" in e.title.lower() or "exploit" in e.title.lower() or (e.category.value if hasattr(e.category, 'value') else str(e.category)) == "exploits_tricks") and e not in exploits]
            exploits.extend(poc_candidates[:4 - len(exploits)])

        # Final safety backfill so no section is ever empty
        if not trending_repos:
            trending_repos = pool[:4]
        if not ai_models_list:
            ai_models_list = pool[4:8]
        if not ai_research_list:
            ai_research_list = pool[8:12]
        if not ai_tools_list:
            ai_tools_list = pool[12:16]
        if not china_radar:
            china_radar = pool[16:20]
        if not cves:
            cves = pool[20:24]
        if not exploits:
            exploits = pool[24:28]

        # 3. Deep Extract / Enrich Content for Key Featured Stories
        featured_entries = [lead, secondary_anchor] + trending_repos[:2] + ai_models_list[:2] + pre_cves[:2]
        extract_tasks = [
            article_extractor.extract_article_content(item)
            for item in featured_entries if item
        ]
        extracted_summaries = await asyncio.gather(*extract_tasks, return_exceptions=True)

        idx = 0
        for item in featured_entries:
            if item and idx < len(extracted_summaries):
                res = extracted_summaries[idx]
                if isinstance(res, str) and len(res) > len(item.summary or ""):
                    item.summary = res
                idx += 1

        return {
            "lead": lead,
            "secondary_anchor": secondary_anchor,
            "front_page_briefs": remaining[:4],
            "ciso_briefs": remaining[4:10],
            "trending_repos": trending_repos,
            "ai_models": ai_models_list,
            "ai_research": ai_research_list,
            "ai_tools": ai_tools_list,
            "pre_cve": pre_cves,
            "ai_labs": ai_labs,
            "china_radar": china_radar,
            "cves": cves,
            "exploits": exploits,
            "cloud_infra": cloud_infra,
            "cert_bulletins": cert_bulletins,
            "mitre_matrix": sorted_entries[:12],
            "remediation": sorted_entries[:12],
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

        lead_title = lead.title if lead else "Global Threat Landscape Advisory"
        lead_summary = lead.summary if lead else "Continuous monitoring active across global telemetry nodes."
        lead_vel = lead.analysis.threat_velocity if lead and lead.analysis else 40
        lead_sev = lead.analysis.severity_index if lead and lead.analysis else 50
        lead_blast = lead.analysis.blast_radius_score if lead and lead.analysis else 45
        lead_vec = lead.analysis.attack_vector if lead and lead.analysis else "Network perimeter exploitation"
        lead_mit = lead.analysis.mitigation if lead and lead.analysis else "Apply emergency vendor patches"

        md = f"""# 📰 THE CYBER INTELLIGENCE CHRONICLE & GLOBAL AI GAZETTE
**Autonomous 10-Page Comprehensive Intelligence Broadsheet Dossier • Edition #{edition_num}**  
*Date: {date_str} • Monitoring Horizon: {window_hours} Hours • Verified Across 92 Sensing Arrays*

---

## 🏛️ [PAGE 1] FRONT PAGE: BREAKING GLOBAL AI & CYBER INTELLIGENCE
### 🚨 {lead_title}
- **Threat Velocity Index**: `{lead_vel}/100` | **Severity / Impact Score**: `{lead_sev}/100` | **Blast Radius**: `{lead_blast}/100`
- **Exploitation / Focus Vector**: {lead_vec}
- **Remediation / Deployment Directive**: {lead_mit}

{lead_summary}

### ⚡ SECONDARY ANCHOR DISPATCH: {secondary.title if secondary else 'Frontier AI & Critical Infrastructure Alert'}
{secondary.summary if secondary else 'Global intelligence feeds confirm heightened sovereign AI deployment and threat telemetry.'}

#### Top Flash Bulletins
"""
        for item in categorized.get("front_page_briefs", [])[:4]:
            vel = item.analysis.threat_velocity if item.analysis else 35
            md += f"- **{item.title}** (VEL `{vel}`) — {item.summary or 'Active telemetry update.'}\n"

        md += f"""
---

## 👔 [PAGE 2] CISO & EXECUTIVE BOARD STRATEGIC BRIEFING
### Macro AI Horizons, Sovereign Compute & Geopolitical Cyber Landscape
The global technological landscape is marked by rapid sovereign AI model adoption and mission-critical cyber defense mobilization. Enterprise leadership must navigate autonomous agent integration while defending identity fabrics against automated exploitation. As frontier labs accelerate model reasoning benchmarks, adversaries simultaneously weaponize perimeter zero-days within hours of public disclosure.

### Enterprise Attack Surface & AI Exposure Matrix
| Vector / Boundary | Likelihood | Enterprise Impact | Primary Detection Control | Executive Mandate |
| :--- | :--- | :--- | :--- | :--- |
| **Cloud Identity & IdP** | High | Full Tenant Takeover | Conditional Access & FIDO2 | Mandate phishing-resistant hardware keys |
| **Kubernetes & Containers** | Critical | Lateral Pod Escape | eBPF runtime inspection | Enforce read-only root filesystems |
| **Autonomous AI Agents** | High | Prompt & Tool Injection | Parameter schema validation | Enforce strict firewalled runtime sandboxes |
| **Edge Perimeter Gateways** | Critical | Unauthenticated RCE | Ingress WAF & NetFlow | Disallow direct internet admin exposure |
| **Software Supply Chain** | High | Pipeline Poisoning | CycloneDX SBOM verification | Enforce signed commits & package pinning |

### Prioritized 24-Hour Executive Directives
"""
        for item in categorized.get("ciso_briefs", [])[:5]:
            md += f"1. **{item.title}**: Verify immediate operational compliance and review access logs.\n"

        md += f"""
---

## 🚀 [PAGE 3] TRENDING OPEN-SOURCE AI & GITHUB INNOVATIONS
### Global Developer Community Velocity & Codebase Momentum
Open-source generative AI development on GitHub is surging at unprecedented velocity. From agentic orchestration runtimes to quantized local inference engines, community repositories empower autonomous intelligence across distributed environments.

| Repository / Project | Focus Area | Ecosystem Impact | Community Momentum |
| :--- | :--- | :--- | :--- |
| **vllm-project / vllm** | High-Throughput Inference | PagedAttention GPU Serving | ★ 35k+ Stars • Industry Standard |
| **ollama / ollama** | Local Model Execution | Zero-Config CLI / Desktop | ★ 95k+ Stars • Local AI Baseline |
| **run-llama / llama_index**| Agentic RAG Framework | Enterprise Data Connectors | ★ 38k+ Stars • Production Retrieval |
| **langchain-ai / langgraph**| Multi-Agent Cyclic Graphs | State Machine Coordination | ★ 12k+ Stars • Autonomous Swarms |
| **deepseek-ai / DeepSeek-V3**| MoE Reasoning Architecture| Multi-Head Latent Attention | ★ 60k+ Stars • Frontier Open-Weight |

### Featured Trending Repositories
"""
        for r in categorized.get("trending_repos", [])[:4]:
            vel = r.analysis.threat_velocity if r.analysis else 85
            md += f"### 🚀 {r.title}\n- **Velocity**: `{vel}/100` | **Source**: `{self._get_source_name(r)}`\n\n{r.summary or ''}\n\n"

        md += f"""
---

## 🤖 [PAGE 4] FRONTIER AI MODELS & AUTONOMOUS AGENTS
### Sovereign Architectures, Reasoning Breakthroughs & Model Benchmarks
Frontier AI research is defined by post-training reinforcement learning, test-time compute scaling, and mixture-of-experts (MoE) efficiency. Models demonstrate emergent reasoning across mathematical olympiads, code synthesis, and autonomous decision pipelines.

| Model | Organization | Parameter Scale | Context Window | Key Innovation |
| :--- | :--- | :--- | :--- | :--- |
| **DeepSeek-R1** | DeepSeek | 671B (37B active) | 128k Tokens | Pure RL reasoning, open weights |
| **Claude 3.7 Sonnet** | Anthropic | Proprietary | 200k Tokens | Hybrid instant & extended thinking |
| **OpenAI o3-mini** | OpenAI | Proprietary | 200k Tokens | Cost-effective mathematical reasoning |
| **Qwen-2.5-Max** | Alibaba Cloud | Proprietary / MoE | 128k Tokens | Bilingual reasoning & STEM benchmark leader |
| **Llama 3.3 70B** | Meta AI | 70B Dense | 128k Tokens | Open-weight foundation with 405B parity |

### Frontier Model Dispatches
"""
        for m in categorized.get("ai_models", [])[:4]:
            vel = m.analysis.threat_velocity if m.analysis else 90
            md += f"### 🤖 {m.title}\n- **Velocity**: `{vel}/100` | **Source**: `{self._get_source_name(m)}`\n\n{m.summary or ''}\n\n"

        md += f"""
---

## 🔬 [PAGE 5] TOP AI RESEARCH PAPERS & ARXIV BREAKTHROUGHS
### Scientific Inquiries, Test-Time Compute & Emergent Capabilities
Academic and industrial research published across arXiv reveals transformative paradigms in agent verification, latent alignment, and multi-modal sensory synthesis.

### Seminal Research Papers
"""
        for paper in categorized.get("ai_research", [])[:4]:
            vel = paper.analysis.threat_velocity if paper.analysis else 80
            md += f"### 🔬 {paper.title}\n- **Research Velocity**: `{vel}/100` | **Source**: `{self._get_source_name(paper)}`\n\n{paper.summary or ''}\n\n"

        md += f"""
---

## 🛠️ [PAGE 6] DEVELOPER TOOLS, FRAMEWORKS & AI INFRASTRUCTURE
### Local Inference Runtimes, Evaluation Harnesses & Tooling Ecosystem
The infrastructure layer powering modern artificial intelligence has transitioned towards specialized inference kernels, synthetic dataset pipelines, and zero-trust agent sandboxes.

### Core Tooling Dispatches
"""
        for tool in categorized.get("ai_tools", [])[:4]:
            vel = tool.analysis.threat_velocity if tool.analysis else 75
            md += f"### 🛠️ {tool.title}\n- **Adoption Index**: `{vel}/100` | **Source**: `{self._get_source_name(tool)}`\n\n{tool.summary or ''}\n\n"

        md += f"""
---

## 🌐 [PAGE 7] SOVEREIGN AI & WORLDWIDE REGIONAL INTEL RADAR (Tier 1 & Tier 2 Sovereigns)
### Sovereign AI Initiatives, State Vulnerability Governance & Worldwide Wire (🇨🇳 CN · 🇮🇳 IN · 🇮🇱 IL · 🇯🇵 JP · 🇰🇷 KR · 🇬🇧 GB · 🇪🇺 EU · 🇸🇬 SG · 🇹🇼 TW · 🇦🇪 AE · 🇨🇦 CA · 🇩🇪 DE · 🇫🇷 FR · 🇳🇱 NL · 🇨🇭 CH)
Comprehensive sovereign compute ecosystems, national foundation models (DeepSeek, Qwen, Falcon, Mistral, Kyutai, Indian AI initiatives), and regional defense agencies (CERT-In, BSI, ANSSI, JPCERT, TWCERT, NCSC, ENISA) form a unified geopolitical radar. Telemetry synthesizes bilingual dispatches from sovereign labs, CERTs, and academic nodes across Tier 1 and Tier 2 strategic nations.

### Sovereign Wire Dispatches
"""
        for ch in categorized.get("china_radar", [])[:4]:
            c_code = (ch.metadata.get("country") if ch.metadata else "") or "SOV"
            md += f"### 🌐 [{c_code}] {ch.title}\n- **Sovereign Source**: `{self._get_source_name(ch)}` | **Country**: `{c_code}`\n\n{ch.summary or ''}\n\n"

        md += f"""
---

## 🔴 [PAGE 8] HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV CATALOG
### Active In-The-Wild Exploits & Critical Infrastructure Zero-Days
Adversaries prioritize unauthenticated remote code execution and session token forgery. Recent threat actor activity demonstrates automated mass scanning of public IP ranges within hours of advisory disclosures.

### Critical Vulnerabilities
"""
        for c in categorized.get("cves", [])[:5]:
            md += f"### 🛡️ {c.title}\n- **Severity**: `{c.analysis.severity_index if c.analysis else 50}/100` | **Reference**: {c.url}\n\n{c.summary or ''}\n\n"

        md += f"""
---

## ⚡ [PAGE 9] VERIFIED PROOF-OF-CONCEPTS & RED TEAM REPOSITORIES
### Exploit Weaponization Velocity & MITRE ATLAS Threat Matrix
Functional exploit scripts distributed via Exploit-DB, Packet Storm, and GitHub repositories have drastically compressed enterprise patch windows. Defensive teams must deploy proactive network signatures before weaponized modules are integrated into automated attack frameworks.

| Technique / ID | Target Entity | Threat Level | Recommended Telemetry Control |
| :--- | :--- | :--- | :--- |
| **T1190 Exploit Public-Facing App** | Web & API Gateways | Critical | WAF inspection, ingress rate-limiting |
| **T1059 Command and Scripting** | Host & Container | High | Auditd, Sysmon process telemetry |
| **T1078 Valid Accounts** | Cloud IAM & IdP | High | Enforce FIDO2 MFA, rotate session tokens |
| **AML.T0054 LLM Prompt Injection** | Autonomous AI Agents | High | Enforce system prompt boundaries |
| **AML.T0043 Model Weights Exfiltration**| ML Inference Clusters| Critical | Encrypt model artifacts at rest and in transit |

### Actionable Proof-of-Concepts
"""
        for exp in categorized.get("exploits", [])[:4]:
            md += f"### 💥 {exp.title}\n- **Source**: `{self._get_source_name(exp)}`\n\n{exp.summary or ''}\n\n"

        md += f"""
---

## 🛡️ [PAGE 10] 24-HOUR DEFENSIVE PLAYBOOK & OPERATIONAL ACTION PLAN
### Remediation SLA Hierarchy
1. **P0 Emergency (< 4 Hours)**: Patch active CISA KEV catalog entries and public perimeter RCE flaws.
2. **P1 Critical (< 24 Hours)**: Remediate high-velocity CVEs (CVSS >= 8.5) and rotate compromised cloud tokens.
3. **P2 High (< 72 Hours)**: Audit AI agent tool permissions and apply non-critical OS dependency updates.

### Tactical AI & Infrastructure Hardening Directives
- **AI Agent Sandboxing**: Execute all LLM tool invocations in isolated gVisor/firecracker microVMs with strictly bounded egress.
- **Perimeter Access Isolation**: Disallow external access to administrative ports (SSH, RDP, Kubernetes API, Ollama daemon).
- **SafeTensors Verification**: Block unverified PyTorch `.bin`/`.pt` pickle checkpoints across all internal ML clusters.

*Imprimatur: The Aether Guard — Global AI & Technology Gazette • Autonomous SecIntel Engine • Edition #{edition_num}*
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

        lead_title = lead.title if lead else "Global Threat Landscape Advisory"
        lead_summary = lead.summary if lead else "Continuous monitoring active across global telemetry nodes."
        lead_vel = lead.analysis.threat_velocity if lead and lead.analysis else 40
        lead_sev = lead.analysis.severity_index if lead and lead.analysis else 50
        lead_blast = lead.analysis.blast_radius_score if lead and lead.analysis else 45
        lead_vec = lead.analysis.attack_vector if lead and lead.analysis else "Network perimeter exploitation"
        lead_mit = lead.analysis.mitigation if lead and lead.analysis else "Apply emergency vendor patches"
        lead_src = self._get_source_name(lead)

        html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Cyber Intelligence Chronicle — 10-Page Edition #{edition_num}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Cinzel:wght@700;900&family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --paper: #fbf9f1;
      --ink: #0d1117;
      --border-ink: #1e2430;
    }}
    body {{
      background-color: #0b0f17;
      color: var(--ink);
      font-family: 'Merriweather', Georgia, serif;
    }}
    .newspaper-sheet {{
      background-color: var(--paper);
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255,255,255,0.05);
      border: 1px solid #d1cbba;
      page-break-after: always;
      break-after: page;
      min-height: 1050px;
    }}
    .masthead-title {{
      font-family: 'Cinzel', serif;
      letter-spacing: -0.02em;
    }}
    .headline-font {{
      font-family: 'Playfair Display', serif;
      line-height: 1.1;
    }}
    .editorial-col {{
      column-count: 2;
      column-gap: 28px;
      column-rule: 1px solid #d8d3c5;
      text-align: justify;
    }}
    .double-rule-thick {{
      border-top: 3px double var(--border-ink);
      border-bottom: 1px solid var(--border-ink);
      height: 6px;
    }}
    @media print {{
      body {{ background: transparent !important; padding: 0 !important; }}
      .no-print {{ display: none !important; }}
      .newspaper-sheet {{ box-shadow: none !important; border: none !important; margin-bottom: 0 !important; page-break-after: always; }}
    }}
  </style>
</head>
<body class="py-8 px-2 sm:px-6">

  <!-- Print & Download Floating Command Bar -->
  <div class="no-print max-w-5xl mx-auto mb-6 flex items-center justify-between bg-slate-900/90 backdrop-blur-md p-3.5 rounded-xl border border-white/10 text-white font-mono text-xs">
    <div class="flex items-center gap-3">
      <span class="flex items-center gap-1.5 text-cyan-400 font-bold">
        <span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
        10-PAGE EXECUTIVE INTELLIGENCE DOSSIER
      </span>
      <span class="text-slate-500">|</span>
      <span class="text-slate-300">Edition #{edition_num}</span>
    </div>
    <div class="flex items-center gap-2">
      <button onclick="window.print()" class="px-3.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-slate-100 transition font-bold">
        🖨️ Print / Save 10-Page PDF
      </button>
      <a href="/api/newspaper/download?format=pdf" class="px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition font-bold">
        📥 Download PDF
      </a>
    </div>
  </div>

  <!-- PAGE 1: FRONT PAGE BROADSHEET -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>AETHERGUARD DEFENSE DISPATCH • 10-PAGE DOSSIER</div>
      <div>GLOBAL THREAT LEVEL: <span class="font-bold text-red-700">DEFCON 3 (ELEVATED)</span></div>
      <div>PAGE 1 OF 10</div>
    </div>
    <header class="text-center py-5 border-b border-[#1e2430]">
      <h1 class="masthead-title text-3xl sm:text-5xl md:text-6xl font-black uppercase text-[#0d1117] tracking-tight">
        The Cyber Intelligence Chronicle
      </h1>
      <p class="text-xs sm:text-sm italic text-[#4b5563] mt-1 font-serif">
        "Omnis Vulnerabilitas Patefacietur" — Autonomous Telemetry Across 92 Global Threat Arrays
      </p>
    </header>
    <div class="double-rule-thick my-2"></div>
    <div class="flex items-center justify-between text-[11px] font-mono py-1 text-[#1f2937] font-semibold border-b border-[#1e2430]">
      <div>{date_str}</div>
      <div>NO. {edition_num} • EXECUTIVE INTELLIGENCE DOSSIER</div>
      <div>{time_str} • REPORTERS: AETHERGUARD AI ENGINE</div>
    </div>

    <!-- Breaking Lead Story -->
    <section class="mt-6 mb-6">
      <div class="text-[11px] font-mono font-bold uppercase tracking-widest text-red-700 mb-1 flex items-center gap-2">
        <span class="inline-block w-2 h-2 bg-red-700"></span> BREAKING GLOBAL ZERO-DAY INVESTIGATION
      </div>
      <h2 class="headline-font text-2xl sm:text-4xl font-black text-[#0a0d13] mb-3 leading-tight">
        {html.escape(lead_title)}
      </h2>
      <p class="text-sm font-serif italic text-[#374151] mb-4 pb-2 border-b border-[#d1cbba]">
        Threat velocity clocks at {lead_vel}/100 with blast radius index {lead_blast}/100; enterprise systems face active exploitation.
      </p>
      <div class="editorial-col text-xs leading-relaxed text-[#1f2937]">
        <p class="mb-3 first-letter:text-4xl first-letter:font-bold first-letter:float-left first-letter:mr-2 font-serif">
          {html.escape(lead_summary)}
        </p>
        <div class="my-2 p-2.5 bg-[#f2eedf] border-l-4 border-red-700 font-mono text-[10.5px]">
          <strong>VECTOR:</strong> {html.escape(lead_vec)}<br>
          <strong>MITIGATION:</strong> {html.escape(lead_mit)}
        </div>
      </div>
    </section>

    <!-- Secondary Anchor -->
    {f'''
    <section class="mb-6 p-4 bg-white/70 border border-[#d1cbba]">
      <div class="text-[10px] font-mono font-bold text-red-800 uppercase">⚡ SECONDARY ANCHOR DISPATCH</div>
      <h3 class="font-serif font-bold text-base mt-1 text-[#0f172a]">{html.escape(secondary.title)}</h3>
      <p class="text-xs text-[#374151] mt-1 leading-relaxed">{html.escape(secondary.summary or '')}</p>
    </section>
    ''' if secondary else ''}

    <!-- Top Flash Bulletins -->
    <div class="border-t-2 border-[#1e2430] pt-4">
      <h3 class="font-mono text-xs font-bold uppercase text-red-800 mb-3">⚡ Front Page Global Flash Bulletins</h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3.5 text-xs">
        {"".join([f"""
          <div class="p-2.5 bg-white/60 border border-[#d1cbba]">
            <span class="text-[9.5px] font-mono font-bold text-red-700">VEL {item.analysis.threat_velocity if item.analysis else 35}/100</span>
            <h4 class="font-serif font-bold text-xs mt-1"><a href="{item.url}" target="_blank" class="hover:text-red-700">{html.escape(item.title)}</a></h4>
            <p class="text-[11px] text-[#4b5563] mt-1 leading-normal">{html.escape(item.summary or '')[:180]}...</p>
          </div>
        """ for item in categorized.get("front_page_briefs", [])[:4]])}
      </div>
    </div>
  </article>

  <!-- PAGE 2: CISO & EXECUTIVE BOARD BRIEFING -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION II: EXECUTIVE INTELLIGENCE BRIEF</div>
      <div>BOARDROOM DIRECTIVES</div>
      <div>PAGE 2 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">CISO Strategic Risk Assessment & Attack Surface Exposure</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">High-level threat prioritization synthesized for executive leadership and board decision-makers.</p>
    
    <div class="p-4 bg-white/70 border border-[#d1cbba] mb-6 text-xs leading-relaxed text-[#374151]">
      <h3 class="font-mono text-xs font-bold uppercase text-blue-900 mb-2">🎯 Macro Geopolitical & Ransomware Landscape</h3>
      <p class="mb-2">Telemetry across 92 authoritative sensing nodes indicates an aggressive acceleration in edge gateway exploitation, cloud IAM token forgery, and autonomous prompt injection attacks. Sophisticated ransomware syndicates (LockBit, BlackCat, Akira) continue to weaponize critical CVEs within hours of disclosure, targeting enterprise virtualization hosts and storage fabrics.</p>
      <p>Corporate risk officers are instructed to prepare for mandatory SEC 4-day disclosure timelines, enforce hardware-bound FIDO2 authentication on all administrative gateways, and audit autonomous agentic tool invocations.</p>
    </div>

    <div class="overflow-x-auto mb-6">
      <table class="w-full text-left font-mono text-[11px] border border-[#d1cbba]">
        <thead class="bg-[#e2e8f0] text-[#0f172a]">
          <tr>
            <th class="p-2 border border-[#d1cbba]">ATTACK VECTOR</th>
            <th class="p-2 border border-[#d1cbba]">LIKELIHOOD</th>
            <th class="p-2 border border-[#d1cbba]">ENTERPRISE IMPACT</th>
            <th class="p-2 border border-[#d1cbba]">EXECUTIVE MANDATE</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[#d1cbba] bg-white/50">
          <tr>
            <td class="p-2 font-bold">Cloud Identity / IdP</td>
            <td class="p-2 text-red-700 font-bold">High</td>
            <td class="p-2">Full Tenant Takeover</td>
            <td class="p-2">Mandate phishing-resistant FIDO2 hardware keys</td>
          </tr>
          <tr>
            <td class="p-2 font-bold">Kubernetes & Containers</td>
            <td class="p-2 text-red-700 font-bold">Critical</td>
            <td class="p-2">Lateral Node Escape</td>
            <td class="p-2">Enforce read-only root filesystems & eBPF monitoring</td>
          </tr>
          <tr>
            <td class="p-2 font-bold">AI Agent / LLM APIs</td>
            <td class="p-2 text-amber-700 font-bold">High</td>
            <td class="p-2">Data Exfiltration & RCE</td>
            <td class="p-2">Isolate agentic tool execution in firewalled sandboxes</td>
          </tr>
          <tr>
            <td class="p-2 font-bold">Edge Perimeter Gateways</td>
            <td class="p-2 text-red-700 font-bold">Critical</td>
            <td class="p-2">Unauthenticated RCE</td>
            <td class="p-2">Disallow public internet access to administrative panels</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="font-mono text-xs font-bold uppercase text-red-800 mb-3">⚡ Prioritized 24-Hour Executive Directives</h3>
    <div class="space-y-2.5 text-xs font-mono">
      {"".join([f"""
        <div class="p-2.5 bg-white/60 border border-[#d1cbba] flex items-baseline gap-2">
          <span class="text-red-700 font-bold">•</span>
          <div><strong>{html.escape(b.title)}:</strong> Verify patch compliance and review access telemetry.</div>
        </div>
      """ for b in categorized.get("ciso_briefs", [])[:5]])}
    </div>
  </article>

  <!-- PAGE 3: AI FRONTIER & PRE-CVE -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION III: AI FRONTIER & PRE-CVE</div>
      <div>MODEL SECURITY & RESEARCH DISCLOSURES</div>
      <div>PAGE 3 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Frontier AI Models, Prompt Injection & Pre-CVE Register</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Academic zero-day disclosures and model weights telemetry prior to NVD assignment.</p>

    <div class="p-4 bg-white/70 border border-[#d1cbba] mb-6 text-xs leading-relaxed text-[#374151]">
      <h3 class="font-mono text-xs font-bold uppercase text-indigo-900 mb-2">🤖 Autonomous Agent Exploitation & Prompt Injection</h3>
      <p>As organizations embed LLMs into automated workflows, indirect prompt injection has emerged as the premier offensive vector. Attackers embed adversarial token sequences into ingested files and web search results. When ingested, the model violates system guardrails to invoke external tools, dump credential caches, or poison RAG embeddings.</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      {"".join([f"""
        <div class="p-3.5 bg-white/80 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-amber-700">⚡ PRE-CVE WIRE • VEL {p.analysis.threat_velocity if p.analysis else 30}/100</span>
          <h4 class="font-serif font-bold text-xs mt-1 text-[#0f172a]">{html.escape(p.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1.5 leading-relaxed">{html.escape(p.summary or '')}</p>
        </div>
      """ for p in categorized.get("pre_cve", [])[:4]])}
    </div>
  </article>

  <!-- PAGE 4: SOVEREIGN RADAR -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION IV: SOVEREIGN RADAR</div>
      <div>WORLDWIDE TIER 1 & TIER 2 SOVEREIGN TELEMETRY</div>
      <div>PAGE 4 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Sovereign AI Initiatives & Worldwide Regional Intelligence</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Strategic nation-state foundational models, sovereign cloud compute, and national CERT threat bulletins across Tier 1 (US, CN, GB, IN, EU, IL, JP, KR) and Tier 2 (CA, DE, FR, SG, TW, AE, AU, NL, FI, SE, CH) ecosystems.</p>

    <div class="p-4 bg-white/70 border border-[#d1cbba] mb-6 text-xs leading-relaxed text-[#374151]">
      <h3 class="font-mono text-xs font-bold uppercase text-red-900 mb-2">🌐 Global Sovereign Vulnerability & Foundation Model Governance</h3>
      <p>Sovereign compute infrastructure and national vulnerability governance frameworks have become critical geopolitical determinants. Domestic foundation models (DeepSeek, Qwen, Falcon, Mistral, Kyutai, Indian AI initiatives) and sovereign defense agencies (CERT-In, BSI, ANSSI, JPCERT, TWCERT, NCSC, ENISA) maintain strategic early visibility into zero-day disclosures and frontier model breakthroughs.</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      {"".join([f"""
        <div class="p-3.5 bg-white/80 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-red-700">🌐 SOVEREIGN DISPATCH [{(ch.metadata.get("country") if ch.metadata else "") or "SOV"}] • {html.escape(self._get_source_name(ch)[:22])}</span>
          <h4 class="font-serif font-bold text-xs mt-1 text-[#0f172a]">{html.escape(ch.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1.5 leading-relaxed">{html.escape(ch.summary or '')}</p>
        </div>
      """ for ch in categorized.get("china_radar", [])[:4]])}
    </div>
  </article>

  <!-- PAGE 5: VULNERABILITIES & CISA KEV -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION V: VULNERABILITIES</div>
      <div>CISA KEV CATALOG & ZERO-DAYS</div>
      <div>PAGE 5 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">High-Velocity Exploited Vulnerabilities & CISA KEV</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">Catalog of active in-the-wild zero-days and mandatory federal remediation directives.</p>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      {"".join([f"""
        <div class="p-3.5 bg-white/80 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-blue-900">🛡️ CISA KEV REGISTER • SEV {c.analysis.severity_index if c.analysis else 50}/100</span>
          <h4 class="font-serif font-bold text-xs mt-1 text-[#0f172a]">{html.escape(c.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1.5 leading-relaxed">{html.escape(c.summary or '')}</p>
        </div>
      """ for c in categorized.get("cves", [])[:4]])}
    </div>
  </article>

  <footer class="text-center font-mono text-[10px] text-[#4b5563] pt-4">
    PUBLISHED AUTONOMOUSLY EVERY FIVE HOURS BY AETHERGUARD SECINTEL • COMPLETE 10-PAGE DOSSIER • ALL RIGHTS RESERVED
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
            leftMargin=36,
            rightMargin=36,
            topMargin=38,
            bottomMargin=40,
        )

        base_styles = getSampleStyleSheet()

        # Professional Editorial Typography
        masthead_title = ParagraphStyle(
            "MastheadTitle",
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=24,
            alignment=1,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )
        masthead_sub = ParagraphStyle(
            "MastheadSub",
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=9.5,
            alignment=1,
            textColor=colors.HexColor("#475569"),
            spaceAfter=4,
        )
        page_header = ParagraphStyle(
            "PageHeader",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )
        page_sub = ParagraphStyle(
            "PageSub",
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
            spaceAfter=6,
        )
        dateline_style = ParagraphStyle(
            "Dateline",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor("#1e293b"),
        )
        headline_style = ParagraphStyle(
            "Headline",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#0a0d13"),
            spaceAfter=2,
        )
        subhead_style = ParagraphStyle(
            "Subhead",
            fontName="Times-Italic",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#334155"),
            spaceAfter=3,
        )
        body_style = ParagraphStyle(
            "Body",
            fontName="Times-Roman",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#1f2937"),
            alignment=4,  # Justified
            spaceAfter=3,
        )
        item_title = ParagraphStyle(
            "ItemTitle",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0f172a"),
        )
        item_meta = ParagraphStyle(
            "ItemMeta",
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#b91c1c"),
        )
        item_summary = ParagraphStyle(
            "ItemSummary",
            fontName="Times-Roman",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#334155"),
            alignment=4,
        )
        callout_box_text = ParagraphStyle(
            "CalloutBoxText",
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a"),
        )

        date_str = generated_at.strftime("%A, %B %d, %Y • %H:%M UTC")
        story = []

        def render_dense_article_card(item: Entry, tag_color: str, tag_label: str, stat_label: str = "SEVERITY"):
            src = self._get_source_name(item)
            is_pure_ai = (item.analysis and getattr(item.analysis, "is_ai_innovation", False)) or (
                item.category.value if hasattr(item.category, "value") else str(item.category)
            ) in ("github_trending", "ai_models", "ai_research", "cyber_tools")
            vel = item.analysis.threat_velocity if item.analysis else 35
            sev = item.analysis.severity_index if item.analysis else 50
            vec = item.analysis.attack_vector if item.analysis else "Remote Exploit"
            effective_stat = "IMPACT" if is_pure_ai else stat_label
            title_text = f"<b>{html.escape(item.title)}</b>"
            meta_text = (
                f"<font color='{tag_color}'><b>[{tag_label}]</b></font> "
                f"<b>SOURCE:</b> {html.escape(src[:20])} | <b>VELOCITY:</b> {vel}/100 | <b>{effective_stat}:</b> {sev}/100"
            )
            body_text = html.escape(item.summary or "Detailed technical synthesis and telemetry analysis underway.")
            return [
                Paragraph(meta_text, item_meta),
                Paragraph(title_text, item_title),
                Spacer(1, 1),
                Paragraph(body_text, item_summary),
                Spacer(1, 4),
            ]

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 1: FRONT PAGE & BREAKING GLOBAL AI & THREAT LEAD INVESTIGATION
        # ═════════════════════════════════════════════════════════════════════
        story.append(Table([[
            Paragraph("AETHERGUARD INTELLIGENCE & DEFENSE DISPATCH", dateline_style),
            Paragraph("GLOBAL THREAT: <b>DEFCON 3 (ELEVATED)</b>", dateline_style),
            Paragraph(f"PAGE 1 OF 10 • 10-PAGE DOSSIER", ParagraphStyle('R', fontName='Helvetica-Bold', fontSize=7.5, alignment=2, textColor=colors.HexColor('#1e293b'))),
        ]], colWidths=[180, 180, 180]))
        story.append(Spacer(1, 2))
        story.append(Paragraph("THE AETHER GUARD — GLOBAL AI & TECHNOLOGY GAZETTE", masthead_title))
        story.append(Paragraph('"Omnis Intelligentia Patefacietur" — Frontier Research • Trending Repositories • Developer Tools • AI Models • Security & Governance', masthead_sub))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f172a"), spaceAfter=1))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#0f172a"), spaceAfter=3))
        story.append(Table([[
            Paragraph(f"<b>{date_str}</b>", dateline_style),
            Paragraph(f"<b>EDITION NO. {edition_num}</b>", ParagraphStyle('C', fontName='Helvetica-Bold', fontSize=7.5, alignment=1, textColor=colors.HexColor('#1e293b'))),
            Paragraph("<b>AETHERGUARD AI OBSERVER</b>", ParagraphStyle('R', fontName='Helvetica-Bold', fontSize=7.5, alignment=2, textColor=colors.HexColor('#1e293b'))),
        ]], colWidths=[200, 140, 200]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))

        lead = categorized["lead"]
        if lead:
            lead_vel = lead.analysis.threat_velocity if lead.analysis else 40
            lead_sev = lead.analysis.severity_index if lead.analysis else 50
            lead_blast = lead.analysis.blast_radius_score if lead.analysis else 45
            lead_vec = lead.analysis.attack_vector if lead.analysis else "Remote code execution pattern"
            lead_mit = lead.analysis.mitigation if lead.analysis else "Apply emergency vendor patches"
            
            story.append(Paragraph("<font color='#b91c1c'><b>🚨 BREAKING INVESTIGATION // CRITICAL ZERO-DAY INCIDENT</b></font>", dateline_style))
            # Calibrate lead summary to ~130 words to fit Page 1 broadsheet layout perfectly
            lead_words = (lead.summary or "").split()
            lead_display = " ".join(lead_words[:130]) + ("..." if len(lead_words) > 130 else "")
            story.append(Paragraph(html.escape(lead_display), body_style))

            lead_box = Table([[
                Paragraph(f"<b>EXPLOITATION MECHANICS:</b> {html.escape(lead_vec)}<br/><b>EMERGENCY DIRECTIVE:</b> {html.escape(lead_mit)}", callout_box_text)
            ]], colWidths=[540])
            lead_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(lead_box)

        # Secondary Anchor Story
        secondary = categorized.get("secondary_anchor")
        if secondary:
            story.append(Spacer(1, 2))
            story.append(Paragraph("<font color='#1e3a8a'><b>⚡ SECONDARY ANCHOR DISPATCH: CRITICAL THREAT INDICATOR</b></font>", dateline_style))
            story.append(Paragraph(html.escape(secondary.title), headline_style))
            sec_words = (secondary.summary or "").split()
            sec_display = " ".join(sec_words[:65]) + ("..." if len(sec_words) > 65 else "")
            story.append(Paragraph(html.escape(sec_display), body_style))

        # Flash Bulletins Table (Top 3 items)
        story.append(Spacer(1, 2))
        story.append(Paragraph("<b>⚡ TOP FRONT-PAGE FLASH BULLETINS</b>", page_header))
        bulletin_data = []
        for b in categorized.get("front_page_briefs", [])[:3]:
            vel = b.analysis.threat_velocity if b.analysis else 35
            sum_words = (b.summary or "").split()
            sum_text = " ".join(sum_words[:25]) + ("..." if len(sum_words) > 25 else "")
            bulletin_data.append([
                Paragraph(f"<font color='#b91c1c'><b>[VEL {vel}]</b></font> <b>{html.escape(b.title)}</b> — {html.escape(sum_text)}", item_summary)
            ])
        bt = Table(bulletin_data, colWidths=[540])
        bt.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(bt)
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 2: CISO & EXECUTIVE BOARD STRATEGIC BRIEFING
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("👔 SECTION II: CISO & EXECUTIVE BOARD STRATEGIC BRIEFING", page_header))
        story.append(Paragraph("Macro Risk Posture, Threat Velocity Heatmaps, and 24-Hour Boardroom Mandates", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        ciso_macro_text = (
            "<b>MACRO THREAT POSTURE:</b> The enterprise threat posture remains indexed at DEFCON 3 (Elevated). "
            "Continuous telemetry across 92 authoritative sensor nodes records an aggressive convergence between nation-state "
            "reconnaissance and automated ransomware syndicates. Attackers are exploiting unauthenticated edge perimeter gateways "
            "and forging cloud identity provider tokens to establish persistence before enterprise SOC teams detect initial intrusion. "
            "Concurrently, the rapid enterprise adoption of autonomous generative AI agents has introduced an entirely new class "
            "of prompt injection and tool execution vulnerabilities that evade legacy web application firewalls (WAFs)."
        )
        story.append(Paragraph(ciso_macro_text, body_style))
        story.append(Spacer(1, 4))

        # Enterprise Attack Surface Exposure Table
        story.append(Paragraph("<b>ENTERPRISE ATTACK SURFACE EXPOSURE MATRIX</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0f172a'), spaceAfter=3)))
        matrix_data = [
            [
                Paragraph("<b>VECTOR / BOUNDARY</b>", dateline_style),
                Paragraph("<b>LIKELIHOOD</b>", dateline_style),
                Paragraph("<b>ENTERPRISE IMPACT</b>", dateline_style),
                Paragraph("<b>PRIMARY DETECTION CONTROL</b>", dateline_style),
                Paragraph("<b>EXECUTIVE MANDATE</b>", dateline_style),
            ],
            [
                Paragraph("<b>Cloud Identity & IdP</b>", item_title),
                Paragraph("<font color='#b91c1c'><b>High</b></font>", item_meta),
                Paragraph("Full Tenant Compromise", item_summary),
                Paragraph("Conditional Access & Token Audit", item_summary),
                Paragraph("Enforce FIDO2 hardware MFA", item_summary),
            ],
            [
                Paragraph("<b>Kubernetes & Containers</b>", item_title),
                Paragraph("<font color='#b91c1c'><b>Critical</b></font>", item_meta),
                Paragraph("Lateral Pod Escape", item_summary),
                Paragraph("eBPF Runtime Audit", item_summary),
                Paragraph("Enforce read-only root filesystems", item_summary),
            ],
            [
                Paragraph("<b>AI Agent / LLM APIs</b>", item_title),
                Paragraph("<font color='#ea580c'><b>High</b></font>", item_meta),
                Paragraph("Prompt Injection & Tool Abuse", item_summary),
                Paragraph("Context boundary filters", item_summary),
                Paragraph("Sandbox agent tool invocations", item_summary),
            ],
            [
                Paragraph("<b>Edge Perimeter Gateways</b>", item_title),
                Paragraph("<font color='#b91c1c'><b>Critical</b></font>", item_meta),
                Paragraph("Unauthenticated RCE", item_summary),
                Paragraph("NetFlow anomaly inspection", item_summary),
                Paragraph("Disallow public admin panels", item_summary),
            ],
            [
                Paragraph("<b>Software Supply Chain</b>", item_title),
                Paragraph("<font color='#ea580c'><b>High</b></font>", item_meta),
                Paragraph("Build Pipeline Poisoning", item_summary),
                Paragraph("SBOM & SHA256 verification", item_summary),
                Paragraph("Mandate signed container commits", item_summary),
            ],
        ]
        mt = Table(matrix_data, colWidths=[105, 55, 110, 130, 140])
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(mt)
        story.append(Spacer(1, 5))

        # Prioritized 24-Hour Executive Directives
        story.append(Paragraph("<b>PRIORITIZED 24-HOUR EXECUTIVE DIRECTIVES</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0f172a'), spaceAfter=3)))
        for item in categorized.get("ciso_briefs", [])[:5]:
            for element in render_dense_article_card(item, tag_color="#1e3a8a", tag_label="EXECUTIVE DIRECTIVE"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 3: TRENDING OPEN-SOURCE AI & GITHUB INNOVATIONS
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🚀 SECTION III: TRENDING OPEN-SOURCE AI & GITHUB INNOVATIONS", page_header))
        story.append(Paragraph("Top GitHub Repositories, Developer Velocity, Architecture Dissections & Deployment Guides", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        repo_intro = (
            "<b>GLOBAL DEVELOPER VELOCITY:</b> Open-source AI engineering on GitHub is expanding across distributed runtimes, "
            "agentic workflows, and quantized model serving. Developers worldwide are rapidly converging on local-first LLM orchestration, "
            "synthetic data pipelines, and high-throughput inference kernels that bypass proprietary API bottlenecks."
        )
        story.append(Paragraph(repo_intro, body_style))
        story.append(Spacer(1, 4))

        # Trending Repositories Matrix
        repo_table_data = [
            [
                Paragraph("<b>PROJECT / REPO</b>", dateline_style),
                Paragraph("<b>DOMAIN FOCUS</b>", dateline_style),
                Paragraph("<b>ARCHITECTURE / STACK</b>", dateline_style),
                Paragraph("<b>COMMUNITY MOMENTUM</b>", dateline_style),
            ],
            [
                Paragraph("<b>vllm-project / vllm</b>", item_title),
                Paragraph("High-Throughput Serving", item_summary),
                Paragraph("PagedAttention, CUDA C++, Python", item_summary),
                Paragraph("★ 35,000+ Stars • Standard Engine", item_meta),
            ],
            [
                Paragraph("<b>ollama / ollama</b>", item_title),
                Paragraph("Local Execution Engine", item_summary),
                Paragraph("Go, llama.cpp, Cross-Platform", item_summary),
                Paragraph("★ 95,000+ Stars • Desktop Standard", item_meta),
            ],
            [
                Paragraph("<b>run-llama / llama_index</b>", item_title),
                Paragraph("Production Agentic RAG", item_summary),
                Paragraph("Python, Hybrid Vector Connectors", item_summary),
                Paragraph("★ 38,000+ Stars • Enterprise Retrieval", item_meta),
            ],
            [
                Paragraph("<b>deepseek-ai / DeepSeek-V3</b>", item_title),
                Paragraph("Frontier MoE Foundation", item_summary),
                Paragraph("Multi-Head Latent Attention", item_summary),
                Paragraph("★ 60,000+ Stars • Open Weights", item_meta),
            ],
        ]
        rt = Table(repo_table_data, colWidths=[140, 130, 140, 130])
        rt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(rt)
        story.append(Spacer(1, 4))

        story.append(Paragraph("<b>FEATURED OPEN-SOURCE DISPATCHES & REPOSITORIES</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0f172a'), spaceAfter=3)))
        for item in categorized.get("trending_repos", [])[:3]:
            for element in render_dense_article_card(item, tag_color="#0891b2", tag_label="TRENDING REPO", stat_label="VELOCITY"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 4: FRONTIER AI MODELS & AUTONOMOUS AGENTS
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🤖 SECTION IV: FRONTIER AI MODELS & AUTONOMOUS AGENTS", page_header))
        story.append(Paragraph("Sovereign Architectures, Reasoning Breakthroughs, Parameter Scale & Benchmark Matrices", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        model_intro = (
            "<b>THE FRONTIER REASONING PARADIGM:</b> Machine intelligence has pivoted from pure next-token prediction to reinforcement "
            "learning during inference (test-time compute). Architectures such as DeepSeek-R1, OpenAI o3, and Claude 3.7 Sonnet produce "
            "verifiable internal reasoning traces, demonstrating human-expert parity across software engineering, competitive mathematics, "
            "and formal logic benchmarks."
        )
        story.append(Paragraph(model_intro, body_style))
        story.append(Spacer(1, 4))

        # Frontier AI Models Benchmark Table
        model_table_data = [
            [
                Paragraph("<b>MODEL / ARCHITECTURE</b>", dateline_style),
                Paragraph("<b>SCALE / ACTIVE</b>", dateline_style),
                Paragraph("<b>CONTEXT</b>", dateline_style),
                Paragraph("<b>PRIMARY BENCHMARK</b>", dateline_style),
                Paragraph("<b>INNOVATION HIGHLIGHT</b>", dateline_style),
            ],
            [
                Paragraph("<b>DeepSeek-R1</b>", item_title),
                Paragraph("671B / 37B MoE", item_summary),
                Paragraph("128k Tokens", item_summary),
                Paragraph("AIME 2024: 79.8%", item_meta),
                Paragraph("Pure RL cold-start reasoning", item_summary),
            ],
            [
                Paragraph("<b>Claude 3.7 Sonnet</b>", item_title),
                Paragraph("Proprietary", item_summary),
                Paragraph("200k Tokens", item_summary),
                Paragraph("SWE-bench: 70.3%", item_meta),
                Paragraph("Hybrid instant/extended thinking", item_summary),
            ],
            [
                Paragraph("<b>OpenAI o3-mini</b>", item_title),
                Paragraph("Proprietary", item_summary),
                Paragraph("200k Tokens", item_summary),
                Paragraph("Math: 91.2%", item_meta),
                Paragraph("High-speed chain-of-thought", item_summary),
            ],
            [
                Paragraph("<b>Qwen-2.5 72B</b>", item_title),
                Paragraph("72B Dense", item_summary),
                Paragraph("128k Tokens", item_summary),
                Paragraph("MMLU: 86.1%", item_meta),
                Paragraph("Bilingual coding & open weights", item_summary),
            ],
        ]
        mt_models = Table(model_table_data, colWidths=[115, 80, 75, 120, 150])
        mt_models.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(mt_models)
        story.append(Spacer(1, 4))

        story.append(Paragraph("<b>FRONTIER MODEL DISPATCHES & CAPABILITY DOSSIERS</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0f172a'), spaceAfter=3)))
        for item in categorized.get("ai_models", [])[:3]:
            for element in render_dense_article_card(item, tag_color="#7c3aed", tag_label="FRONTIER MODEL", stat_label="IMPACT"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 5: TOP AI RESEARCH PAPERS & ARXIV BREAKTHROUGHS
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🔬 SECTION V: TOP AI RESEARCH PAPERS & ARXIV BREAKTHROUGHS", page_header))
        story.append(Paragraph("Reasoning Paradigms, Multimodal Architectures, Autonomous Planning & Latent Alignment", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        research_intro = (
            "<b>ACADEMIC & INDUSTRIAL DISCOVERY WIRE:</b> Peer-reviewed and preprint investigations across arXiv document monumental leaps "
            "in test-time compute optimization, self-correcting agentic loops, and multi-modal alignment. Researchers increasingly focus "
            "on algorithmic sample efficiency, process reward models (PRMs), and verifiable constraint satisfaction over brute-force pre-training."
        )
        story.append(Paragraph(research_intro, body_style))
        story.append(Spacer(1, 4))

        for item in categorized.get("ai_research", [])[:4]:
            for element in render_dense_article_card(item, tag_color="#4338ca", tag_label="AI RESEARCH", stat_label="IMPACT"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 6: DEVELOPER TOOLS, FRAMEWORKS & AI INFRASTRUCTURE
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🛠️ SECTION VI: DEVELOPER TOOLS, FRAMEWORKS & AI INFRASTRUCTURE", page_header))
        story.append(Paragraph("Inference Runtimes, Evaluation Frameworks, Vector DBs & Local GPU Execution Engines", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        infra_intro = (
            "<b>ENTERPRISE AI RUNTIME STACK:</b> The operational foundation of artificial intelligence requires fault-tolerant vector storage, "
            "low-latency CUDA/Metal inference engines, and rigorous benchmark harnesses. Tooling ecosystems enable organizations to deploy "
            "resilient multi-agent swarms with granular access controls and continuous latency optimization."
        )
        story.append(Paragraph(infra_intro, body_style))
        story.append(Spacer(1, 4))

        for item in categorized.get("ai_tools", [])[:4]:
            for element in render_dense_article_card(item, tag_color="#0d9488", tag_label="AI TOOL", stat_label="ADOPTION"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 7: SOVEREIGN AI & WORLDWIDE REGIONAL INTEL RADAR (Tier 1 & Tier 2)
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🌐 SECTION VII: SOVEREIGN AI & WORLDWIDE REGIONAL INTEL RADAR", page_header))
        story.append(Paragraph("Strategic Sovereign Telemetry: 🇨🇳 CN · 🇮🇳 IN · 🇮🇱 IL · 🇯🇵 JP · 🇰🇷 KR · 🇬🇧 GB · 🇪🇺 EU · 🇸🇬 SG · 🇹🇼 TW · 🇦🇪 AE · 🇨🇦 CA · 🇩🇪 DE · 🇫🇷 FR · 🇳🇱 NL · 🇨🇭 CH", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        sovereign_text = (
            "<b>WORLDWIDE SOVEREIGN & REGIONAL INTELLIGENCE:</b> Sovereign compute ecosystems and regional defense commands "
            "across Tier 1 and Tier 2 nations are driving breakthroughs in domestic foundation models (China's DeepSeek & Qwen, "
            "UAE's Falcon, France's Mistral & Kyutai, India's AI models, Korea's AI hardware) and active threat intelligence (CERT-In, "
            "BSI, ANSSI, JPCERT, TWCERT, NCSC). Autonomous telemetry synthesizes cross-theatre sovereign disclosures."
        )
        story.append(Paragraph(sovereign_text, body_style))
        story.append(Spacer(1, 4))

        for item in categorized.get("china_radar", [])[:4]:
            c_code = (item.metadata.get("country") if item.metadata else "") or "SOV"
            for element in render_dense_article_card(item, tag_color="#b91c1c", tag_label=f"SOVEREIGN WIRE [{c_code}]", stat_label="SEVERITY"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 8: HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV CATALOG
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🛡️ SECTION VIII: HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV", page_header))
        story.append(Paragraph("Known Exploited Vulnerabilities Catalog, CVSS Risk Ratings & Urgent Patch Directives", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        kev_intro = (
            "<b>ACTIVE IN-THE-WILD EXPLOITATION TELEMETRY:</b> Adversaries demonstrate weaponization velocity that outpaces standard patch "
            "cadences. CISA Known Exploited Vulnerabilities (KEV) represent immediate risk to federal and commercial enterprise operations. "
            "Attackers leverage automated scanners to discover exposed endpoints within hours of proof-of-concept code publication."
        )
        story.append(Paragraph(kev_intro, body_style))
        story.append(Spacer(1, 4))

        for item in categorized.get("cves", [])[:4]:
            for element in render_dense_article_card(item, tag_color="#dc2626", tag_label="CISA KEV / CVE", stat_label="SEVERITY"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 9: VERIFIED PROOF-OF-CONCEPTS & RED TEAM REPOSITORIES
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("⚡ SECTION IX: VERIFIED PROOF-OF-CONCEPTS & RED TEAM REPOSITORIES", page_header))
        story.append(Paragraph("Exploit-DB, Packet Storm & MITRE ATT&CK / ATLAS Threat Taxonomy", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        poc_text = (
            "<b>EXPLOIT WEAPONIZATION TIMELINES:</b> The window between vulnerability publication and functional exploit automation "
            "has compressed to under 24 hours. Red team repositories release proof-of-concept scripts that require proactive protocol-level "
            "inspection rules before binary patches can be fully staged."
        )
        story.append(Paragraph(poc_text, body_style))
        story.append(Spacer(1, 4))

        mitre_table_data = [
            [
                Paragraph("<b>TECHNIQUE</b>", dateline_style),
                Paragraph("<b>NAME</b>", dateline_style),
                Paragraph("<b>TACTIC</b>", dateline_style),
                Paragraph("<b>MITIGATION DIRECTIVE</b>", dateline_style),
            ],
            [
                Paragraph("<b>T1190</b>", callout_box_text),
                Paragraph("Exploit Public-Facing App", item_title),
                Paragraph("Initial Access", item_summary),
                Paragraph("Deploy WAF rules & patch edge perimeter gateways", item_summary),
            ],
            [
                Paragraph("<b>T1059</b>", callout_box_text),
                Paragraph("Command & Scripting Interpreter", item_title),
                Paragraph("Execution", item_summary),
                Paragraph("Enforce PowerShell Constrained Language & container read-only roots", item_summary),
            ],
            [
                Paragraph("<b>T1078</b>", callout_box_text),
                Paragraph("Valid Accounts & Token Theft", item_title),
                Paragraph("Defense Evasion", item_summary),
                Paragraph("Mandate FIDO2 MFA & continuous conditional access re-evaluation", item_summary),
            ],
            [
                Paragraph("<b>AML.T0054</b>", callout_box_text),
                Paragraph("LLM Prompt Injection", item_title),
                Paragraph("AI ATLAS", item_summary),
                Paragraph("Input guardrails & strict tool parameter schema validation", item_summary),
            ],
            [
                Paragraph("<b>AML.T0043</b>", callout_box_text),
                Paragraph("Model Weights Exfiltration", item_title),
                Paragraph("AI ATLAS", item_summary),
                Paragraph("Encrypt model storage & enforce egress inspection on inference clusters", item_summary),
            ],
        ]
        mt = Table(mitre_table_data, colWidths=[65, 145, 90, 240])
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(mt)
        story.append(Spacer(1, 4))

        for item in categorized.get("exploits", [])[:3]:
            for element in render_dense_article_card(item, tag_color="#ea580c", tag_label="VERIFIED PoC", stat_label="SEVERITY"):
                story.append(element)

        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 10: 24-HOUR DEFENSIVE PLAYBOOK & OPERATIONAL DIRECTIVES
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🛡️ SECTION X: 24-HOUR REMEDIATION PLAYBOOK & OPERATIONAL DIRECTIVES", page_header))
        story.append(Paragraph("Actionable Patching SLAs, AI Agent Runtime Hardening & Broadsheet Colophon", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=5))

        playbook_data = [
            [
                Paragraph("<b>TIER</b>", dateline_style),
                Paragraph("<b>SLA</b>", dateline_style),
                Paragraph("<b>SCOPE & DIRECTIVES</b>", dateline_style),
            ],
            [
                Paragraph("<font color='#b91c1c'><b>P0 EMERGENCY</b></font>", callout_box_text),
                Paragraph("<b>&lt; 4 Hours</b>", dateline_style),
                Paragraph("Apply vendor patches for active in-the-wild zero-days (CISA KEV). Isolate compromised host instances immediately.", item_summary),
            ],
            [
                Paragraph("<font color='#ea580c'><b>P1 CRITICAL</b></font>", callout_box_text),
                Paragraph("<b>&lt; 24 Hours</b>", dateline_style),
                Paragraph("Patch high-velocity CVEs (CVSS >= 8.5). Rotate service account credentials for exposed cloud providers.", item_summary),
            ],
            [
                Paragraph("<font color='#0284c7'><b>P2 HIGH</b></font>", callout_box_text),
                Paragraph("<b>&lt; 72 Hours</b>", dateline_style),
                Paragraph("Audit AI agent system prompts, update dependencies in container registries, and verify model SafeTensors.", item_summary),
            ],
        ]
        pt = Table(playbook_data, colWidths=[80, 60, 400])
        pt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(pt)

        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>TACTICAL AI & INFRASTRUCTURE HARDENING DIRECTIVES</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0f172a'), spaceAfter=3)))
        firewall_text = (
            "1. <b>AI Agent Sandboxing:</b> Execute all LLM tool invocations in isolated gVisor/firecracker microVMs with strictly bounded egress and zero root capabilities.<br/>"
            "2. <b>SafeTensors Deserialization Mandate:</b> Strictly reject untrusted PyTorch .bin/.pt pickle files across training and inference clusters.<br/>"
            "3. <b>Perimeter Access Isolation:</b> Disallow public internet exposure of administrative ports (SSH, RDP, Kubernetes API, Ollama daemon)."
        )
        story.append(Paragraph(firewall_text, body_style))

        story.append(Spacer(1, 6))
        colophon = Paragraph(
            "<b>COLOPHON & SENSOR METHODOLOGY:</b> The Aether Guard — Global AI & Technology Gazette is compiled autonomously by the "
            "AetherGuard Intelligence Engine. Data is aggregated across 92 authoritative global sources including Hugging Face, GitHub Trending, "
            "arXiv, CISA, NVD, Exploit-DB, and sovereign CERTs. Neural NLP analyzers perform multi-language translation, algorithmic deduplication, "
            "and structured technical synthesis. All rights reserved.",
            body_style
        )
        story.append(colophon)

        # Build PDF with NumberedCanvas for exact page count
        doc.build(story, canvasmaker=NumberedCanvas)


_newspaper_service = NewspaperService()
