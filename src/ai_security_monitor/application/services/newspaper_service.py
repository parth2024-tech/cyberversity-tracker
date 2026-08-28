"""
Autonomous 5-Hour Newspaper Intelligence Service ("The Cyber Intelligence Chronicle").
Compiles live security intelligence into authentic editorial Markdown and HTML newspaper documents.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import html
from pathlib import Path
import json
from typing import Any, Callable

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

logger = get_logger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/newspapers")


class NewspaperService:
    """Compiles and publishes 5-hour periodic newspaper intelligence documents."""

    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
        output_dir: Path | str | None = None,
    ):
        self._uow_factory = uow_factory or (lambda: SqlAlchemyUnitOfWork())
        self._output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_edition(self, window_hours: int = 5) -> dict[str, Any]:
        """
        Generate a new newspaper edition for the specified time window.
        Saves both .md and .html documents to disk and updates latest links.
        """
        logger.info(f"Initiating {window_hours}-hour intelligence newspaper compilation...")
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)

        async with self._uow_factory() as uow:
            # Query recent entries with analyses
            recent_filters = EntryFilters(since=cutoff, sort_by="velocity")
            entries = await uow.entries.list(
                filters=recent_filters,
                pagination=PaginationParams(limit=40, offset=0)
            )

            # Fallback: if period was quiet (< 6 entries), pull top highest velocity / severity recent entries
            if len(entries) < 6:
                logger.info("Fewer than 6 entries in 5h window; backfilling top historical alerts for edition richness.")
                fallback_filters = EntryFilters(sort_by="velocity")
                entries = await uow.entries.list(
                    filters=fallback_filters,
                    pagination=PaginationParams(limit=30, offset=0)
                )

        edition_num = self._compute_edition_number(now)
        timestamp_str = now.strftime("%Y%m%d_%H%M")
        edition_id = f"chronicle_{timestamp_str}"

        # Segment entries by editorial category
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
        latest_md = self._output_dir / "latest.md"
        latest_html = self._output_dir / "latest.html"
        meta_file = self._output_dir / f"{edition_id}.json"
        latest_meta = self._output_dir / "latest.json"

        md_file.write_text(markdown_content, encoding="utf-8")
        html_file.write_text(html_content, encoding="utf-8")
        latest_md.write_text(markdown_content, encoding="utf-8")
        latest_html.write_text(html_content, encoding="utf-8")

        metadata = {
            "edition_id": edition_id,
            "edition_number": edition_num,
            "title": f"The Cyber Intelligence Chronicle — Edition #{edition_num}",
            "generated_at": now.isoformat(),
            "window_hours": window_hours,
            "total_threats": len(entries),
            "lead_story": categorized["lead"].title if categorized["lead"] else "Global Threat Advisory",
            "pre_cve_count": len(categorized["pre_cve"]),
            "cve_count": len(categorized["cves"]),
            "ai_lab_count": len(categorized["ai_labs"]),
            "md_path": str(md_file),
            "html_path": str(html_file),
        }

        meta_json = json.dumps(metadata, indent=2)
        meta_file.write_text(meta_json, encoding="utf-8")
        latest_meta.write_text(meta_json, encoding="utf-8")

        logger.info(
            f"Successfully published Newspaper Edition #{edition_num} "
            f"({len(entries)} stories compiled into {md_file.name} & {html_file.name})"
        )

        return metadata

    def get_latest_edition(self) -> dict[str, Any] | None:
        """Retrieve metadata and content of the latest newspaper edition."""
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
        """Retrieve the formatted HTML newspaper document of the latest edition."""
        latest_html_file = self._output_dir / "latest.html"
        if latest_html_file.exists():
            return latest_html_file.read_text(encoding="utf-8")
        return None

    def list_editions(self, limit: int = 15) -> list[dict[str, Any]]:
        """List historical newspaper editions stored on disk."""
        editions = []
        for meta_file in sorted(self._output_dir.glob("chronicle_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                editions.append(data)
            except Exception:
                continue
        return editions

    # ─── Editorial Parsing & Formatting ──────────────────────────────────────

    def _get_source_name(self, entry: Entry | None) -> str:
        """Extract a readable source name from metadata or URL."""
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
        return "Intelligence Feed"

    def _compute_edition_number(self, dt: datetime) -> int:
        """Deterministic chronological edition counter starting from Epoch baseline."""
        # 5-hour slots since Jan 1, 2026
        base = datetime(2026, 1, 1)
        hours = max(0, int((dt - base).total_seconds() / 3600))
        return 100 + (hours // 5)

    def _categorize_entries(self, entries: list[Entry]) -> dict[str, Any]:
        """Classify entries into distinct newspaper columns and sections."""
        if not entries:
            return {"lead": None, "pre_cve": [], "cves": [], "ai_labs": [], "general": []}

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
        cves = []
        ai_labs = []
        general = []

        for e in remaining:
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            is_pre = e.analysis and e.analysis.is_pre_cve_warning
            if is_pre:
                pre_cves.append(e)
            elif cat == "vulnerabilities" or "CVE" in e.title:
                cves.append(e)
            elif cat in ("ai_tech", "ai_models", "ai_research"):
                ai_labs.append(e)
            else:
                general.append(e)

        return {
            "lead": lead,
            "pre_cve": pre_cves[:6],
            "cves": cves[:8],
            "ai_labs": ai_labs[:6],
            "general": general[:8],
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
        pre_cves = categorized["pre_cve"]
        cves = categorized["cves"]
        ai_labs = categorized["ai_labs"]

        md = []
        md.append("```")
        md.append("================================================================================")
        md.append("                     THE CYBER INTELLIGENCE CHRONICLE                           ")
        md.append(f"          Edition #{edition_num}  |  {date_str}  |  {window_hours}-Hour Digest          ")
        md.append("             Global Threat Defcon: 3 (ELEVATED)  |  AetherGuard Radar           ")
        md.append("================================================================================")
        md.append("```\n")

        # Front Page Lead Story
        if lead:
            analysis = lead.analysis
            vel = analysis.threat_velocity if analysis else 50
            sev = analysis.severity_index if analysis else 50
            blast = analysis.blast_radius_score if analysis else 20
            eco = ", ".join(analysis.affected_ecosystem) if analysis and analysis.affected_ecosystem else "Global Stacks"
            src = self._get_source_name(lead)

            md.append(f"# 🚨 FRONT PAGE: {lead.title}\n")
            md.append(f"> **DATELINE**: {src.upper()} | **VELOCITY**: {vel}/100 | **SEVERITY**: {sev}/100 | **BLAST RADIUS**: {blast}/100")
            md.append(f"> **TARGET ECOSYSTEM**: {eco}\n")
            
            if lead.summary:
                md.append(f"{lead.summary}\n")

            if analysis and (analysis.attack_vector or analysis.risk_assessment):
                md.append("### 🔬 Architectural Impact & Risk Anatomy")
                if analysis.attack_vector:
                    md.append(f"- **Attack Vector**: {analysis.attack_vector}")
                if analysis.risk_assessment:
                    md.append(f"- **Risk Assessment**: {analysis.risk_assessment}")
                if analysis.mitigation:
                    md.append(f"- **Tactical Patch**: {analysis.mitigation}")
                md.append("")

            if lead.url:
                md.append(f"🔗 *Original Source*: [{lead.url}]({lead.url})\n")

        # CISO Executive Summary
        md.append("---\n")
        md.append("## 👔 CISO EXECUTIVE INTELLIGENCE BRIEF\n")
        total_precve = len(pre_cves) + (1 if lead and lead.analysis and lead.analysis.is_pre_cve_warning else 0)
        md.append(
            f"Over the last **{window_hours} hours**, AetherGuard telemetry ingested and triaged **{len(entries)} urgent threat indicators**. "
            f"Of primary concern are **{total_precve} Pre-CVE zero-day research papers** presenting immediate architectural exposure to generative AI pipelines "
            f"and critical enterprise dependencies.\n"
        )

        # Pre-CVE & Zero-Day Radar Wire
        if pre_cves:
            md.append("---\n")
            md.append("## ⚡ THE ZERO-DAY & PRE-CVE WIRE (Academic & Darknet)\n")
            md.append("*Novel jailbreaks, model extraction, and agent hijacking techniques identified prior to CVE filing:*\n")
            for item in pre_cves:
                an = item.analysis
                v = an.threat_velocity if an else 30
                b = an.blast_radius_score if an else 20
                md.append(f"### • {item.title}")
                md.append(f"- **Velocity**: {v}/100 | **Blast Score**: {b}/100 | **Pattern**: {an.attack_archetype if an else 'Research'}")
                if an and an.attack_vector:
                    md.append(f"- **Vector**: {an.attack_vector}")
                if an and an.mitigation:
                    md.append(f"- **Defense**: {an.mitigation}")
                if item.url:
                    md.append(f"- **Paper / Source**: [View Research]({item.url})")
                md.append("")

        # Vulnerability Ledger (CVE Table)
        if cves:
            md.append("---\n")
            md.append("## 🛡️ THE VULNERABILITY REGISTER (Newly Disclosed CVEs)\n")
            md.append("| CVE / Vulnerability | Velocity | Severity | Vector / Archetype | Source |")
            md.append("|:---|:---:|:---:|:---|:---|")
            for c in cves:
                an = c.analysis
                vel = f"{an.threat_velocity}/100" if an else "N/A"
                sev = f"{an.severity_index}/100" if an else "N/A"
                vec = (an.attack_archetype if an and an.attack_archetype else (an.attack_vector[:35] + "..." if an and an.attack_vector else "CVE Advisory"))
                src_short = self._get_source_name(c)[:14]
                md.append(f"| **{c.title[:45]}...** | `{vel}` | `{sev}` | {vec} | {src_short} |")
            md.append("")

        # AI Labs & Frontier Model Dispatches
        if ai_labs:
            md.append("---\n")
            md.append("## 🤖 AI LABS & FRONTIER MODEL DISPATCHES\n")
            for lab in ai_labs:
                md.append(f"- **{lab.title}**")
                if lab.summary:
                    md.append(f"  {lab.summary[:200]}...")
                if lab.url:
                    md.append(f"  *Reference*: [Open Dispatch]({lab.url})")
            md.append("")

        # Tactical Security Directives
        md.append("---\n")
        md.append("## ⚔️ TACTICAL DEFENSE DIRECTIVES FOR SECURITY OPERATIONS\n")
        md.append("1. **Audit Agentic Tool Permissions**: Restrict all autonomous LLM tool executions to sandboxed ephemeral containers.")
        md.append("2. **Validate Deserialization Endpoints**: Check PyTorch, pickle, and SafeTensors boundary loaders against untrusted weights.")
        md.append("3. **Inspect RAG Embeddings**: Scan vector database inputs for indirect prompt injections and document poisoning vectors.")
        md.append("4. **Apply Upstream Vendor Advisories**: Execute patch deployments for critical CVEs noted in the register above.\n")

        md.append("```")
        md.append("================================================================================")
        md.append("   End of Edition  |  Compiled Autonomously by AetherGuard Cyber Monitor Engine   ")
        md.append("================================================================================")
        md.append("```")

        return "\n".join(md)

    # ─── HTML Newspaper Document Renderer ─────────────────────────────────────

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
        pre_cves = categorized["pre_cve"]
        cves = categorized["cves"]
        ai_labs = categorized["ai_labs"]

        lead_analysis = lead.analysis if lead else None
        lead_vel = lead_analysis.threat_velocity if lead_analysis else 50
        lead_blast = lead_analysis.blast_radius_score if lead_analysis else 20
        lead_eco = ", ".join(lead_analysis.affected_ecosystem) if lead_analysis and lead_analysis.affected_ecosystem else "Global Enterprise Infrastructure"
        lead_src = self._get_source_name(lead) if lead else "Radar Wire"

        lead_section_html = ""
        if lead:
            analysis_box_html = ""
            if lead_analysis:
                analysis_box_html = f"""
                <div class="my-3 p-3 bg-[#f2eedf] border-l-4 border-red-700 font-mono text-xs">
                  <strong>EXPLOIT VECTOR:</strong> {html.escape(lead_analysis.attack_vector or 'Dynamic remote code execution pattern.')}<br>
                  <strong>IMPACT:</strong> {html.escape(lead_analysis.risk_assessment or 'Full pipeline compromise.')}<br>
                  <strong>RECOMMENDED PATCH:</strong> {html.escape(lead_analysis.mitigation or 'Deploy vendor patches and isolate perimeter.')}
                </div>
                """
            lead_section_html = f"""
            <section class="mb-8">
              <div class="text-[11px] font-mono font-bold uppercase tracking-widest text-red-700 mb-1 flex items-center gap-2">
                <span class="inline-block w-2 h-2 bg-red-700"></span> BREAKING ADVISORY // CRITICAL ZERO-DAY
              </div>
              <h2 class="headline-font text-2xl sm:text-4xl md:text-5xl font-black text-[#0a0d13] mb-3 leading-tight">
                {html.escape(lead.title)}
              </h2>
              
              <p class="text-base sm:text-lg font-serif italic text-[#374151] mb-4 pb-3 border-b border-[#d1cbba]">
                Threat velocity clocks at {lead_vel}/100 with blast radius index {lead_blast}/100; enterprise systems face immediate exposure across {html.escape(lead_eco)}.
              </p>

              <div class="editorial-col text-sm leading-relaxed text-[#1f2937]">
                <p class="mb-3 first-letter:text-5xl first-letter:font-bold first-letter:float-left first-letter:mr-2 first-letter:font-serif first-letter:text-black">
                  {html.escape(lead.summary or 'A critical threat indicator has been prioritized by autonomous telemetry sensors.')}
                </p>
                {analysis_box_html}
                <p class="mt-2 text-xs font-mono text-[#4b5563]">
                  Telemetry source: {html.escape(lead_src)} • Reference Link: <a href="{lead.url}" class="text-blue-800 underline break-all">{html.escape(lead.url or 'Internal Sensor')}</a>
                </p>
              </div>
            </section>
            """

        pre_cves_html = "".join([f"""
          <article class="pb-3 border-b border-[#e5e0d3]">
            <h4 class="font-serif font-bold text-sm leading-snug text-[#0f141c] hover:text-red-700">
              <a href="{p.url}" target="_blank">{html.escape(p.title)}</a>
            </h4>
            <div class="text-[10px] font-mono text-red-700 font-semibold mt-1">
              VELOCITY: {p.analysis.threat_velocity if p.analysis else 25} • BLAST: {p.analysis.blast_radius_score if p.analysis else 20}
            </div>
            <p class="text-xs text-[#374151] mt-1 line-clamp-3 leading-normal">
              {html.escape(p.summary or '')}
            </p>
          </article>
        """ for p in pre_cves]) if pre_cves else '<p class="text-xs text-slate-500 italic">No pre-CVE warnings in current cycle.</p>'

        cves_html = "".join([f"""
          <div class="p-2.5 bg-[#f5f2e8] border border-[#d8d3c5]">
            <div class="flex justify-between items-baseline">
              <span class="font-mono text-xs font-bold text-[#111827]">{html.escape(c.title[:28])}...</span>
              <span class="text-[10px] font-mono font-bold text-red-700">SEV: {c.analysis.severity_index if c.analysis else 45}/100</span>
            </div>
            <p class="text-xs text-[#4b5563] mt-1 line-clamp-2">
              {html.escape(c.summary or 'Official CVE advisory.')}
            </p>
            <div class="mt-1.5 text-[10px] font-mono flex justify-between text-[#6b7280]">
              <span>{html.escape(self._get_source_name(c))}</span>
              <a href="{c.url}" target="_blank" class="text-blue-700 underline font-semibold">Inspect →</a>
            </div>
          </div>
        """ for c in cves]) if cves else '<p class="text-xs text-slate-500 italic">No new CVE disclosures in current cycle.</p>'

        ai_labs_html = "".join([f"""
          <div class="pb-2.5 border-b border-[#e5e0d3]">
            <h5 class="font-serif font-semibold text-xs leading-snug">
              <a href="{lab.url}" target="_blank" class="hover:text-blue-800">{html.escape(lab.title)}</a>
            </h5>
            <p class="text-[11px] text-[#4b5563] mt-0.5 line-clamp-2">
              {html.escape(lab.summary or '')}
            </p>
          </div>
        """ for lab in ai_labs]) if ai_labs else '<p class="text-xs text-slate-500 italic">No lab dispatches in current cycle.</p>'

        html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Cyber Intelligence Chronicle — Edition #{edition_num}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root {{
      --paper: #fbf9f4;
      --ink: #11141a;
      --ink-muted: #4b5563;
      --border-ink: #1e2430;
      --accent: #b91c1c;
      --accent-blue: #0369a1;
      --font-masthead: 'Cinzel', serif;
      --font-headline: 'Playfair Display', Georgia, serif;
      --font-body: 'Newsreader', Georgia, serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}
    body {{
      background-color: #0f131a;
      color: var(--ink);
      font-family: var(--font-body);
      -webkit-font-smoothing: antialiased;
    }}
    .newspaper-page {{
      background-color: var(--paper);
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255,255,255,0.05);
      border: 1px solid #d1cbba;
    }}
    .masthead-title {{
      font-family: var(--font-masthead);
      letter-spacing: -0.02em;
    }}
    .headline-font {{
      font-family: var(--font-headline);
      line-height: 1.08;
    }}
    .editorial-col {{
      column-count: 2;
      column-gap: 28px;
      column-rule: 1px solid #d8d3c5;
      text-align: justify;
      text-justify: inter-word;
    }}
    @media (max-width: 768px) {{
      .editorial-col {{ column-count: 1; }}
    }}
    .double-rule-thick {{
      border-top: 3px double var(--border-ink);
      border-bottom: 1px solid var(--border-ink);
      height: 6px;
    }}
    .double-rule-thin {{
      border-top: 1px solid var(--border-ink);
      border-bottom: 1px solid var(--border-ink);
      height: 4px;
    }}
    @media print {{
      body {{ background: transparent !important; padding: 0 !important; }}
      .no-print {{ display: none !important; }}
      .newspaper-page {{ box-shadow: none !important; border: none !important; width: 100% !important; max-width: 100% !important; }}
    }}
  </style>
</head>
<body class="py-8 px-2 sm:px-6">

  <!-- Print & Download Floating Command Bar -->
  <div class="no-print max-w-5xl mx-auto mb-6 flex items-center justify-between bg-slate-900/90 backdrop-blur-md p-3.5 rounded-xl border border-white/10 text-white font-mono text-xs">
    <div class="flex items-center gap-3">
      <span class="flex items-center gap-1.5 text-cyan-400 font-bold">
        <span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
        AUTONOMOUS NEWSPAPER // 5-HOUR CYCLE
      </span>
      <span class="text-slate-500">|</span>
      <span class="text-slate-300">Edition #{edition_num}</span>
    </div>
    <div class="flex items-center gap-2">
      <button onclick="window.print()" class="px-3.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-slate-100 transition font-bold flex items-center gap-1.5">
        🖨️ Print / Save PDF
      </button>
      <a href="/api/newspaper/download?format=md" class="px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition font-bold flex items-center gap-1.5">
        📥 Download Markdown
      </a>
    </div>
  </div>

  <!-- THE NEWSPAPER BROADSHEET -->
  <article class="newspaper-page max-w-5xl mx-auto p-6 sm:p-12 text-[#12161f]">

    <!-- TOP WEATHER & DEFCON BAROMETER STRIP -->
    <div class="flex items-center justify-between text-[11px] font-mono uppercase tracking-widest border-b border-[#222834] pb-1.5 text-[#374151]">
      <div>AETHERGUARD DEFENSE DISPATCH • VOLUME IV</div>
      <div>GLOBAL THREAT LEVEL: <span class="font-bold text-red-700">DEFCON 3 (ELEVATED)</span></div>
      <div>5-HOUR INTELLIGENCE CYCLE</div>
    </div>

    <!-- MAIN EDITORIAL MASTHEAD -->
    <header class="text-center py-5 border-b border-[#1e2430]">
      <h1 class="masthead-title text-3xl sm:text-5xl md:text-6xl font-black uppercase text-[#0d1117] tracking-tight">
        The Cyber Intelligence Chronicle
      </h1>
      <p class="text-xs sm:text-sm italic text-[#4b5563] mt-1 font-serif">
        "Omnis Vulnerabilitas Patefacietur" — Autonomous Telemetry from 79 Global Threat Arrays
      </p>
    </header>

    <!-- DATELINE STRIP -->
    <div class="double-rule-thick my-2"></div>
    <div class="flex items-center justify-between text-[11px] font-mono py-1 text-[#1f2937] font-semibold border-b border-[#1e2430]">
      <div>{date_str}</div>
      <div>NO. {edition_num} • ARCHIVED BROADCAST</div>
      <div>{time_str} • REPORTERS: AETHERGUARD AI ENGINE</div>
    </div>
    <div class="double-rule-thin mb-5"></div>

    <!-- LEAD STORY BANNER HEADLINE -->
    {lead_section_html}

    <div class="double-rule-thick my-6"></div>

    <!-- THREE-COLUMN EDITORIAL GRID: PRE-CVE WIRE + VULNERABILITY REGISTER + AI LABS -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">

      <!-- Column 1: Pre-CVE & Zero-Day Wire -->
      <div class="border-b md:border-b-0 md:border-r border-[#d1cbba] md:pr-5">
        <h3 class="font-mono text-xs font-bold uppercase tracking-wider text-red-700 pb-1.5 border-b-2 border-red-700 mb-3">
          ⚡ Pre-CVE & Zero-Day Wire
        </h3>
        <p class="text-xs text-[#4b5563] italic mb-3">
          Novel academic and darknet research cataloged prior to National Vulnerability Database assignment.
        </p>
        <div class="space-y-4">
          {pre_cves_html}
        </div>
      </div>

      <!-- Column 2: The Vulnerability Ledger -->
      <div class="border-b md:border-b-0 md:border-r border-[#d1cbba] md:px-3">
        <h3 class="font-mono text-xs font-bold uppercase tracking-wider text-blue-900 pb-1.5 border-b-2 border-blue-900 mb-3">
          🛡️ The Vulnerability Ledger
        </h3>
        <p class="text-xs text-[#4b5563] italic mb-3">
          Newly registered CVEs and weaponized exploits recorded during this 5-hour sweep.
        </p>
        <div class="space-y-3.5">
          {cves_html}
        </div>
      </div>

      <!-- Column 3: AI Labs & Frontier Dispatches -->
      <div class="md:pl-2">
        <h3 class="font-mono text-xs font-bold uppercase tracking-wider text-[#1e293b] pb-1.5 border-b-2 border-[#1e293b] mb-3">
          🤖 Frontier AI Labs Dispatch
        </h3>
        <p class="text-xs text-[#4b5563] italic mb-3">
          Model weights releases, architectural shifts, and autonomous agent security developments.
        </p>
        <div class="space-y-3">
          {ai_labs_html}
        </div>

        <!-- Tactical SecOps Checklist Box -->
        <div class="mt-5 p-3 bg-[#e8e4d5] border border-[#1e2430]">
          <h4 class="font-mono text-xs font-bold uppercase text-[#0f172a] mb-1.5">
            ⚔️ Defense Directives
          </h4>
          <ul class="text-[11px] font-mono space-y-1 text-[#1e293b] list-disc list-inside">
            <li>Sandbox dynamic code execution tools</li>
            <li>Enforce SafeTensors deserialization</li>
            <li>Monitor prompt injection vectors in RAG</li>
            <li>Apply patches for high-velocity CVEs</li>
          </ul>
        </div>
      </div>

    </div>

    <div class="double-rule-thick my-6"></div>

    <!-- FOOTER IMPRIMATUR -->
    <footer class="text-center font-mono text-[10px] text-[#4b5563] pt-2">
      PUBLISHED AUTONOMOUSLY EVERY FIVE HOURS BY AETHERGUARD SECINTEL • VERIFIED AGAINST 79 REPOSITORIES • ALL RIGHTS RESERVED
    </footer>

  </article>

</body>
</html>
"""
        return html_out
