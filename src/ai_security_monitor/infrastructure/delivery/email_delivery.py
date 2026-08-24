# Email delivery adapter.

import smtplib
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
