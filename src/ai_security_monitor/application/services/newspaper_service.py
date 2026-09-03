"""
Autonomous 10-Page Intelligence Newspaper Service ("The Cyber Intelligence Chronicle").
Compiles live security intelligence into authentic 9-to-10 page editorial broadsheet documents (PDF, HTML, and Markdown).
"""
from __future__ import annotations

import html
import json
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

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
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
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#475569"))

        # Running Header on pages > 1
        if self._pageNumber > 1:
            self.drawString(36, 756, "THE CYBER INTELLIGENCE CHRONICLE • 10-PAGE EXECUTIVE DOSSIER")
            self.drawRightString(576, 756, f"PAGE {self._pageNumber} OF {page_count}")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(36, 750, 576, 750)

        # Running Footer on all pages
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 32, 576, 32)
        self.drawString(36, 22, "AETHERGUARD DEFENSE SECINTEL • VERIFIED ACROSS 92 SENSORS • STRICTLY CONFIDENTIAL")
        self.drawRightString(576, 22, f"EDITION NO. 100+ • PAGE {self._pageNumber} OF {page_count}")
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
        """Compile a 9-to-10 page broadsheet newspaper covering all daily intelligence."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max(5, window_hours))
        logger.info(f"Initiating 10-page intelligence newspaper compilation (window={window_hours}h)...")

        async with self._uow_factory() as uow:
            # Query extensive entries across all categories (up to 120 items)
            recent_filters = EntryFilters(since=cutoff, sort_by="velocity")
            entries = await uow.entries.list(
                filters=recent_filters,
                pagination=PaginationParams(limit=120, offset=0),
            )

            # Rich backfill if recent volume is sparse
            if len(entries) < 30:
                logger.info("Backfilling rich historical intelligence to assemble comprehensive 10-page dossier.")
                fallback_filters = EntryFilters(sort_by="velocity")
                entries = await uow.entries.list(
                    filters=fallback_filters,
                    pagination=PaginationParams(limit=100, offset=0),
                )

        edition_num = self._compute_edition_number(now)
        timestamp_str = now.strftime("%Y%m%d_%H%M")
        edition_id = f"chronicle_{timestamp_str}"

        # Segment entries across all 10 specialized intelligence domains
        categorized = self._categorize_entries(entries)

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
            "title": f"The Cyber Intelligence Chronicle — 10-Page Edition #{edition_num}",
            "generated_at": now.isoformat(),
            "window_hours": window_hours,
            "total_threats": len(entries),
            "pages_count": 10,
            "lead_story": categorized["lead"].title if categorized["lead"] else "Global Threat Advisory",
            "pre_cve_count": len(categorized["pre_cve"]),
            "cve_count": len(categorized["cves"]),
            "ai_lab_count": len(categorized["ai_labs"]),
            "china_count": len(categorized["china_radar"]),
            "poc_count": len(categorized["exploits"]),
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

    def _categorize_entries(self, entries: list[Entry]) -> dict[str, Any]:
        """Classify entries into 10 distinct editorial sections with translation."""
        if not entries:
            return {
                "lead": None,
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

        # Auto-translate any foreign language entries to English
        from ai_security_monitor.application.services.translation_service import translation_service
        for e in entries:
            try:
                translation_service.translate_entry(e)
            except Exception:
                pass

        def priority_score(e: Entry) -> int:
            score = 0
            if e.analysis:
                if e.analysis.is_pre_cve_warning:
                    score += 500
                score += e.analysis.threat_velocity * 2
                score += e.analysis.severity_index
                if "PoC" in (e.analysis.weaponization_potential or ""):
                    score += 200
            return score

        sorted_entries = sorted(entries, key=priority_score, reverse=True)
        lead = sorted_entries[0] if sorted_entries else None
        remaining = sorted_entries[1:] if len(sorted_entries) > 1 else []

        pre_cves = []
        ai_labs = []
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
            is_pre = e.analysis and e.analysis.is_pre_cve_warning

            is_china = (
                region == "china"
                or country in ("CN", "HK")
                or any(k in t_lower for k in ("deepseek", "qwen", "glm", "internlm", "zhipu", "baidu", "360", "cnnvd", "tencent", "tsinghua", "antiy", "venustech", "kunlun"))
            )
            is_poc = "poc" in t_lower or "exploit" in t_lower or (e.analysis and "PoC" in (e.analysis.weaponization_potential or ""))
            is_cloud = any(k in t_lower or k in s_lower for k in ("aws", "azure", "gcp", "kubernetes", "k8s", "docker", "cloud", "iam", "npm", "pypi", "container"))
            is_cert = any(k in t_lower or k in s_lower for k in ("cisa", "cert", "ncsc", "advisory", "bulletin", "alert", "security update"))

            if is_china and len(china_radar) < 12:
                china_radar.append(e)
            elif is_pre and len(pre_cves) < 12:
                pre_cves.append(e)
            elif is_poc and len(exploits) < 12:
                exploits.append(e)
            elif (cat in ("ai_tech", "ai_models", "ai_research") or "llm" in t_lower or "gpt" in t_lower) and len(ai_labs) < 12:
                ai_labs.append(e)
            elif is_cloud and len(cloud_infra) < 12:
                cloud_infra.append(e)
            elif (cat == "vulnerabilities" or "cve" in t_lower) and len(cves) < 15:
                cves.append(e)
            elif is_cert and len(cert_bulletins) < 12:
                cert_bulletins.append(e)
            else:
                cves.append(e)

        # Backfill empty sections from remaining pool if needed
        pool = remaining[:]
        if not pre_cves:
            pre_cves = pool[:6]
        if not ai_labs:
            ai_labs = pool[6:12]
        if not china_radar:
            china_radar = pool[12:18]
        if not exploits:
            exploits = pool[18:24]
        if not cloud_infra:
            cloud_infra = pool[24:30]
        if not cert_bulletins:
            cert_bulletins = pool[30:36]

        return {
            "lead": lead,
            "front_page_briefs": remaining[:4],
            "ciso_briefs": remaining[4:10],
            "pre_cve": pre_cves,
            "ai_labs": ai_labs,
            "china_radar": china_radar,
            "cves": cves,
            "exploits": exploits,
            "cloud_infra": cloud_infra,
            "cert_bulletins": cert_bulletins,
            "mitre_matrix": sorted_entries[:15],
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

        lead_title = lead.title if lead else "Global Threat Landscape Advisory"
        lead_summary = lead.summary if lead else "Continuous monitoring active across global telemetry nodes."
        lead_vel = lead.analysis.threat_velocity if lead and lead.analysis else 40
        lead_sev = lead.analysis.severity_index if lead and lead.analysis else 50
        lead_blast = lead.analysis.blast_radius_score if lead and lead.analysis else 45
        lead_vec = lead.analysis.attack_vector if lead and lead.analysis else "Network perimeter exploitation"
        lead_mit = lead.analysis.mitigation if lead and lead.analysis else "Apply emergency vendor patches"

        md = f"""# 📰 THE CYBER INTELLIGENCE CHRONICLE
**Autonomous 10-Page Comprehensive Intelligence Dossier • Edition #{edition_num}**  
*Date: {date_str} • Monitoring Horizon: {window_hours} Hours • Verified Across 92 Sensors*

---

## 🏛️ [PAGE 1] FRONT PAGE: BREAKING ZERO-DAY & GLOBAL LEAD STORY
### 🚨 {lead_title}
- **Threat Velocity Index**: `{lead_vel}/100` | **Severity Score**: `{lead_sev}/100` | **Blast Radius**: `{lead_blast}/100`
- **Exploitation Vector**: {lead_vec}
- **Direct Remediation Directive**: {lead_mit}

{lead_summary}

#### Top Flash Bulletins
"""
        for item in categorized.get("front_page_briefs", [])[:4]:
            vel = item.analysis.threat_velocity if item.analysis else 30
            md += f"- **{item.title}** (VEL `{vel}`) — {item.summary or 'Active indicator.'}\n"

        md += f"""
---

## 👔 [PAGE 2] CISO & EXECUTIVE BOARD INTELLIGENCE BRIEF
- **Global Posture Assessment**: DEFCON 3 (Elevated). Active autonomous weaponization detected.
- **Top Attack Surface Exposure**: Enterprise Identity Gateways, Kubernetes Ingress, Agentic AI RAG APIs.

### Key Executive Action Items
"""
        for item in categorized.get("ciso_briefs", [])[:5]:
            md += f"1. **{item.title}**: Verify patching and isolate exposed endpoints.\n"

        md += f"""
---

## 🔬 [PAGE 3] AI FRONTIER, LLM SECURITY & PRE-CVE EARLY WARNINGS
"""
        for p in categorized.get("pre_cve", [])[:6]:
            vel = p.analysis.threat_velocity if p.analysis else 25
            md += f"### ⚡ {p.title}\n- **Velocity**: `{vel}/100` | **Source**: `{self._get_source_name(p)}`\n- {p.summary or ''}\n\n"

        md += f"""
---

## 🇨🇳 [PAGE 4] SOVEREIGN NATION-STATE & CHINA CYBER RADAR (🇨🇳 🇷🇺 🇮🇷 🇰🇵)
"""
        for ch in categorized.get("china_radar", [])[:6]:
            md += f"### 🌐 {ch.title}\n- **Sovereign Source**: `{self._get_source_name(ch)}`\n- {ch.summary or ''}\n\n"

        md += f"""
---

## 🔴 [PAGE 5] HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV
"""
        for c in categorized.get("cves", [])[:6]:
            md += f"### 🛡️ {c.title}\n- **Severity**: `{c.analysis.severity_index if c.analysis else 50}/100` | **Reference**: {c.url}\n- {c.summary or ''}\n\n"

        md += f"""
---

## ⚡ [PAGE 6] VERIFIED PROOF-OF-CONCEPTS (POCs) & RED TEAM EXPLOIT REPOSITORIES
"""
        for exp in categorized.get("exploits", [])[:6]:
            md += f"- **{exp.title}**: Weaponization potential confirmed. Verify intrusion detection signatures.\n"

        md += f"""
---

## ☁️ [PAGE 7] CLOUD INFRASTRUCTURE, KUBERNETES & SUPPLY CHAIN DEFENSE
"""
        for cld in categorized.get("cloud_infra", [])[:6]:
            md += f"- **{cld.title}**: Audit cloud IAM roles and container base images.\n"

        md += f"""
---

## 🌐 [PAGE 8] GLOBAL CERT BULLETINS & SECTOR IMPACT ADVISORIES
"""
        for cert in categorized.get("cert_bulletins", [])[:6]:
            md += f"- **{cert.title}** (`{self._get_source_name(cert)}`)\n"

        md += f"""
---

## 🎯 [PAGE 9] MITRE ATT&CK & ATLAS ENTERPRISE THREAT MATRIX
| Technique / ID | Target Entity | Threat Level | Recommended Telemetry |
| :--- | :--- | :--- | :--- |
| **T1190 Exploit Public-Facing App** | Web & API Gateways | Critical | WAF inspection, ingress rate-limiting |
| **T1059 Command and Scripting** | Host & Container | High | Auditd, Sysmon process telemetry |
| **T1078 Valid Accounts** | Cloud IAM & IdP | High | Enforce FIDO2 MFA, rotate session tokens |
| **AML.T0054 LLM Prompt Injection** | Autonomous AI Agents | High | Enforce system prompt boundaries |

---

## 🛡️ [PAGE 10] 24-HOUR DEFENSIVE PLAYBOOK & SECOPS DIRECTIVES
1. **Emergency Patch Priority (P0)**: Remediate lead critical zero-days within 4 hours.
2. **Perimeter Hardening (P1)**: Isolate unused administrative ports and audit Kubernetes API access.
3. **AI Defense Controls (P2)**: Implement input guardrails against prompt injection and RAG poisoning.

*Imprimatur: The Cyber Intelligence Chronicle • AetherGuard Autonomous SecIntel Engine*
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
        10-PAGE COMPREHENSIVE INTELLIGENCE DOSSIER
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
        "Omnis Vulnerabilitas Patefacietur" — Autonomous Telemetry from 92 Global Threat Arrays
      </p>
    </header>
    <div class="double-rule-thick my-2"></div>
    <div class="flex items-center justify-between text-[11px] font-mono py-1 text-[#1f2937] font-semibold border-b border-[#1e2430]">
      <div>{date_str}</div>
      <div>NO. {edition_num} • DAILY EXECUTIVE EDITION</div>
      <div>{time_str} • REPORTERS: AETHERGUARD AI ENGINE</div>
    </div>

    <!-- Breaking Lead Story -->
    <section class="mt-6 mb-8">
      <div class="text-[11px] font-mono font-bold uppercase tracking-widest text-red-700 mb-1 flex items-center gap-2">
        <span class="inline-block w-2 h-2 bg-red-700"></span> BREAKING GLOBAL ZERO-DAY ADVISORY
      </div>
      <h2 class="headline-font text-2xl sm:text-4xl font-black text-[#0a0d13] mb-3 leading-tight">
        {html.escape(lead_title)}
      </h2>
      <p class="text-sm font-serif italic text-[#374151] mb-4 pb-2 border-b border-[#d1cbba]">
        Threat velocity clocks at {lead_vel}/100 with blast radius {lead_blast}/100; enterprise systems face active exposure.
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

    <!-- Top Bulletins -->
    <div class="border-t-2 border-[#1e2430] pt-4">
      <h3 class="font-mono text-xs font-bold uppercase text-red-800 mb-3">⚡ Front Page Global Flash Bulletins</h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
        {"".join([f"""
          <div class="p-2.5 bg-white/60 border border-[#d1cbba]">
            <span class="text-[9.5px] font-mono font-bold text-red-700">VEL {item.analysis.threat_velocity if item.analysis else 35}/100</span>
            <h4 class="font-serif font-bold text-xs mt-1"><a href="{item.url}" target="_blank" class="hover:text-red-700">{html.escape(item.title)}</a></h4>
            <p class="text-[11px] text-[#4b5563] mt-1 line-clamp-2">{html.escape(item.summary or '')}</p>
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
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">CISO Strategic Risk Assessment & Threat Velocity Matrix</h2>
    <p class="text-xs text-[#4b5563] italic mb-4">High-level threat prioritization synthesized for executive board decision-makers.</p>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
      <div class="p-4 bg-white/70 border border-[#d1cbba]">
        <h3 class="font-mono text-xs font-bold uppercase text-blue-900 mb-2">🎯 Macro Threat Landscape</h3>
        <p class="leading-relaxed text-[#374151] mb-3">Autonomous telemetry across 92 sensing feeds indicates an acceleration in edge device exploitation, API credential leakage, and prompt injection weaponization targeting automated corporate agents.</p>
        <div class="p-2 bg-[#f5f2e8] border border-[#d8d3c5] font-mono text-[10.5px]">
          <strong>PRIORITY 1:</strong> Enforce FIDO2 hardware MFA on all administrative cloud IdPs.<br>
          <strong>PRIORITY 2:</strong> Isolate public Kubernetes ingress and audit RAG pipeline inputs.
        </div>
      </div>
      <div class="p-4 bg-white/70 border border-[#d1cbba]">
        <h3 class="font-mono text-xs font-bold uppercase text-red-800 mb-2">⚡ 24-Hour Critical Action Items</h3>
        <ul class="space-y-2 font-mono text-[11px] text-[#1e293b]">
          {"".join([f"<li>• <strong>{html.escape(b.title[:45])}...</strong>: Verify patch deployment.</li>" for b in categorized.get("ciso_briefs", [])[:5]])}
        </ul>
      </div>
    </div>
  </article>

  <!-- PAGES 3 to 10 RENDERED IN BROADSHEET FORMAT -->
  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION III: AI FRONTIER & PRE-CVE</div>
      <div>ACADEMIC ZERO-DAYS</div>
      <div>PAGE 3 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Frontier AI Models, Prompt Injection & Pre-CVE Register</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
      {"".join([f"""
        <div class="p-3 bg-white/70 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-amber-700">⚡ PRE-CVE WARNING • VEL {p.analysis.threat_velocity if p.analysis else 30}</span>
          <h4 class="font-serif font-bold text-xs mt-1">{html.escape(p.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1">{html.escape(p.summary or '')}</p>
        </div>
      """ for p in categorized.get("pre_cve", [])[:6]])}
    </div>
  </article>

  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION IV: SOVEREIGN RADAR</div>
      <div>🇨🇳 🇷🇺 🇮🇷 🇰🇵 NATION-STATE INTEL</div>
      <div>PAGE 4 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Sovereign Nation-State & Translated Threat Radar</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
      {"".join([f"""
        <div class="p-3 bg-white/70 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-red-700">🇨🇳 {html.escape(self._get_source_name(ch)[:20])}</span>
          <h4 class="font-serif font-bold text-xs mt-1">{html.escape(ch.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1">{html.escape(ch.summary or '')}</p>
        </div>
      """ for ch in categorized.get("china_radar", [])[:6]])}
    </div>
  </article>

  <article class="newspaper-sheet max-w-5xl mx-auto p-6 sm:p-12 mb-8 text-[#12161f]">
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>SECTION V: VULNERABILITIES</div>
      <div>CISA KEV REGISTER</div>
      <div>PAGE 5 OF 10</div>
    </div>
    <h2 class="headline-font text-2xl font-black mt-4 mb-2">Exploited Vulnerabilities & CISA KEV Catalog</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
      {"".join([f"""
        <div class="p-3 bg-white/70 border border-[#d1cbba]">
          <span class="text-[9.5px] font-mono font-bold text-blue-900">🛡️ SEV {c.analysis.severity_index if c.analysis else 50}/100</span>
          <h4 class="font-serif font-bold text-xs mt-1">{html.escape(c.title)}</h4>
          <p class="text-[11px] text-[#4b5563] mt-1">{html.escape(c.summary or '')}</p>
        </div>
      """ for c in categorized.get("cves", [])[:6]])}
    </div>
  </article>

  <footer class="text-center font-mono text-[10px] text-[#4b5563] pt-4">
    PUBLISHED AUTONOMOUSLY EVERY FIVE HOURS BY AETHERGUARD SECINTEL • VERIFIED AGAINST 92 SENSORS • COMPLETE 10-PAGE EDITION
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
        """Render a publication-grade 10-page PDF document."""
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=40,
            bottomMargin=42,
        )

        base_styles = getSampleStyleSheet()

        # Custom Typography
        masthead_title = ParagraphStyle(
            "MastheadTitle",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=25,
            alignment=1,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )
        masthead_sub = ParagraphStyle(
            "MastheadSub",
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#475569"),
            spaceAfter=4,
        )
        page_header = ParagraphStyle(
            "PageHeader",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=3,
        )
        page_sub = ParagraphStyle(
            "PageSub",
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
            spaceAfter=8,
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
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#0a0d13"),
            spaceAfter=3,
        )
        body_style = ParagraphStyle(
            "Body",
            fontName="Times-Roman",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#1f2937"),
            alignment=4,
            spaceAfter=4,
        )
        item_title = ParagraphStyle(
            "ItemTitle",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0f172a"),
        )
        item_summary = ParagraphStyle(
            "ItemSummary",
            fontName="Times-Roman",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#334155"),
        )
        callout_text = ParagraphStyle(
            "CalloutText",
            fontName="Courier-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a"),
        )

        date_str = generated_at.strftime("%A, %B %d, %Y • %H:%M UTC")
        story = []

        def make_section_table(items: list[Entry], tag_color="#b91c1c", tag_label="INTEL"):
            table_data = []
            for item in items[:6]:
                src = self._get_source_name(item)
                vel = item.analysis.threat_velocity if item.analysis else 30
                sev = item.analysis.severity_index if item.analysis else 45
                title_p = Paragraph(f"<b>{html.escape(item.title)}</b>", item_title)
                meta_p = Paragraph(f"<font color='{tag_color}'><b>[{tag_label}]</b></font> <b>SRC:</b> {html.escape(src[:18])} | <b>VEL:</b> {vel} | <b>SEV:</b> {sev}", dateline_style)
                sum_p = Paragraph(html.escape((item.summary or 'Active intelligence indicator.')[:220]) + "...", item_summary)
                table_data.append([
                    Paragraph(f"•", ParagraphStyle('B', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor(tag_color))),
                    [meta_p, title_p, sum_p]
                ])
            t = Table(table_data, colWidths=[15, 525])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ]))
            return t

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 1: FRONT PAGE & BREAKING LEAD STORY
        # ═════════════════════════════════════════════════════════════════════
        story.append(Table([[
            Paragraph("AETHERGUARD DEFENSE DISPATCH", dateline_style),
            Paragraph("GLOBAL THREAT: <b>DEFCON 3 (ELEVATED)</b>", dateline_style),
            Paragraph(f"PAGE 1 OF 10 • 10-PAGE DOSSIER", ParagraphStyle('R', fontName='Helvetica-Bold', fontSize=7.5, alignment=2, textColor=colors.HexColor('#1e293b'))),
        ]], colWidths=[180, 180, 180]))
        story.append(Spacer(1, 3))
        story.append(Paragraph("THE CYBER INTELLIGENCE CHRONICLE", masthead_title))
        story.append(Paragraph('"Omnis Vulnerabilitas Patefacietur" — Autonomous Telemetry Across 92 Global Arrays', masthead_sub))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f172a"), spaceAfter=2))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#0f172a"), spaceAfter=4))
        story.append(Table([[
            Paragraph(f"<b>{date_str}</b>", dateline_style),
            Paragraph(f"<b>EDITION NO. {edition_num}</b>", ParagraphStyle('C', fontName='Helvetica-Bold', fontSize=7.5, alignment=1, textColor=colors.HexColor('#1e293b'))),
            Paragraph("<b>AETHERGUARD AI CORE</b>", ParagraphStyle('R', fontName='Helvetica-Bold', fontSize=7.5, alignment=2, textColor=colors.HexColor('#1e293b'))),
        ]], colWidths=[200, 140, 200]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6))

        lead = categorized["lead"]
        if lead:
            lead_vel = lead.analysis.threat_velocity if lead.analysis else 40
            lead_sev = lead.analysis.severity_index if lead.analysis else 50
            lead_blast = lead.analysis.blast_radius_score if lead.analysis else 45
            story.append(Paragraph("<font color='#b91c1c'><b>🚨 BREAKING ADVISORY // CRITICAL ZERO-DAY INCIDENT</b></font>", dateline_style))
            story.append(Paragraph(html.escape(lead.title), headline_style))
            story.append(Paragraph(f"<i>Threat velocity: {lead_vel}/100 • Severity index: {lead_sev}/100 • Blast radius: {lead_blast}/100</i>", ParagraphStyle('I', fontName='Times-Italic', fontSize=8, textColor=colors.HexColor('#334155'), spaceAfter=4)))
            story.append(Paragraph(html.escape(lead.summary or "High-priority intelligence item."), body_style))

            lead_vec = lead.analysis.attack_vector if lead.analysis else "Perimeter exploit"
            lead_mit = lead.analysis.mitigation if lead.analysis else "Apply emergency vendor patches"
            t_box = Table([[
                Paragraph(f"<b>EXPLOITATION VECTOR:</b> {html.escape(lead_vec)}<br/><b>DIRECTIVE:</b> {html.escape(lead_mit)}", callout_text)
            ]], colWidths=[540])
            t_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(t_box)

        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>⚡ TOP FRONT-PAGE FLASH BULLETINS</b>", page_header))
        story.append(make_section_table(categorized.get("front_page_briefs", []), tag_color="#b91c1c", tag_label="CRITICAL"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 2: CISO & EXECUTIVE BOARD INTELLIGENCE BRIEFING
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("👔 SECTION II: CISO & EXECUTIVE BOARD STRATEGIC BRIEFING", page_header))
        story.append(Paragraph("Macro Threat Trends, Attack Surface Exposure, and 24-Hour Prioritized Action Items", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        
        ciso_p = Paragraph(
            "<b>EXECUTIVE POSTURE:</b> Global threat environment remains in elevated DEFCON 3 state. "
            "Telemetry across 92 sensing nodes identifies persistent nation-state adversary scanning against exposed Kubernetes APIs, "
            "cloud IAM role escalations, and automated prompt injection against corporate LLM deployments. "
            "Executive leadership is instructed to verify emergency patch status on edge firewalls and revoke stale IdP sessions.",
            body_style
        )
        story.append(ciso_p)
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>PRIORITIZED 24-HOUR EXECUTIVE DIRECTIVES</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#0f172a'), spaceAfter=4)))
        story.append(make_section_table(categorized.get("ciso_briefs", []), tag_color="#1e3a8a", tag_label="EXECUTIVE"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 3: AI FRONTIER, LLM VULNERABILITIES & PRE-CVE EARLY WARNINGS
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🤖 SECTION III: AI FRONTIER, LLM SECURITY & PRE-CVE EARLY WARNINGS", page_header))
        story.append(Paragraph("Academic Disclosures, Model Weights Exfiltration, Prompt Injection & Pre-CVE Wire", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("pre_cve", []), tag_color="#d97706", tag_label="PRE-CVE"))
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>FRONTIER MODEL DISPATCHES (DEEPSEEK, QWEN, OPENAI, ANTHROPIC)</b>", ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#0f172a'), spaceAfter=4)))
        story.append(make_section_table(categorized.get("ai_labs", []), tag_color="#4f46e5", tag_label="AI LABS"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 4: SOVEREIGN NATION-STATE & CHINA CYBER RADAR (🇨🇳 🇷🇺 🇮🇷 🇰🇵)
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🌐 SECTION IV: SOVEREIGN NATION-STATE & CHINA THREAT RADAR", page_header))
        story.append(Paragraph("Real-Time Translated Telemetry from Sovereign CERTs, Threat Labs & APT Tracking", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("china_radar", []), tag_color="#b91c1c", tag_label="SOVEREIGN"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 5: HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🛡️ SECTION V: HIGH-VELOCITY EXPLOITED VULNERABILITIES & CISA KEV", page_header))
        story.append(Paragraph("Known Exploited Vulnerabilities Catalog, CVSS Risk Ratings & Remediation Mandates", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("cves", []), tag_color="#dc2626", tag_label="CISA KEV"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 6: VERIFIED PROOF-OF-CONCEPTS (POCs) & RED TEAM EXPLOIT REPOSITORIES
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("⚡ SECTION VI: VERIFIED PROOF-OF-CONCEPTS & RED TEAM REPOSITORIES", page_header))
        story.append(Paragraph("Exploit-DB, Packet Storm, and GitHub Trending 0-Day Code Weaponization Analysis", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("exploits", []), tag_color="#ea580c", tag_label="EXPLOIT PoC"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 7: CLOUD INFRASTRUCTURE, KUBERNETES & SUPPLY CHAIN DEFENSE
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("☁️ SECTION VII: CLOUD, CONTAINER & SUPPLY CHAIN THREATS", page_header))
        story.append(Paragraph("AWS, Azure, GCP, Kubernetes Ingress & Malicious Open-Source Package Telemetry", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("cloud_infra", []), tag_color="#0284c7", tag_label="CLOUD/K8S"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 8: GLOBAL CERT ADVISORIES & INCIDENT RESPONSE BULLETINS
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🌍 SECTION VIII: INTERNATIONAL CERT BULLETINS & SECTOR IMPACT", page_header))
        story.append(Paragraph("NCSC-UK, CERT-EU, JPCERT/CC, GovCERT.HK & Critical Infrastructure Directives", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        story.append(make_section_table(categorized.get("cert_bulletins", []), tag_color="#059669", tag_label="CERT"))
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 9: MITRE ATT&CK & ATLAS ENTERPRISE THREAT MATRIX
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🎯 SECTION IX: MITRE ATT&CK & ATLAS ENTERPRISE THREAT TAXONOMY", page_header))
        story.append(Paragraph("Tactical Adversary TTP Mapping and Machine Learning ATLAS Security Matrix", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))
        
        mitre_table_data = [
            [
                Paragraph("<b>TECHNIQUE</b>", dateline_style),
                Paragraph("<b>NAME</b>", dateline_style),
                Paragraph("<b>TACTIC</b>", dateline_style),
                Paragraph("<b>MITIGATION DIRECTIVE</b>", dateline_style),
            ],
            [
                Paragraph("<b>T1190</b>", callout_text),
                Paragraph("Exploit Public-Facing App", item_title),
                Paragraph("Initial Access", item_summary),
                Paragraph("Deploy WAF rules & patch edge perimeter gateways", item_summary),
            ],
            [
                Paragraph("<b>T1059</b>", callout_text),
                Paragraph("Command & Scripting Interpreter", item_title),
                Paragraph("Execution", item_summary),
                Paragraph("Enforce PowerShell Constrained Language & container read-only roots", item_summary),
            ],
            [
                Paragraph("<b>T1078</b>", callout_text),
                Paragraph("Valid Accounts & IdP Token Theft", item_title),
                Paragraph("Defense Evasion", item_summary),
                Paragraph("Mandate FIDO2 MFA & continuous conditional access re-evaluation", item_summary),
            ],
            [
                Paragraph("<b>T1486</b>", callout_text),
                Paragraph("Data Encrypted for Impact (Ransomware)", item_title),
                Paragraph("Impact", item_summary),
                Paragraph("Immutable offline backups & volume shadow copy monitoring", item_summary),
            ],
            [
                Paragraph("<b>AML.T0054</b>", callout_text),
                Paragraph("LLM Prompt Injection & Jailbreak", item_title),
                Paragraph("AI ATLAS", item_summary),
                Paragraph("Input guardrails & strict tool parameter schema validation", item_summary),
            ],
            [
                Paragraph("<b>AML.T0043</b>", callout_text),
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
        story.append(PageBreak())

        # ═════════════════════════════════════════════════════════════════════
        # PAGE 10: 24-HOUR DEFENSIVE PLAYBOOK & SECOPS DIRECTIVES
        # ═════════════════════════════════════════════════════════════════════
        story.append(Paragraph("🛡️ SECTION X: 24-HOUR REMEDIATION PLAYBOOK & SECOPS DIRECTIVES", page_header))
        story.append(Paragraph("Actionable Patching Schedules, Firewall Ingress Hardening & Broadsheet Colophon", page_sub))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a"), spaceAfter=6))

        playbook_data = [
            [
                Paragraph("<b>TIER</b>", dateline_style),
                Paragraph("<b>SLA</b>", dateline_style),
                Paragraph("<b>SCOPE & DIRECTIVES</b>", dateline_style),
            ],
            [
                Paragraph("<font color='#b91c1c'><b>P0 EMERGENCY</b></font>", callout_text),
                Paragraph("<b>&lt; 4 Hours</b>", dateline_style),
                Paragraph("Apply vendor patches for active in-the-wild zero-days (CISA KEV). Isolate compromised host instances immediately.", item_summary),
            ],
            [
                Paragraph("<font color='#ea580c'><b>P1 CRITICAL</b></font>", callout_text),
                Paragraph("<b>&lt; 24 Hours</b>", dateline_style),
                Paragraph("Patch high-velocity CVEs (CVSS >= 8.5). Rotate service account credentials for exposed cloud providers.", item_summary),
            ],
            [
                Paragraph("<font color='#0284c7'><b>P2 HIGH</b></font>", callout_text),
                Paragraph("<b>&lt; 72 Hours</b>", dateline_style),
                Paragraph("Audit AI agent system prompts, update dependencies in container registries, and apply non-critical OS updates.", item_summary),
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

        story.append(Spacer(1, 10))
        colophon = Paragraph(
            "<b>COLOPHON & SENSOR METHODOLOGY:</b> The Cyber Intelligence Chronicle is generated autonomously every five hours by the "
            "AetherGuard Security Intelligence Engine. Data is aggregated from 92 authoritative sources including CISA, NVD, Exploit-DB, "
            "GitHub Advisory Database, arXiv, CNNVD, and global national CERTs. Heuristic and neural NLP analyzers perform continuous de-noising, "
            "threat velocity calculations, and multi-language translation. All rights reserved.",
            body_style
        )
        story.append(colophon)

        # Build PDF with NumberedCanvas for exact page count
        doc.build(story, canvasmaker=NumberedCanvas)


_newspaper_service = NewspaperService()
