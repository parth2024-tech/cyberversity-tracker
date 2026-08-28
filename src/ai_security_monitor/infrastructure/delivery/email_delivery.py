from __future__ import annotations

import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
)


class EmailDelivery(BaseDelivery):
    """Email delivery via SMTP."""

    @property
    def channel_name(self) -> str:
        return "email"

    def validate_config(self) -> None:
        required = ["smtp_server", "smtp_port", "username", "password", "from_email", "to_email"]
        missing = [k for k in required if not self.config.get(k)]
        if missing:
            raise DeliveryConfigError(self.channel_name, missing)

    async def send_digest(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> DeliveryResult:
        """Send digest via email."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config["from_email"]
            msg["To"] = self.config["to_email"]
            msg["Subject"] = f"{settings.app_name} - {digest.schedule.title()} Digest ({digest.total_entries} items)"

            # Build HTML body
            html = self._build_html_body(digest, entries_with_analysis)
            msg.attach(MIMEText(html, "html"))

            # Send
            with smtplib.SMTP(self.config["smtp_server"], self.config["smtp_port"]) as server:
                server.starttls()
                server.login(self.config["username"], self.config["password"])
                server.send_message(msg)

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(success=True, channel=self.channel_name, message="Email sent")

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send alert email."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config["from_email"]
            msg["To"] = self.config["to_email"]
            msg["Subject"] = f"🚨 ALERT: {entry.title[:60]}"

            html = f"""
            <html><body>
            <h2>🚨 High-Velocity Threat Alert</h2>
            <p><strong>Title:</strong> {entry.title}</p>
            <p><strong>URL:</strong> <a href="{entry.url}">{entry.url}</a></p>
            <p><strong>Velocity:</strong> {analysis.threat_velocity}/100</p>
            <p><strong>Severity:</strong> {analysis.severity_index}/100</p>
            <p><strong>Archetype:</strong> {analysis.attack_archetype} ({analysis.weaponization_potential})</p>
            <p><strong>Vector:</strong> {analysis.attack_vector}</p>
            <p><strong>Mitigation:</strong> {analysis.mitigation}</p>
            </body></html>
            """
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(self.config["smtp_server"], self.config["smtp_port"]) as server:
                server.starttls()
                server.login(self.config["username"], self.config["password"])
                server.send_message(msg)

            return DeliveryResult(success=True, channel=self.channel_name, message="Alert email sent")
        except Exception as e:
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def send_newspaper_pdf(
        self,
        pdf_path: str | Path,
        edition_number: int,
        to_email: str | None = None,
        lead_story: str = "",
        total_threats: int = 0,
    ) -> DeliveryResult:
        """Send the 5-hour newspaper PDF edition as an attachment via email."""
        try:
            target_to = to_email or self.config.get("to_email")
            from_email = self.config.get("from_email")
            
            if not target_to or not from_email:
                return DeliveryResult(
                    success=False,
                    channel=self.channel_name,
                    error="Recipient or sender email is missing."
                )

            import html
            from email.mime.application import MIMEApplication

            msg = MIMEMultipart()
            msg["From"] = from_email
            msg["To"] = target_to
            msg["Subject"] = f"📰 The Cyber Intelligence Chronicle — Edition #{edition_number} (PDF Attached)"

            html_body = f"""
            <html>
            <body style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
              <div style="background-color: #0f172a; padding: 24px; text-align: center; border-radius: 8px 8px 0 0;">
                <h1 style="color: #38bdf8; margin: 0; font-size: 22px; text-transform: uppercase; letter-spacing: 1px;">The Cyber Intelligence Chronicle</h1>
                <p style="color: #94a3b8; margin: 5px 0 0 0; font-size: 13px;">Edition #{edition_number} • 5-Hour Intelligence Sweep</p>
              </div>
              <div style="background-color: #ffffff; padding: 24px; border: 1px solid #e2e8f0; border-radius: 0 0 8px 8px;">
                <h2 style="color: #0f172a; font-size: 18px; margin-top: 0;">🚨 Front Page: {html.escape(lead_story or 'Threat Intelligence Dispatch')}</h2>
                <p>Your autonomous 5-hour security intelligence newspaper has been compiled from 79 global monitoring arrays. <strong>{total_threats} threats</strong> were analyzed during this period.</p>
                <div style="background-color: #f8fafc; border-left: 4px solid #0ea5e9; padding: 12px 16px; margin: 18px 0;">
                  <p style="margin: 0; font-size: 14px; font-weight: 600; color: #0369a1;">📎 Attached Document:</p>
                  <p style="margin: 4px 0 0 0; font-size: 13px; color: #475569;">Please find the attached PDF broadsheet (<code>Cyber_Chronicle_Edition_{edition_number}.pdf</code>) formatted for viewing and printing.</p>
                </div>
                <p style="font-size: 12px; color: #64748b; margin-top: 24px; border-top: 1px solid #f1f5f9; padding-top: 12px; text-align: center;">
                  Published autonomously by AetherGuard Cyber Monitor Engine
                </p>
              </div>
            </body>
            </html>
            """
            msg.attach(MIMEText(html_body, "html"))

            p_path = Path(pdf_path)
            if p_path.exists():
                with open(p_path, "rb") as f:
                    pdf_part = MIMEApplication(f.read(), _subtype="pdf")
                    pdf_part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=f"Cyber_Chronicle_Edition_{edition_number}.pdf"
                    )
                    msg.attach(pdf_part)
            else:
                return DeliveryResult(success=False, channel=self.channel_name, error=f"PDF file not found at {pdf_path}")

            server_host = self.config.get("smtp_server", settings.delivery.email_smtp_server)
            server_port = int(self.config.get("smtp_port", settings.delivery.email_smtp_port))
            username = self.config.get("username", settings.delivery.email_username)
            password = self.config.get("password", settings.delivery.email_password)

            with smtplib.SMTP(server_host, server_port) as server:
                server.starttls()
                if username and password:
                    server.login(username, password)
                server.send_message(msg)

            return DeliveryResult(success=True, channel=self.channel_name, message=f"Newspaper PDF Edition #{edition_number} emailed to {target_to}")
        except Exception as e:
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    def _build_html_body(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> str:
        html = f"""
        <html><body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
        <h1>{settings.app_name} - {digest.schedule.title()} Digest</h1>
        <p>Period: {digest.period_start.strftime('%Y-%m-%d %H:%M')} - {digest.period_end.strftime('%Y-%m-%d %H:%M')}</p>
        <p>Total Entries: {digest.total_entries}</p>
        """

        for category, entries in digest.entries_by_category.items():
            if not entries:
                continue
            cat_entries = [(e, a) for e, a in entries_with_analysis if e.category.value == category]
            if not cat_entries:
                continue

            html += f"<h2>{category.replace('_', ' ').title()} ({len(cat_entries)} items)</h2>"

            for entry, analysis in cat_entries:
                html += f"""
                <div style="border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px;">
                    <h3><a href="{entry.url}">{entry.title}</a></h3>
                    <p>Source: {entry.metadata.get('source_name', 'Unknown')}</p>
                """

                if analysis:
                    html += f"""
                    <div style="background: #f5f5f5; padding: 10px; border-radius: 3px;">
                        <p><strong>⚡ Velocity:</strong> {analysis.threat_velocity}/100</p>
                        <p><strong>⚠️ Severity:</strong> {analysis.severity_index}/100</p>
                        <p><strong>💥 Blast Radius:</strong> {analysis.blast_radius_score}/100</p>
                        <p><strong>🎯 Archetype:</strong> {analysis.attack_archetype} ({analysis.weaponization_potential})</p>
                        {"<p style='color: red;'><strong>🚨 PRE-CVE WARNING</strong></p>" if analysis.is_pre_cve_warning else ""}
                        <p><strong>💥 Ecosystems:</strong> {', '.join(analysis.affected_ecosystem) or 'None'}</p>
                        <p><strong>📝 Vector:</strong> {analysis.attack_vector}</p>
                        <p><strong>🛡️ Mitigation:</strong> {analysis.mitigation}</p>
                    </div>
                    """
                else:
                    html += "<p><em>Not yet analyzed</em></p>"

                html += "</div>"

        html += "</body></html>"
        return html


delivery_registry.register("email", EmailDelivery)
