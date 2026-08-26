# Telegram delivery adapter.


import httpx

from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
)


class TelegramDelivery(BaseDelivery):
    """Telegram delivery via Bot API."""

    @property
    def channel_name(self) -> str:
        return "telegram"

    def validate_config(self) -> None:
        required = ["bot_token", "chat_id"]
        missing = [k for k in required if not self.config.get(k)]
        if missing:
            raise DeliveryConfigError(self.channel_name, missing)

    async def send_digest(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> DeliveryResult:
        """Send digest to Telegram."""
        try:
            message = self._build_message(digest, entries_with_analysis)
            await self._send_message(message)

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(success=True, channel=self.channel_name, message="Telegram message sent")

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send alert to Telegram."""
        try:
            message = (
                f"🚨 <b>High-Velocity Threat Alert</b>\n\n"
                f"<b>Title:</b> {entry.title}\n"
                f"<b>URL:</b> <a href=\"{entry.url}\">Link</a>\n"
                f"<b>Velocity:</b> {analysis.threat_velocity}/100\n"
                f"<b>Severity:</b> {analysis.severity_index}/100\n"
                f"<b>Archetype:</b> {analysis.attack_archetype} ({analysis.weaponization_potential})\n"
                f"<b>Vector:</b> {analysis.attack_vector}\n"
                f"<b>Mitigation:</b> {analysis.mitigation}"
            )
            await self._send_message(message)
            return DeliveryResult(success=True, channel=self.channel_name, message="Telegram alert sent")
        except Exception as e:
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def _send_message(self, text: str) -> None:
        """Send message via Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.config['bot_token']}/sendMessage"
        payload = {
            "chat_id": self.config["chat_id"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

    def _build_message(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> str:
        """Build digest message (Telegram has 4096 char limit)."""
        header = (
            f"📋 <b>{digest.schedule.title()} Digest</b>\n"
            f"Period: {digest.period_start.strftime('%Y-%m-%d')} to {digest.period_end.strftime('%Y-%m-%d')}\n"
            f"Total: {digest.total_entries} entries\n\n"
        )

        parts = [header]

        for category, entries in digest.entries_by_category.items():
            if not entries:
                continue
            cat_entries = [(e, a) for e, a in entries_with_analysis if e.category.value == category]
            if not cat_entries:
                continue

            cat_header = f"📂 <b>{category.replace('_', ' ').title()}</b> ({len(cat_entries)})\n"
            cat_parts = [cat_header]

            for entry, analysis in cat_entries[:3]:  # Limit per category
                item = f"• <a href=\"{entry.url}\">{self._escape_html(entry.title)}</a>"
                if analysis:
                    item += f"\n  ⚡ {analysis.threat_velocity}/100 | ⚠️ {analysis.severity_index}/100"
                    if analysis.is_pre_cve_warning:
                        item += " 🚨 <b>PRE-CVE</b>"
                    item += f"\n  🎯 {analysis.attack_archetype} ({analysis.weaponization_potential})"
                    item += f"\n  💥 {', '.join(analysis.affected_ecosystem[:3]) or 'N/A'}"
                cat_parts.append(item)

            if len(cat_entries) > 3:
                cat_parts.append(f"  ... and {len(cat_entries) - 3} more")

            parts.append("\n".join(cat_parts) + "\n")

        full_message = "\n".join(parts)

        # Truncate if too long (Telegram limit 4096)
        if len(full_message) > 4000:
            full_message = full_message[:3950] + "\n\n<i>...truncated</i>"

        return full_message

    def _escape_html(self, text: str) -> str:
        import html
        return html.escape(str(text or ""), quote=False)


delivery_registry.register("telegram", TelegramDelivery)
