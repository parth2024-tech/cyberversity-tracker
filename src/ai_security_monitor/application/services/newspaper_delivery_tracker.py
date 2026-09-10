"""
Persistent delivery state tracking and deduplication for newspaper dispatches.
Prevents duplicate dispatches, enforces cooldown intervals, and maintains an audit log of sent editions.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_STATE_FILE = Path("data/newspapers/delivery_state.json")


class NewspaperDeliveryTracker:
    """Tracks delivered newspaper editions across Telegram, Email, and other channels to prevent duplicates."""

    def __init__(self, state_file: Path | str = DEFAULT_STATE_FILE):
        self._state_file = Path(state_file)
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to read delivery state from {self._state_file}: {e}")
        return {}

    def _save(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to persist delivery state to {self._state_file}: {e}")

    def should_dispatch(
        self,
        channel: str,
        edition_number: int,
        lead_story: str = "",
        min_cooldown_hours: float = 4.0,
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        Evaluate whether an edition is eligible for dispatch.
        Returns (is_allowed, reason_message).
        """
        if force:
            return True, "Dispatch forced by override flag."

        ch_state = self._state.get(channel, {})
        last_edition = ch_state.get("last_sent_edition")
        sent_editions = set(ch_state.get("sent_editions", []))
        last_lead = (ch_state.get("last_lead_story") or "").strip().lower()
        current_lead = (lead_story or "").strip().lower()
        last_sent_at_str = ch_state.get("last_sent_at")

        # 1. Exact edition deduplication
        if edition_number in sent_editions or last_edition == edition_number:
            msg = f"Edition #{edition_number} has already been dispatched to {channel}."
            logger.info(f"Deduplication gate: {msg}")
            return False, msg

        # 2. Lead story identical deduplication (same content generated under different timestamp)
        if current_lead and last_lead and current_lead == last_lead:
            msg = f"Newspaper lead story '{lead_story}' is identical to the last {channel} dispatch."
            logger.info(f"Deduplication gate: {msg}")
            return False, msg

        # 3. Minimum cooldown between automated dispatches
        if last_sent_at_str and min_cooldown_hours > 0:
            try:
                last_sent_at = datetime.fromisoformat(last_sent_at_str)
                if last_sent_at.tzinfo is None:
                    last_sent_at = last_sent_at.replace(tzinfo=UTC)
                now = datetime.now(UTC)
                elapsed_hours = (now - last_sent_at).total_seconds() / 3600.0
                if elapsed_hours < min_cooldown_hours:
                    remaining_min = int((min_cooldown_hours - elapsed_hours) * 60)
                    msg = (
                        f"Cooldown active for {channel}: only {elapsed_hours:.1f}h elapsed since last dispatch "
                        f"(minimum interval: {min_cooldown_hours}h, {remaining_min}m remaining)."
                    )
                    logger.info(f"Deduplication gate: {msg}")
                    return False, msg
            except Exception as e:
                logger.warning(f"Error parsing last_sent_at '{last_sent_at_str}': {e}")

        return True, "Eligible for dispatch."

    def record_dispatch(
        self,
        channel: str,
        edition_number: int,
        lead_story: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record successful dispatch of an edition."""
        now = datetime.now(UTC)
        if channel not in self._state:
            self._state[channel] = {
                "last_sent_edition": None,
                "last_sent_at": None,
                "last_lead_story": None,
                "sent_editions": [],
                "history": [],
            }

        ch_state = self._state[channel]
        ch_state["last_sent_edition"] = edition_number
        ch_state["last_sent_at"] = now.isoformat()
        ch_state["last_lead_story"] = lead_story

        sent_list = ch_state.setdefault("sent_editions", [])
        if edition_number not in sent_list:
            sent_list.append(edition_number)

        history = ch_state.setdefault("history", [])
        history.append({
            "edition_number": edition_number,
            "dispatched_at": now.isoformat(),
            "lead_story": lead_story,
            "details": details or {},
        })
        # Keep recent 50 history entries
        if len(history) > 50:
            ch_state["history"] = history[-50:]

        self._save()
        logger.info(f"Recorded successful dispatch of Edition #{edition_number} to {channel}")

    def get_channel_state(self, channel: str) -> dict[str, Any]:
        """Retrieve delivery state for a specific channel."""
        return self._state.get(channel, {})


# Global singleton instance
delivery_tracker = NewspaperDeliveryTracker()
