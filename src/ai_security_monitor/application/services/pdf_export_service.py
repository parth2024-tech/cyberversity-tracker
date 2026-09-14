"""
PDF Export Service for Threat Intelligence Briefs and Incident Dossiers.
Generates executive-grade multi-page PDFs using ReportLab.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
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


class DossierNumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and stamp total page numbers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):  # noqa: N802
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running Header on page 2+
        if self._pageNumber > 1:
            self.drawString(
                36, 756, "AETHERGUARD GLOBAL AI & TECHNOLOGY INTELLIGENCE DOSSIER"
            )
            self.drawRightString(576, 756, "EXECUTIVE TECHNOLOGY BRIEF")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(36, 750, 576, 750)

        # Running Footer on all pages
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawString(
            36,
            25,
            "CONFIDENTIAL // FOR AUTHORIZED RESEARCH & DEV USE ONLY • AETHERGUARD AI OBSERVATORY",
        )
        self.drawRightString(576, 25, page_str)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 35, 576, 35)
        self.restoreState()


class PdfExportService:
    """Generates structured PDF reports for threat and AI intelligence entries."""

    @staticmethod
    def generate_dossier_pdf(
        entries: list[dict[str, Any]],
        title: str = "AetherGuard Global AI & Technology Intelligence Dossier",
        subtitle: str = "Frontier AI Systems & Technology Intelligence Briefing",
    ) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=40,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()

        # Custom typography styles
        doc_title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        )
        sub_title_style = ParagraphStyle(
            "DocSubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=8,
        )
        section_h2 = ParagraphStyle(
            "SectionH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=12,
            spaceAfter=6,
        )
        table_hdr_style = ParagraphStyle(
            "TableHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#ffffff"),
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1e293b"),
        )
        threat_title_style = ParagraphStyle(
            "ThreatTitle",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=8,
            spaceAfter=4,
        )
        body_label = ParagraphStyle(
            "BodyLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#334155"),
        )
        body_val = ParagraphStyle(
            "BodyVal",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#475569"),
        )

        story = []
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        # Title Block
        story.append(Paragraph(title.upper(), doc_title_style))
        story.append(Paragraph(f"{subtitle} • Generated: {now_str}", sub_title_style))
        story.append(
            HRFlowable(
                width="100%",
                thickness=2,
                color=colors.HexColor("#0284c7"),
                spaceBefore=2,
                spaceAfter=10,
            )
        )

        # Overview Metadata Stats Box
        total_threats = len(entries)
        high_vel_count = sum(
            1
            for e in entries
            if (e.get("analysis") or {}).get("threat_velocity", 0) >= 70
            or e.get("threat_velocity", 0) >= 70
        )

        stats_data = [
            [
                Paragraph("<b>Total Intelligence Analyzed</b>", body_label),
                Paragraph("<b>High Velocity (≥70)</b>", body_label),
                Paragraph("<b>Frontier Systems & Papers</b>", body_label),
                Paragraph("<b>Observatory Status</b>", body_label),
            ],
            [
                Paragraph(
                    f"<font size=14><b>{total_threats}</b></font>", doc_title_style
                ),
                Paragraph(
                    f"<font size=14 color='#0284c7'><b>{high_vel_count}</b></font>",
                    doc_title_style,
                ),
                Paragraph(
                    f"<font size=14 color='#7c3aed'><b>{sum(1 for e in entries if (e.get('category') or '') in ('ai_models', 'ai_research', 'github_trending'))}</b></font>",
                    doc_title_style,
                ),
                Paragraph(
                    "<font size=11 color='#059669'><b>GLOBAL RADAR // ACTIVE</b></font>",
                    doc_title_style,
                ),
            ],
        ]
        stats_table = Table(stats_data, colWidths=[135, 135, 135, 135])
        stats_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(stats_table)
        story.append(Spacer(1, 12))

        # Section 1: Executive Intelligence Matrix Table
        story.append(
            Paragraph("1. EXECUTIVE INTELLIGENCE & ACCELERATION MATRIX", section_h2)
        )

        table_rows = [
            [
                Paragraph("DISPATCH / ARTIFACT", table_hdr_style),
                Paragraph("SOURCE", table_hdr_style),
                Paragraph("CATEGORY", table_hdr_style),
                Paragraph("VELOCITY", table_hdr_style),
                Paragraph("IMPACT", table_hdr_style),
            ]
        ]

        for idx, entry in enumerate(entries[:25]):
            analysis = entry.get("analysis") or {}
            vel = analysis.get("threat_velocity") or entry.get("threat_velocity") or 25
            blast = (
                analysis.get("blast_radius_score")
                or entry.get("blast_radius_score")
                or 20
            )
            source_name = entry.get("source_name") or "Verified Intel"
            category = entry.get("category") or "security"
            title_text = entry.get("title") or "Unnamed Dispatch"

            vel_color = (
                "#e11d48" if vel >= 70 else ("#d97706" if vel >= 40 else "#0284c7")
            )
            blast_color = (
                "#e11d48" if blast >= 70 else ("#d97706" if blast >= 40 else "#0284c7")
            )

            table_rows.append(
                [
                    Paragraph(f"<b>{idx + 1}.</b> {title_text[:65]}", table_cell_style),
                    Paragraph(source_name[:18], table_cell_style),
                    Paragraph(
                        category.replace("_", " ").upper()[:12], table_cell_style
                    ),
                    Paragraph(
                        f"<font color='{vel_color}'><b>{vel}/100</b></font>",
                        table_cell_style,
                    ),
                    Paragraph(
                        f"<font color='{blast_color}'><b>{blast}/100</b></font>",
                        table_cell_style,
                    ),
                ]
            )

        matrix_table = Table(table_rows, colWidths=[240, 100, 80, 60, 60])
        matrix_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")],
                    ),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(matrix_table)
        story.append(Spacer(1, 14))

        # Section 2: Detailed Intelligence Profiles & Technical Advisories
        story.append(
            Paragraph(
                "2. DETAILED INTELLIGENCE PROFILES & TECHNICAL ADVISORIES", section_h2
            )
        )

        for idx, entry in enumerate(entries[:20]):
            analysis = entry.get("analysis") or {}
            vel = analysis.get("threat_velocity") or entry.get("threat_velocity") or 25
            blast = (
                analysis.get("blast_radius_score")
                or entry.get("blast_radius_score")
                or 20
            )
            source_name = entry.get("source_name") or "Verified Intel"
            category = (entry.get("category") or "security").replace("_", " ").upper()
            pub_date = entry.get("published_at") or "Recent"
            url = entry.get("url") or ""
            is_pre_cve = analysis.get("is_pre_cve_warning") or entry.get(
                "is_pre_cve_warning"
            )
            is_ai_entry = entry.get("is_ai_innovation") or (
                entry.get("category")
                in (
                    "ai_tech",
                    "ai_models",
                    "ai_research",
                    "github_trending",
                    "cyber_tools",
                )
            )

            badge_text = (
                " [🚨 PRE-CVE EARLY WARNING]"
                if is_pre_cve
                else (" [🚀 AI INNOVATION]" if is_ai_entry else "")
            )

            threat_elements = [
                Paragraph(
                    f"<b>{idx + 1}. {entry.get('title')}{badge_text}</b>",
                    threat_title_style,
                ),
                Paragraph(
                    f"<b>Category:</b> {category} | <b>Source:</b> {source_name} | <b>Published:</b> {pub_date} | "
                    f"<b>Velocity:</b> {vel}/100 | <b>Impact:</b> {blast}/100",
                    body_label,
                ),
            ]

            tech_vector = analysis.get("tech_focus") or analysis.get("attack_vector")
            if tech_vector:
                vec_label = (
                    "⚡ Technology Focus:"
                    if is_ai_entry
                    else "⚡ Primary Attack Vector:"
                )
                threat_elements.append(
                    Paragraph(
                        f"<b>{vec_label}</b> {tech_vector}",
                        body_val,
                    )
                )

            cap_summary = analysis.get("capability_summary") or analysis.get(
                "risk_assessment"
            )
            if cap_summary:
                risk_label = (
                    "💡 Capability & Analysis:"
                    if is_ai_entry
                    else "🛡️ Infrastructure Risk:"
                )
                threat_elements.append(
                    Paragraph(
                        f"<b>{risk_label}</b> {cap_summary}",
                        body_val,
                    )
                )
            elif entry.get("summary"):
                threat_elements.append(
                    Paragraph(
                        f"<b>📝 Summary:</b> {entry.get('summary')[:300]}", body_val
                    )
                )

            action_insight = analysis.get("actionable_insight") or analysis.get(
                "mitigation"
            )
            if action_insight:
                mit_label = (
                    "🔧 Deployment Directive:"
                    if is_ai_entry
                    else "🔧 Recommended Patch & Hardening:"
                )
                threat_elements.append(
                    Paragraph(
                        f"<b>{mit_label}</b> <font color='#0284c7'><b>{action_insight}</b></font>",
                        body_val,
                    )
                )

            ecosystem = analysis.get("affected_ecosystem") or []
            if ecosystem:
                threat_elements.append(
                    Paragraph(
                        f"<b>📦 Ecosystem:</b> {', '.join(ecosystem)}",
                        body_val,
                    )
                )

            if url:
                threat_elements.append(
                    Paragraph(
                        f"<b>🔗 Reference Link:</b> <font color='#0284c7'><u>{url[:85]}</u></font>",
                        body_val,
                    )
                )

            threat_elements.append(
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=colors.HexColor("#e2e8f0"),
                    spaceBefore=6,
                    spaceAfter=8,
                )
            )

            story.append(KeepTogether(threat_elements))

        doc.build(story, canvasmaker=DossierNumberedCanvas)
        return buffer.getvalue()
