from __future__ import annotations

import asyncio
import html
from pathlib import Path
from uuid import UUID

import httpx

from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.exceptions import DeliveryConfigError
from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
)


def build_entry_inline_keyboard(
    entry_id: UUID | str,
    source_id: UUID | str | None = None,
    is_vaulted: bool = False,
    is_dismissed: bool = False,
    is_muted: bool = False,
    is_analyzing: bool = False,
) -> dict:
    """Build compact, bi-directional inline action keyboard (< 64 bytes callback_data).

    Prefixes:
    - v:<hex32>  -> Star to Vault
    - uv:<hex32> -> Undo Vault
    - d:<hex32>  -> Enqueue for Deep LLM Triage
    - x:<hex32>  -> Soft-purge / Dismiss
    - ux:<hex32> -> Undo Dismiss
    - m:<slug>   -> Mute source feed
    - um:<slug>  -> Unmute source feed
    """
    hex32 = (
        entry_id.hex if isinstance(entry_id, UUID) else str(entry_id).replace("-", "")
    )[:32]

    # Row 1: Vault & Deep Triage
    vault_btn = (
        {"text": "✅ Vaulted (Undo)", "callback_data": f"uv:{hex32}"}
        if is_vaulted
        else {"text": "⭐ Vault", "callback_data": f"v:{hex32}"}
    )
    if is_analyzing:
        triage_btn = {"text": "⏳ Analyzing...", "callback_data": f"noop:{hex32}"}
    else:
        triage_btn = {"text": "📊 Deep Triage", "callback_data": f"d:{hex32}"}

    row1 = [vault_btn, triage_btn]

    # Row 2: Dismiss & Source Mute
    dismiss_btn = (
        {"text": "↩️ Dismissed (Undo)", "callback_data": f"ux:{hex32}"}
        if is_dismissed
        else {"text": "❌ Dismiss", "callback_data": f"x:{hex32}"}
    )
    row2 = [dismiss_btn]

    if source_id:
        src_str = (
            source_id.hex
            if isinstance(source_id, UUID)
            else str(source_id).replace("-", "")
        )
        src_slug = src_str[:32]
        mute_btn = (
            {"text": "🔈 Unmute Source", "callback_data": f"um:{src_slug}"}
            if is_muted
            else {"text": "🔇 Mute Source", "callback_data": f"m:{src_slug}"}
        )
        row2.append(mute_btn)

    return {"inline_keyboard": [row1, row2]}


def build_quarantine_inline_keyboard(source_id: str | UUID) -> dict:
    """Build inline keyboard for a quarantined source diagnostic alert.

    Prefix:
    - uq:<slug> -> Unquarantine and reset source failure count
    """
    slug = (
        source_id.hex if isinstance(source_id, UUID) else str(source_id).strip()
    )[:40]
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🔄 Retry & Unquarantine Source",
                    "callback_data": f"uq:{slug}",
                }
            ]
        ]
    }


class TelegramDelivery(BaseDelivery):
    """Telegram delivery via Bot API supporting two-way inline ChatOps callbacks."""

    @property
    def channel_name(self) -> str:
        return "telegram"

    def validate_config(self) -> None:
        required = ["bot_token", "chat_id"]
        missing = [k for k in required if not self.config.get(k)]
        if missing:
            raise DeliveryConfigError(self.channel_name, missing)

    async def send_digest(
        self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]
    ) -> DeliveryResult:
        """Send digest to Telegram."""
        try:
            message = self._build_message(digest, entries_with_analysis)
            await self._send_message(message)

            await self._publish_delivery_event(digest.id, True)
            return DeliveryResult(
                success=True, channel=self.channel_name, message="Telegram message sent"
            )

        except Exception as e:
            await self._publish_delivery_event(digest.id, False, str(e))
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )

    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send high-priority alert with interactive ChatOps inline keyboard."""
        try:
            message = (
                f"🚨 <b>Worldwide AI Intelligence Alert</b>\n\n"
                f"<b>Title:</b> {self._escape_html(entry.title)}\n"
                f'<b>URL:</b> <a href="{entry.url}">Link</a>\n'
                f"<b>Velocity:</b> {analysis.threat_velocity}/100\n"
                f"<b>Severity:</b> {analysis.severity_index}/100\n"
                f"<b>Archetype:</b> {self._escape_html(analysis.attack_archetype)} ({self._escape_html(analysis.weaponization_potential)})\n"
                f"<b>Vector:</b> {self._escape_html(analysis.attack_vector)}\n"
                f"<b>Summary:</b> {self._escape_html(entry.summary[:280])}"
            )
            keyboard = build_entry_inline_keyboard(entry.id, entry.source_id)
            await self._send_message(message, reply_markup=keyboard)
            return DeliveryResult(
                success=True, channel=self.channel_name, message="Telegram alert sent"
            )
        except Exception as e:
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )

    async def send_entry_dispatch(
        self, entry: Entry, analysis: Analysis | None = None
    ) -> DeliveryResult:
        """Send single intelligence entry dispatch with interactive ChatOps inline keyboard."""
        try:
            text = (
                f"🌐 <b>AI Ecosystem Intelligence Dispatch</b>\n\n"
                f"<b>Title:</b> {self._escape_html(entry.title)}\n"
                f'<b>URL:</b> <a href="{entry.url}">{self._escape_html(entry.url)}</a>\n'
                f"<b>Category:</b> {entry.category.value if hasattr(entry.category, 'value') else str(entry.category)}\n"
                f"<b>Summary:</b> {self._escape_html(entry.summary[:320])}"
            )
            keyboard = build_entry_inline_keyboard(entry.id, entry.source_id)
            await self._send_message(text, reply_markup=keyboard)
            return DeliveryResult(
                success=True,
                channel=self.channel_name,
                message="Telegram entry dispatch sent",
            )
        except Exception as e:
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> bool:
        """Immediately acknowledge Telegram callback query to dismiss mobile spinner."""
        bot_token = self.config.get("bot_token")
        if not bot_token:
            return False

        url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception:
            return False

    async def edit_message_reply_markup(
        self, chat_id: int | str, message_id: int, reply_markup: dict
    ) -> bool:
        """Update inline keyboard on an existing message in-place (e.g. toggle undo state)."""
        bot_token = self.config.get("bot_token")
        if not bot_token:
            return False

        url = f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 400 and "message is not modified" in res.text:
                    return True  # Idempotent no-op
                res.raise_for_status()
                return True
        except Exception:
            return False

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> bool:
        """Update message text and optionally inline keyboard (e.g. append deep triage verdict)."""
        bot_token = self.config.get("bot_token")
        if not bot_token:
            return False

        # Guard against Telegram 4096-char message length limit
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>...[truncated to Telegram 4096-char limit]</i>"

        url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 400 and "message is not modified" in res.text:
                    return True
                res.raise_for_status()
                return True
        except Exception:
            return False

    async def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """Remove any active webhook to prevent 409 Conflict during long-polling."""
        bot_token = self.config.get("bot_token")
        if not bot_token:
            return False

        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(
                    url, json={"drop_pending_updates": drop_pending_updates}
                )
                return res.status_code == 200
        except Exception:
            return False

    async def get_updates(
        self, offset: int | None = None, timeout: int = 20
    ) -> list[dict]:
        """Fetch incoming updates via long-polling (getUpdates)."""
        bot_token = self.config.get("bot_token")
        if not bot_token:
            return []

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        payload: dict = {
            "timeout": timeout,
            "allowed_updates": ["callback_query", "message"],
        }
        if offset is not None:
            payload["offset"] = offset

        try:
            async with httpx.AsyncClient(timeout=timeout + 10) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("result", [])
                return []
        except Exception:
            return []

    async def send_newspaper_document(
        self,
        pdf_path: str | Path,
        edition_number: int,
        lead_story: str = "",
        total_threats: int = 0,
    ) -> DeliveryResult:
        """Send the 5-hour newspaper PDF edition as a document via Telegram Bot API."""
        try:
            bot_token = self.config.get("bot_token")
            chat_id = self.config.get("chat_id")

            if not bot_token or not chat_id:
                return DeliveryResult(
                    success=False,
                    channel=self.channel_name,
                    error="Telegram bot_token or chat_id is missing.",
                )

            p_path = Path(pdf_path)
            pdf_exists = await asyncio.to_thread(p_path.exists)
            if not pdf_exists:
                return DeliveryResult(
                    success=False,
                    channel=self.channel_name,
                    error=f"PDF file not found at {pdf_path}",
                )

            caption = (
                f"📰 <b>The Global AI Gazette — Edition #{edition_number}</b>\n\n"
                f"🚨 <b>Lead Story:</b> {self._escape_html(lead_story or 'Worldwide AI Intelligence Dispatch')}\n"
                f"📊 <b>Stories Analyzed:</b> {total_threats}\n"
                f"🌐 <i>10-Page Autonomous Worldwide AI Broadsheet attached in PDF.</i>"
            )

            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            pdf_bytes = await asyncio.to_thread(p_path.read_bytes)
            async with httpx.AsyncClient(timeout=45) as client:
                files = {
                    "document": (
                        f"Global_AI_Gazette_Edition_{edition_number}.pdf",
                        pdf_bytes,
                        "application/pdf",
                    )
                }
                data = {
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                }
                response = await client.post(url, data=data, files=files)
                response.raise_for_status()

            return DeliveryResult(
                success=True,
                channel=self.channel_name,
                message=f"Newspaper PDF Edition #{edition_number} delivered to Telegram chat {chat_id}",
            )
        except Exception as e:
            return DeliveryResult(
                success=False, channel=self.channel_name, error=str(e)
            )

    async def send_message(
        self, text: str, reply_markup: dict | None = None
    ) -> dict | None:
        """Send message via Telegram Bot API with optional reply_markup."""
        return await self._send_message(text=text, reply_markup=reply_markup)

    async def _send_message(
        self, text: str, reply_markup: dict | None = None
    ) -> dict | None:
        """Send message via Telegram Bot API with optional reply_markup."""
        url = f"https://api.telegram.org/bot{self.config['bot_token']}/sendMessage"
        payload: dict = {
            "chat_id": self.config["chat_id"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    def _build_message(
        self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]
    ) -> str:
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
            cat_entries = [
                (e, a) for e, a in entries_with_analysis if e.category.value == category
            ]
            if not cat_entries:
                continue

            cat_header = (
                f"📂 <b>{category.replace('_', ' ').title()}</b> ({len(cat_entries)})\n"
            )
            cat_parts = [cat_header]

            for entry, analysis in cat_entries[:3]:
                item = f'• <a href="{entry.url}">{self._escape_html(entry.title)}</a>'
                if analysis:
                    item += f"\n  ⚡ {analysis.threat_velocity}/100 | ⚠️ {analysis.severity_index}/100"
                    if analysis.is_pre_cve_warning:
                        item += " 🚨 <b>PRE-CVE</b>"
                    item += f"\n  🎯 {self._escape_html(analysis.attack_archetype)} ({self._escape_html(analysis.weaponization_potential)})"
                    item += (
                        f"\n  💥 {', '.join(analysis.affected_ecosystem[:3]) or 'N/A'}"
                    )
                cat_parts.append(item)

            if len(cat_entries) > 3:
                cat_parts.append(f"  ... and {len(cat_entries) - 3} more")

            parts.append("\n".join(cat_parts) + "\n")

        full_message = "\n".join(parts)
        if len(full_message) > 4000:
            full_message = full_message[:3950] + "\n\n<i>...truncated</i>"

        return full_message

    def _escape_html(self, text: str) -> str:
        return html.escape(str(text or ""), quote=False)


delivery_registry.register("telegram", TelegramDelivery)
