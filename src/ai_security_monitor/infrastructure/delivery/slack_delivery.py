# Slack delivery adapter.


import httpx

from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
)


class SlackDelivery(BaseDelivery):
    """Slack delivery via webhook."""

    @property
    def channel_name(self) -> str:
        return "slack"

    def validate_config(self) -> None:
        if not self.config.get("webhook_url"):
            raise DeliveryConfigError(self.channel_name, ["webhook_url"])

    async def send_digest(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> DeliveryResult:
        """Send digest to Slack."""
        try:
            blocks = self._build_blocks(digest, entries_with_analysis)
            payload = {"blocks": blocks}

            async with httpx.AsyncClient() as client:
                response = await client.post(self.config["webhook_url"], json=payload)
                response.raise_for_status()

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(success=True, channel=self.channel_name, message="Slack message sent")

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send alert to Slack."""
        try:
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🚨 High-Velocity Threat Alert"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Title:*\n{entry.title}"},
                    {"type": "mrkdwn", "text": f"*URL:*\n<{entry.url}|Link>"},
                    {"type": "mrkdwn", "text": f"*Velocity:*\n{analysis.threat_velocity}/100"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{analysis.severity_index}/100"},
                    {"type": "mrkdwn", "text": f"*Archetype:*\n{analysis.attack_archetype}"},
                    {"type": "mrkdwn", "text": f"*Weaponization:*\n{analysis.weaponization_potential}"},
                ]},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Vector:*\n{analysis.attack_vector}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Mitigation:*\n{analysis.mitigation}"}},
            ]
            payload = {"blocks": blocks}

            async with httpx.AsyncClient() as client:
                response = await client.post(self.config["webhook_url"], json=payload)
                response.raise_for_status()

            return DeliveryResult(success=True, channel=self.channel_name, message="Slack alert sent")
        except Exception as e:
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    def _build_blocks(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> list:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📋 {digest.schedule.title()} Digest"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"Period: {digest.period_start.strftime('%Y-%m-%d')} to {digest.period_end.strftime('%Y-%m-%d')} | Total: {digest.total_entries} entries"}
            ]},
            {"type": "divider"},
        ]

        for category, entries in digest.entries_by_category.items():
            if not entries:
                continue
            cat_entries = [(e, a) for e, a in entries_with_analysis if e.category.value == category]
            if not cat_entries:
                continue

            blocks.append({"type": "header", "text": {"type": "plain_text", "text": f"{category.replace('_', ' ').title()}"}})

            for entry, analysis in cat_entries[:5]:  # Limit to 5 per category
                text = f"*<{entry.url}|{entry.title}>*"
                if analysis:
                    text += f"\n⚡ {analysis.threat_velocity}/100 | ⚠️ {analysis.severity_index}/100 | 💥 {analysis.blast_radius_score}/100"
                    if analysis.is_pre_cve_warning:
                        text += " 🚨 *PRE-CVE*"
                    text += f"\n🎯 {analysis.attack_archetype} ({analysis.weaponization_potential})"
                else:
                    text += "\n_Not yet analyzed_"

                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

            if len(cat_entries) > 5:
                blocks.append({"type": "context", "elements": [
                    {"type": "mrkdwn", "text": f"... and {len(cat_entries) - 5} more entries"}
                ]})

            blocks.append({"type": "divider"})

        return blocks


delivery_registry.register("slack", SlackDelivery)
