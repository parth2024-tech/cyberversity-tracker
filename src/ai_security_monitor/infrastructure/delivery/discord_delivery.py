"""
Discord delivery adapter using Discord Webhook API.
Sends high-fidelity rich embed notifications for AI intelligence dispatches.
Inspired by Horizon's rich webhook dispatch engine.
"""

from __future__ import annotations

from typing import Any

import httpx

from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
)


class DiscordDelivery(BaseDelivery):
    """Discord delivery via Webhooks with rich embeds."""

    DISCORD_EMBED_COLOR = 0x06B6D4  # Cyan/Teal (Engineering Intelligence Theme)
    DISCORD_ALERT_COLOR = 0x10B981  # Emerald Green for Frontier Releases

    @property
    def channel_name(self) -> str:
        return "discord"

    def validate_config(self) -> None:
        if not self.config.get("webhook_url"):
            raise DeliveryConfigError(self.channel_name, ["webhook_url"])

    async def send_digest(
        self,
        digest: Digest,
        entries_with_analysis: list[tuple[Entry, Analysis | None]],
    ) -> DeliveryResult:
        """Send daily or periodic AI intelligence digest to Discord."""
        try:
            webhook_url = str(self.config["webhook_url"])

            embeds: list[dict[str, Any]] = []

            # 1. Header Overview Embed
            header_embed = {
                "title": f"📰 Worldwide AI Intelligence Digest ({digest.schedule.capitalize()})",
                "description": (
                    f"Autonomous radar digest covering {digest.total_entries or len(entries_with_analysis)} high-signal developments."
                ),
                "color": self.DISCORD_EMBED_COLOR,
                "fields": [
                    {
                        "name": "📊 Total Intel Items",
                        "value": str(len(entries_with_analysis)),
                        "inline": True,
                    },
                    {
                        "name": "🌐 Ecosystem Scope",
                        "value": "Global Corridors (US, EU, APAC)",
                        "inline": True,
                    },
                ],
                "footer": {"text": "AETHERGUARD // Worldwide AI Ecosystem Radar"},
            }
            embeds.append(header_embed)

            # 2. Top Entries (up to 9 items to stay well within Discord's 10-embed webhook limit)
            for entry, analysis in entries_with_analysis[:9]:
                cat_val = (
                    entry.category.value
                    if hasattr(entry.category, "value")
                    else str(entry.category)
                )
                fields = [
                    {"name": "Category", "value": cat_val.upper(), "inline": True},
                ]
                if analysis:
                    fields.append({
                        "name": "Velocity",
                        "value": f"{analysis.threat_velocity}/100",
                        "inline": True,
                    })

                embeds.append({
                    "title": entry.title[:250],
                    "url": entry.url,
                    "description": (entry.summary or "")[:350],
                    "color": self.DISCORD_ALERT_COLOR,
                    "fields": fields,
                })

            payload = {
                "username": self.config.get("username", "AETHERGUARD Radar"),
                "embeds": embeds,
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(
                success=True, channel=self.channel_name, message="Discord digest delivered"
            )

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send urgent high-priority AI breakthrough alert to Discord."""
        try:
            webhook_url = str(self.config["webhook_url"])
            cat_val = (
                entry.category.value
                if hasattr(entry.category, "value")
                else str(entry.category)
            )

            fields: list[dict[str, Any]] = [
                {"name": "Category", "value": cat_val.upper(), "inline": True},
                {"name": "Velocity", "value": f"{analysis.threat_velocity}/100", "inline": True},
                {"name": "Severity / Impact", "value": f"{analysis.severity_index}/100", "inline": True},
            ]
            if analysis.mitigation:
                fields.append({
                    "name": "Strategic Recommendation",
                    "value": analysis.mitigation[:400],
                    "inline": False,
                })

            embed = {
                "title": f"🚨 High-Velocity AI Breakthrough: {entry.title[:200]}",
                "url": entry.url,
                "description": (entry.summary or "")[:500],
                "color": self.DISCORD_ALERT_COLOR,
                "fields": fields,
                "footer": {"text": "AETHERGUARD // Autonomous Radar Dispatch"},
            }

            payload = {
                "username": self.config.get("username", "AETHERGUARD Radar"),
                "embeds": [embed],
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()

            return DeliveryResult(
                success=True, channel=self.channel_name, message="Discord alert sent"
            )

        except Exception as e:
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )


delivery_registry.register("discord", DiscordDelivery)
