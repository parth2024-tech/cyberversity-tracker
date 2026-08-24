# Console delivery adapter.

from typing import Optional
from uuid import UUID

from ai_security_monitor.domain.entities import Entry, Analysis, Digest
from ai_security_monitor.infrastructure.delivery.base import BaseDelivery, DeliveryResult, delivery_registry
from ai_security_monitor.config.settings import settings


class ConsoleDelivery(BaseDelivery):
    """Console output delivery."""

    @property
    def channel_name(self) -> str:
        return "console"

    def validate_config(self) -> None:
        # No config required for console
        pass

    async def send_digest(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Optional[Analysis]]]) -> DeliveryResult:
        """Print digest to console."""
        try:
            print("\n" + "=" * 80)
            print(f"📋 {settings.app_name} - {digest.schedule.upper()} DIGEST")
            print(f"   Period: {digest.period_start.strftime('%Y-%m-%d %H:%M')} - {digest.period_end.strftime('%Y-%m-%d %H:%M')}")
            print(f"   Total Entries: {digest.total_entries}")
            print("=" * 80)

            for category, entries in digest.entries_by_category.items():
                if not entries:
                    continue
                print(f"\n📂 {category.upper()} ({len(entries)} entries)")
                print("-" * 80)

                for entry, analysis in entries_with_analysis:
                    if entry.category.value != category:
                        continue

                    print(f"\n  📰 {entry.title}")
                    print(f"     URL: {entry.url}")
                    print(f"     Source: {entry.metadata.get('source_name', 'Unknown')}")

                    if analysis:
                        print(f"     ⚡ Velocity: {analysis.threat_velocity}/100  Severity: {analysis.severity_index}/100  Blast: {analysis.blast_radius_score}/100")
                        if analysis.is_pre_cve_warning:
                            print(f"     🚨 PRE-CVE WARNING: {analysis.attack_archetype}")
                        print(f"     🎯 Archetype: {analysis.attack_archetype} ({analysis.weaponization_potential})")
                        print(f"     💥 Ecosystems: {', '.join(analysis.affected_ecosystem) or 'None'}")
                        print(f"     📝 Vector: {analysis.attack_vector}")
                        print(f"     🛡️  Mitigation: {analysis.mitigation}")
                    else:
                        print(f"     ⚠️  Not yet analyzed")

            print("\n" + "=" * 80)
            print("End of digest\n")

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(success=True, channel=self.channel_name, message="Console digest printed")

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Print alert to console."""
        try:
            print("\n" + "🚨" + "=" * 78)
            print(f"ALERT: High-velocity threat detected!")
            print(f"Title: {entry.title}")
            print(f"URL: {entry.url}")
            print(f"Velocity: {analysis.threat_velocity}/100 | Severity: {analysis.severity_index}/100")
            print(f"Archetype: {analysis.attack_archetype} ({analysis.weaponization_potential})")
            print(f"Vector: {analysis.attack_vector}")
            print(f"Mitigation: {analysis.mitigation}")
            print("=" * 80 + "\n")

            return DeliveryResult(success=True, channel=self.channel_name, message="Console alert printed")
        except Exception as e:
            return DeliveryResult(success=False, channel=self.channel_name, error=str(e))


delivery_registry.register("console", ConsoleDelivery)
