"""
Telegram ChatOps Service (Pillar 6).
Handles interactive two-way inline callbacks (Vault, Deep Triage, Dismiss, Mute),
dual-mode transport (Webhook vs. Long-Polling with deleteWebhook conflict guard),
and non-blocking background Deep Triage with in-place message editing.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any
from uuid import UUID

from ai_security_monitor.application.services.vault_feedback_service import (
    vault_feedback_service,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Analysis
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.delivery.telegram_delivery import (
    TelegramDelivery,
    build_entry_inline_keyboard,
)

logger = get_logger(__name__)


def _parse_entry_uuid(hex_str: str) -> UUID | None:
    """Parse a 32-hex string or prefix into a UUID."""
    clean = hex_str.strip().replace("-", "")
    if len(clean) == 32:
        try:
            return UUID(hex=clean)
        except ValueError:
            return None
    return None


class TelegramChatOpsService:
    """Orchestrates interactive Telegram inline callbacks and dual transport modes."""

    def __init__(self, delivery: TelegramDelivery | None = None):
        self._delivery = delivery
        self._polling_task: asyncio.Task | None = None
        self._polling_active = False
        self._last_update_id = 0

    @property
    def delivery(self) -> TelegramDelivery:
        if self._delivery is None:
            bot_token = settings.delivery.telegram_bot_token or "unconfigured"
            chat_id = settings.delivery.telegram_chat_id or "unconfigured"
            self._delivery = TelegramDelivery(
                config={
                    "bot_token": bot_token,
                    "chat_id": chat_id,
                }
            )
        return self._delivery

    @delivery.setter
    def delivery(self, val: TelegramDelivery) -> None:
        self._delivery = val

    async def handle_update(self, update: dict[str, Any]) -> dict[str, Any]:
        """Dispatch incoming Telegram update (webhook or poll item)."""
        if "callback_query" in update:
            return await self.handle_callback_query(update["callback_query"])
        return {"status": "ignored", "reason": "No callback_query in update"}

    async def handle_callback_query(
        self, callback_query: dict[str, Any]
    ) -> dict[str, Any]:
        """Process an interactive inline button callback.

        Enforces:
        - Chat ID / User ID authorization guard.
        - Compact action prefix dispatch (< 64 bytes callback_data).
        - State toggles for Vault, Dismiss, and Source Mute.
        - Non-blocking execution for Deep Triage.
        """
        query_id = callback_query.get("id", "")
        data = callback_query.get("data", "")
        from_user = callback_query.get("from", {})
        user_id = from_user.get("id")

        # 1. Authorization Guard
        allowed_user_id = settings.delivery.telegram_allowed_user_id
        if allowed_user_id and user_id != allowed_user_id:
            logger.warning(
                f"Unauthorized Telegram callback query from user_id={user_id}"
            )
            await self.delivery.answer_callback_query(
                query_id,
                text="⛔ Unauthorized: Actions restricted to tracker owner.",
                show_alert=True,
            )
            return {"status": "unauthorized", "user_id": user_id}

        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        original_text = message.get("text", "")

        if not data or ":" not in data:
            await self.delivery.answer_callback_query(query_id)
            return {"status": "noop"}

        action, target = data.split(":", 1)

        # 2. Vault Actions (v: / uv:)
        if action in ("v", "uv"):
            entry_id = _parse_entry_uuid(target)
            if not entry_id:
                await self.delivery.answer_callback_query(
                    query_id, text="⚠️ Invalid entry ID"
                )
                return {"status": "error", "error": "invalid_id"}

            is_vaulting = action == "v"
            async with SqlAlchemyUnitOfWork() as uow:
                entry = await uow.entries.get(entry_id, include_purged=True)
                if not entry:
                    await self.delivery.answer_callback_query(
                        query_id, text="⚠️ Entry not found"
                    )
                    return {"status": "not_found"}

                await uow.entries.toggle_importance(entry.id, is_important=is_vaulting)
                await uow.commit()

            # Refresh live vector centroid with new feedback
            await vault_feedback_service.refresh_profile(force=True)

            toast = (
                "⭐ Saved to Vault & interest vector updated!"
                if is_vaulting
                else "↩️ Unvaulted & interest vector updated!"
            )
            await self.delivery.answer_callback_query(query_id, text=toast)

            # Update inline button state in-place
            new_kb = build_entry_inline_keyboard(
                entry.id, entry.source_id, is_vaulted=is_vaulting
            )
            if chat_id and message_id:
                await self.delivery.edit_message_reply_markup(
                    chat_id, message_id, new_kb
                )

            return {
                "status": "success",
                "action": "vault" if is_vaulting else "unvault",
                "entry_id": str(entry_id),
            }

        # 3. Dismiss Actions (x: / ux:)
        if action in ("x", "ux"):
            entry_id = _parse_entry_uuid(target)
            if not entry_id:
                await self.delivery.answer_callback_query(
                    query_id, text="⚠️ Invalid entry ID"
                )
                return {"status": "error", "error": "invalid_id"}

            is_dismissing = action == "x"
            async with SqlAlchemyUnitOfWork() as uow:
                entry = await uow.entries.get(entry_id, include_purged=True)
                if not entry:
                    await self.delivery.answer_callback_query(
                        query_id, text="⚠️ Entry not found"
                    )
                    return {"status": "not_found"}

                if is_dismissing:
                    await uow.entries.delete(entry.id, hard_delete=False)
                else:
                    await uow.entries.restore_entry(entry.id)
                await uow.commit()

            await vault_feedback_service.refresh_profile(force=True)

            toast = (
                "❌ Dismissed & negative centroid updated."
                if is_dismissing
                else "↩️ Entry restored & centroid updated."
            )
            await self.delivery.answer_callback_query(query_id, text=toast)

            new_kb = build_entry_inline_keyboard(
                entry.id, entry.source_id, is_dismissed=is_dismissing
            )
            if chat_id and message_id:
                await self.delivery.edit_message_reply_markup(
                    chat_id, message_id, new_kb
                )

            return {
                "status": "success",
                "action": "dismiss" if is_dismissing else "undismiss",
                "entry_id": str(entry_id),
            }

        # 4. Deep Triage Action (d:)
        if action == "d":
            entry_id = _parse_entry_uuid(target)
            if not entry_id:
                await self.delivery.answer_callback_query(
                    query_id, text="⚠️ Invalid entry ID"
                )
                return {"status": "error", "error": "invalid_id"}

            # Answer callback immediately (< 500ms) to clear the Telegram spinner
            await self.delivery.answer_callback_query(
                query_id, text="🔍 Running Deep Analysis via Ollama..."
            )

            # Swap button to analyzing spinner
            temp_kb = build_entry_inline_keyboard(entry_id, is_analyzing=True)
            if chat_id and message_id:
                await self.delivery.edit_message_reply_markup(
                    chat_id, message_id, temp_kb
                )

            # Launch analysis in non-blocking task with fresh UnitOfWork
            asyncio.create_task(
                self._run_deep_triage_background(
                    entry_id, chat_id, message_id, original_text
                )
            )

            return {
                "status": "enqueued",
                "action": "deep_triage",
                "entry_id": str(entry_id),
            }

        # 5. Mute Source Actions (m: / um:)
        if action in ("m", "um"):
            is_muting = action == "m"
            source_slug = target[:40]

            async with SqlAlchemyUnitOfWork() as uow:
                success = await uow.sources.toggle_enabled(
                    source_slug, enabled=not is_muting
                )
                await uow.commit()

            toast = (
                f"🔇 Source '{source_slug}' muted."
                if is_muting
                else f"🔈 Source '{source_slug}' unmuted."
            )
            await self.delivery.answer_callback_query(query_id, text=toast)

            if chat_id and message_id:
                # Toggle keyboard state
                kb = build_entry_inline_keyboard(
                    UUID(int=0), source_id=source_slug, is_muted=is_muting
                )
                await self.delivery.edit_message_reply_markup(chat_id, message_id, kb)

            return {
                "status": "success",
                "action": "mute" if is_muting else "unmute",
                "source": source_slug,
                "found": success,
            }

        # Default no-op
        await self.delivery.answer_callback_query(query_id)
        return {"status": "noop"}

    async def _run_deep_triage_background(
        self,
        entry_id: UUID,
        chat_id: int | str | None,
        message_id: int | None,
        original_text: str,
    ) -> None:
        """Run deep autonomous triage in a fresh Unit-of-Work context and edit message in-place."""
        try:
            # Instantiate FRESH UnitOfWork inside background coroutine
            async with SqlAlchemyUnitOfWork() as uow:
                entry = await uow.entries.get(entry_id, include_purged=True)
                if not entry:
                    logger.warning(
                        f"Deep triage background worker: entry {entry_id} not found"
                    )
                    return

                from ai_security_monitor.application.services.decision_brief_service import (
                    decision_brief_service,
                )

                brief = await decision_brief_service.get_or_generate_brief(
                    entry, uow=uow, force=True
                )

                existing_analysis = await uow.analysis.get_by_entry(entry.id)
                if not existing_analysis:
                    analysis = Analysis(
                        entry_id=entry.id,
                        attack_vector=entry.title[:100],
                        risk_assessment=brief.significance[:250],
                        mitigation=brief.action_rationale[:250],
                        threat_velocity=75,
                        severity_index=70,
                        blast_radius_score=65,
                        affected_ecosystem=brief.stack_relevance.matched_technologies or ["AI Ecosystem"],
                        attack_archetype="Decision Intelligence",
                        weaponization_potential="Production Ready",
                        decision_brief=brief.to_dict(),
                    )
                    await uow.analysis.add(analysis)
                    await uow.commit()

            # Append structured decision brief to message text with HTML escaping & length clamp
            action_icon = {
                "TEST_IN_SANDBOX": "🧪",
                "UPGRADE_DEPENDENCY": "⚡",
                "READ_PAPER": "📄",
                "MONITOR_CLAIMS": "🔭",
                "IGNORE_HYPE": "💤",
            }.get(brief.recommended_action.value, "📌")

            conf_icon = {
                "VERIFIED": "✅",
                "SUPPORTED": "🔹",
                "PRELIMINARY": "⚠️",
                "CONTRADICTED": "❌",
                "INSUFFICIENT_EVIDENCE": "❓",
            }.get(brief.evidence_assessment.confidence.value, "🔍")

            impact_badge = brief.stack_relevance.impact_level.value
            tech_str = ", ".join(brief.stack_relevance.matched_technologies[:3]) or "General Ecosystem"
            event_clean = html.escape(brief.event_summary[:200])
            sig_clean = html.escape(brief.significance[:160])
            novel_clean = html.escape(brief.novelty_assessment.summary[:130])
            rationale_clean = html.escape(brief.action_rationale[:140])

            decision_block = (
                f"\n\n<b>🎯 DECISION BRIEF:</b>\n"
                f"• <b>What Happened:</b> {event_clean}\n"
                f"• <b>Why It Matters:</b> {sig_clean}\n"
                f"• <b>What's New:</b> [{brief.novelty_assessment.novelty_type.value}] {novel_clean}\n"
                f"• <b>My Stack Impact:</b> [{impact_badge}] {tech_str}\n"
                f"• <b>Next Action:</b> {action_icon} <code>{brief.recommended_action.value}</code>\n"
                f"  <i>↳ {rationale_clean}</i>\n"
                f"• <b>Evidence:</b> {conf_icon} {brief.evidence_assessment.confidence.value}"
            )

            new_text = original_text + decision_block
            final_kb = build_entry_inline_keyboard(
                entry_id, entry.source_id, is_analyzing=False
            )

            if chat_id and message_id:
                await self.delivery.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=new_text,
                    reply_markup=final_kb,
                )
                logger.info(
                    f"Completed deep triage edit for entry {entry_id} in Telegram message {message_id}"
                )

        except Exception as e:
            logger.error(f"Background deep triage failed for entry {entry_id}: {e}")
            if chat_id and message_id:
                reset_kb = build_entry_inline_keyboard(entry_id)
                await self.delivery.edit_message_reply_markup(
                    chat_id, message_id, reset_kb
                )

    async def start_polling(self) -> None:
        """Start async getUpdates long-polling loop (for local/Tailscale deployments)."""
        if self._polling_active:
            return

        bot_token = settings.delivery.telegram_bot_token
        if not bot_token:
            logger.debug("Telegram bot token not configured; skipping long-polling")
            return

        self._polling_active = True

        # Polling Conflict Guard: deleteWebhook to clear any stale webhook registrations
        logger.info(
            "Deleting any pre-existing Telegram webhook before starting polling loop..."
        )
        await self.delivery.delete_webhook(drop_pending_updates=False)

        self._polling_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Internal worker loop for Telegram long-polling."""
        logger.info(
            f"Telegram ChatOps long-polling loop active (timeout=20s, offset={self._last_update_id})..."
        )

        while self._polling_active:
            try:
                updates = await self.delivery.get_updates(
                    offset=self._last_update_id + 1, timeout=20
                )
                for update in updates:
                    update_id = update.get("update_id", 0)
                    self._last_update_id = max(self._last_update_id, update_id)
                    await self.handle_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram polling update error: {e}")
                await asyncio.sleep(5)

        logger.info("Telegram ChatOps long-polling loop terminated.")

    async def stop_polling(self) -> None:
        """Cleanly terminate long-polling loop."""
        self._polling_active = False
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass


# Global singleton instance
telegram_chatops_service = TelegramChatOpsService()
