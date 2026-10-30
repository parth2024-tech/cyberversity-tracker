"""
AI Benchmark and Leaderboard Tracking Service (Feature 8).
Polls structured leaderboards, captures daily ranking snapshots, detects significant
movements (new #1, rank moves >= 3, new top-20 entrants), and generates pipeline entries.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import (
    Category,
    DiffEvent,
    Entry,
    Leaderboard,
    LeaderboardSnapshot,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork

logger = get_logger(__name__)


class LeaderboardParseError(Exception):
    """Raised when a leaderboard response cannot be parsed or layout changed."""


class BaseLeaderboardParser(ABC):
    """Abstract parser for converting raw leaderboard responses to normalized rows."""

    @abstractmethod
    def parse(self, raw_data: Any) -> list[dict[str, Any]]:
        """Parse raw HTTP response (JSON / text) into normalized ranking rows:

        Format of each row:
        {
            "rank": int,
            "model": str,
            "score": float | str | None,
            "org": str | None,
            "details": dict[str, Any]
        }
        """
        ...


class LMSYSArenaParser(BaseLeaderboardParser):
    """Parser for LMSYS Chatbot Arena leaderboards."""

    def parse(self, raw_data: Any) -> list[dict[str, Any]]:
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except Exception as exc:
                raise LeaderboardParseError(
                    f"Invalid JSON for LMSYS Arena: {exc}"
                ) from exc
        else:
            data = raw_data

        rows: list[dict[str, Any]] = []

        # Handle list of model objects or dict with 'data'/'leaderboard'
        items = (
            data.get("leaderboard", data.get("data", data))
            if isinstance(data, dict)
            else data
        )
        if not isinstance(items, list):
            raise LeaderboardParseError(
                "LMSYS Arena data does not contain a list of models"
            )

        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            model_name = (
                item.get("model")
                or item.get("Model")
                or item.get("key")
                or item.get("name")
            )
            if not model_name:
                continue

            rank_val = item.get("rank") or item.get("Rank") or idx
            try:
                rank_int = int(rank_val)
            except (ValueError, TypeError):
                rank_int = idx

            score_val = (
                item.get("arena_score")
                or item.get("rating")
                or item.get("Arena Score")
                or item.get("score")
            )
            org_val = item.get("organization") or item.get("org") or item.get("License")

            rows.append(
                {
                    "rank": rank_int,
                    "model": str(model_name).strip(),
                    "score": score_val,
                    "org": str(org_val).strip() if org_val else None,
                    "details": item,
                }
            )

        if not rows:
            raise LeaderboardParseError("LMSYS Arena parser found 0 valid model rows")

        # Ensure sorted by rank
        rows.sort(key=lambda r: r["rank"])
        return rows


class OpenLLMLeaderboardParser(BaseLeaderboardParser):
    """Parser for Hugging Face Open LLM Leaderboard v2."""

    def parse(self, raw_data: Any) -> list[dict[str, Any]]:
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except Exception as exc:
                raise LeaderboardParseError(
                    f"Invalid JSON for Open LLM: {exc}"
                ) from exc
        else:
            data = raw_data

        rows: list[dict[str, Any]] = []
        items = (
            data.get("leaderboard", data.get("data", data))
            if isinstance(data, dict)
            else data
        )
        if not isinstance(items, list):
            raise LeaderboardParseError(
                "Open LLM data does not contain a list of models"
            )

        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            model_name = (
                item.get("fullname")
                or item.get("model")
                or item.get("Model")
                or item.get("name")
            )
            if not model_name:
                continue

            rank_val = item.get("rank") or item.get("Rank") or idx
            try:
                rank_int = int(rank_val)
            except (ValueError, TypeError):
                rank_int = idx

            score_val = (
                item.get("average")
                or item.get("Average")
                or item.get("eval_score")
                or item.get("score")
            )
            org_val = item.get("org") or item.get("organization") or item.get("Author")

            rows.append(
                {
                    "rank": rank_int,
                    "model": str(model_name).strip(),
                    "score": score_val,
                    "org": str(org_val).strip() if org_val else None,
                    "details": item,
                }
            )

        if not rows:
            raise LeaderboardParseError("Open LLM parser found 0 valid model rows")

        rows.sort(key=lambda r: r["rank"])
        return rows


class LeaderboardDiffEngine:
    """Detects new SOTA leaders (#1), rank moves >= 3, and new top-20 entrants."""

    @staticmethod
    def normalize_model_key(model_name: str) -> str:
        """Normalize model name for robust cross-snapshot identification."""
        return model_name.strip().lower()

    def compute_diff(
        self,
        prev_rows: list[dict[str, Any]],
        curr_rows: list[dict[str, Any]],
        leaderboard_name: str = "Leaderboard",
    ) -> list[DiffEvent]:
        """Compute significant diff events between previous snapshot and current snapshot."""
        if not curr_rows or not prev_rows:
            return []

        events: list[DiffEvent] = []

        # Map previous models: key -> (rank, row)
        prev_map: dict[str, tuple[int, dict[str, Any]]] = {}
        for r in prev_rows:
            key = self.normalize_model_key(r.get("model", ""))
            if key:
                prev_map[key] = (r.get("rank", 9999), r)

        # 1. Check for New #1 (SOTA shift)
        curr_rank_1 = next((r for r in curr_rows if r.get("rank") == 1), None)
        prev_rank_1 = next((r for r in prev_rows if r.get("rank") == 1), None)

        if curr_rank_1 and prev_rank_1:
            curr_model_1 = self.normalize_model_key(curr_rank_1.get("model", ""))
            prev_model_1 = self.normalize_model_key(prev_rank_1.get("model", ""))

            if curr_model_1 != prev_model_1:
                prev_rank_of_curr = prev_map.get(curr_model_1, (None, None))[0]
                delta = (prev_rank_of_curr - 1) if prev_rank_of_curr else 0
                events.append(
                    DiffEvent(
                        event_type="new_number_one",
                        model=curr_rank_1.get("model", ""),
                        prev_rank=prev_rank_of_curr,
                        new_rank=1,
                        rank_delta=delta,
                        score=curr_rank_1.get("score"),
                        prev_score=prev_rank_1.get("score"),
                        org=curr_rank_1.get("org"),
                        summary=(
                            f"New #1 on {leaderboard_name}: {curr_rank_1.get('model')} claims "
                            f"the top spot with score {curr_rank_1.get('score')} "
                            f"(dethroning {prev_rank_1.get('model')})."
                        ),
                        severity="HIGH",
                    )
                )

        # 2. Check for Rank Surges (>= 3), Drops (<= -3), and New Top-20 Entrants
        for curr in curr_rows:
            model_raw = curr.get("model", "")
            key = self.normalize_model_key(model_raw)
            if not key:
                continue

            curr_rank = curr.get("rank", 9999)
            curr_score = curr.get("score")
            org = curr.get("org")

            if key in prev_map:
                prev_rank, prev_row = prev_map[key]
                prev_score = prev_row.get("score")
                delta = prev_rank - curr_rank  # positive = climbed, negative = dropped

                # Rank moves >= 3
                if delta >= 3:
                    # Skip if already flagged as new_number_one
                    if not (
                        curr_rank == 1
                        and any(
                            e.event_type == "new_number_one" and e.model == model_raw
                            for e in events
                        )
                    ):
                        events.append(
                            DiffEvent(
                                event_type="rank_surge",
                                model=model_raw,
                                prev_rank=prev_rank,
                                new_rank=curr_rank,
                                rank_delta=delta,
                                score=curr_score,
                                prev_score=prev_score,
                                org=org,
                                summary=(
                                    f"Rank surge on {leaderboard_name}: {model_raw} climbed +{delta} spots "
                                    f"from #{prev_rank} to #{curr_rank} (Score: {curr_score})."
                                ),
                                severity="HIGH" if curr_rank <= 10 else "MEDIUM",
                            )
                        )
                elif delta <= -3:
                    events.append(
                        DiffEvent(
                            event_type="rank_drop",
                            model=model_raw,
                            prev_rank=prev_rank,
                            new_rank=curr_rank,
                            rank_delta=delta,
                            score=curr_score,
                            prev_score=prev_score,
                            org=org,
                            summary=(
                                f"Rank drop on {leaderboard_name}: {model_raw} slipped {abs(delta)} spots "
                                f"from #{prev_rank} to #{curr_rank}."
                            ),
                            severity="MEDIUM",
                        )
                    )
            else:
                # Model wasn't in previous snapshot - check if debuted in Top 20
                if curr_rank <= 20:
                    # Skip if already flagged as new_number_one
                    if not any(
                        e.event_type == "new_number_one" and e.model == model_raw
                        for e in events
                    ):
                        events.append(
                            DiffEvent(
                                event_type="new_entrant",
                                model=model_raw,
                                prev_rank=None,
                                new_rank=curr_rank,
                                rank_delta=0,
                                score=curr_score,
                                prev_score=None,
                                org=org,
                                summary=(
                                    f"New entrant in Top 20 on {leaderboard_name}: {model_raw} debuts "
                                    f"at #{curr_rank} with score {curr_score}."
                                ),
                                severity="HIGH",
                            )
                        )

        return events


class LeaderboardService:
    """Manages leaderboard polling, snapshot history, diff computation, and entry generation."""

    DEFAULT_LEADERBOARDS = [
        {
            "name": "LMSYS Chatbot Arena",
            "url": "https://chat.lmsys.org/eval_results.json",
            "parser": "lmsys_arena",
            "category": "general",
        },
        {
            "name": "Hugging Face Open LLM Leaderboard v2",
            "url": "https://huggingface.co/api/spaces/open-llm-leaderboard/open_llm_leaderboard",
            "parser": "open_llm",
            "category": "reasoning_and_knowledge",
        },
    ]

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self._uow_factory = uow_factory or (lambda: UnitOfWork())
        self._http_client = http_client
        self._diff_engine = LeaderboardDiffEngine()
        self._parsers: dict[str, BaseLeaderboardParser] = {
            "lmsys_arena": LMSYSArenaParser(),
            "open_llm": OpenLLMLeaderboardParser(),
        }

    def register_parser(self, name: str, parser: BaseLeaderboardParser) -> None:
        """Register or override a leaderboard parser."""
        self._parsers[name] = parser

    async def seed_default_leaderboards(self) -> list[Leaderboard]:
        """Ensure standard industry leaderboards are tracked in the database."""
        seeded: list[Leaderboard] = []
        async with self._uow_factory() as uow:
            for conf in self.DEFAULT_LEADERBOARDS:
                existing = await uow.leaderboards.get_by_name(conf["name"])
                if not existing:
                    lb = Leaderboard(
                        id=uuid4(),
                        name=conf["name"],
                        url=conf["url"],
                        parser=conf["parser"],
                        category=conf.get("category", "general"),
                        enabled=True,
                        status="OK",
                    )
                    created = await uow.leaderboards.add(lb)
                    seeded.append(created)
                    logger.info(f"Tracked new leaderboard: {lb.name}")
                else:
                    seeded.append(existing)
            await uow.commit()
        return seeded

    async def fetch_leaderboard_data(self, url: str) -> Any:
        """Perform HTTP GET request to fetch remote leaderboard payload."""
        if self._http_client:
            resp = await self._http_client.get(url, timeout=15.0)
            resp.raise_for_status()
            return (
                resp.json()
                if "json" in resp.headers.get("content-type", "")
                else resp.text
            )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return (
                resp.json()
                if "json" in resp.headers.get("content-type", "")
                else resp.text
            )

    def create_entries_from_diff_events(
        self,
        leaderboard: Leaderboard,
        diff_events: list[DiffEvent],
    ) -> list[Entry]:
        """Convert detected significant diff events into standard pipeline entries."""
        entries: list[Entry] = []
        now = datetime.now(UTC)

        for event in diff_events:
            # Format clean, authoritative title
            if event.event_type == "new_number_one":
                title = f"[Benchmark SOTA] {event.model} takes #1 on {leaderboard.name}"
            elif event.event_type == "rank_surge":
                title = f"[Benchmark Surge] {event.model} climbs +{event.rank_delta} to #{event.new_rank} on {leaderboard.name}"
            elif event.event_type == "new_entrant":
                title = f"[Benchmark Entrant] {event.model} enters Top 20 at #{event.new_rank} on {leaderboard.name}"
            elif event.event_type == "rank_drop":
                title = f"[Benchmark Shift] {event.model} drops to #{event.new_rank} on {leaderboard.name}"
            else:
                title = f"[Benchmark Update] {event.model} on {leaderboard.name}"

            # Deterministic content hash for deduplication
            date_str = now.strftime("%Y-%m-%d")
            raw_key = f"{leaderboard.name}:{event.event_type}:{event.model}:{event.new_rank}:{date_str}"
            content_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

            # Canonical link to leaderboard
            url = f"{leaderboard.url}#{event.model.replace(' ', '_')}"

            entry = Entry(
                id=uuid4(),
                source_id=leaderboard.id,
                title=title,
                url=url,
                content_hash=content_hash,
                summary=event.summary,
                category=Category.AI_MODELS,
                published_at=now,
                fetched_at=now,
                metadata={
                    "leaderboard_id": str(leaderboard.id),
                    "leaderboard_name": leaderboard.name,
                    "event_type": event.event_type,
                    "model": event.model,
                    "new_rank": event.new_rank,
                    "prev_rank": event.prev_rank,
                    "rank_delta": event.rank_delta,
                    "score": event.score,
                    "prev_score": event.prev_score,
                    "org": event.org,
                    "severity": event.severity,
                    "is_leaderboard_event": True,
                },
            )
            entries.append(entry)

        return entries

    async def poll_leaderboard(
        self,
        leaderboard_id: UUID,
        fixture_payload: Any = None,
    ) -> tuple[LeaderboardSnapshot, list[DiffEvent]]:
        """Poll a leaderboard, record snapshot, compute diff, and generate entries if changed."""
        async with self._uow_factory() as uow:
            leaderboard = await uow.leaderboards.get(leaderboard_id)
            if not leaderboard:
                raise ValueError(f"Leaderboard {leaderboard_id} not found")

            parser = self._parsers.get(leaderboard.parser)
            if not parser:
                leaderboard.status = "BROKEN"
                await uow.leaderboards.update(leaderboard)
                await uow.commit()
                raise LeaderboardParseError(
                    f"No parser registered for: {leaderboard.parser}"
                )

            # Fetch raw data or use provided fixture
            try:
                raw_data = (
                    fixture_payload
                    if fixture_payload is not None
                    else await self.fetch_leaderboard_data(leaderboard.url)
                )
                rows = parser.parse(raw_data)
                leaderboard.status = "OK"
            except Exception as exc:
                leaderboard.status = "BROKEN"
                await uow.leaderboards.update(leaderboard)
                await uow.commit()
                logger.error(f"Failed polling leaderboard {leaderboard.name}: {exc}")
                raise LeaderboardParseError(
                    f"Polling failure for {leaderboard.name}: {exc}"
                ) from exc

            # Get previous snapshot to compute diff
            prev_snapshot = await uow.leaderboards.get_latest_snapshot(leaderboard_id)
            prev_rows = prev_snapshot.rows if prev_snapshot else []

            # Compute significant diff events
            events = self._diff_engine.compute_diff(
                prev_rows=prev_rows,
                curr_rows=rows,
                leaderboard_name=leaderboard.name,
            )

            # Persist snapshot
            now = datetime.now(UTC)
            snapshot = LeaderboardSnapshot(
                id=uuid4(),
                leaderboard_id=leaderboard_id,
                taken_at=now,
                row_count=len(rows),
                rows=rows,
                diff_events=[
                    {
                        "event_type": e.event_type,
                        "model": e.model,
                        "prev_rank": e.prev_rank,
                        "new_rank": e.new_rank,
                        "rank_delta": e.rank_delta,
                        "score": e.score,
                        "prev_score": e.prev_score,
                        "org": e.org,
                        "summary": e.summary,
                        "severity": e.severity,
                    }
                    for e in events
                ],
            )
            saved_snapshot = await uow.leaderboards.add_snapshot(snapshot)

            # Update leaderboard last snapshot time
            leaderboard.last_snapshot_at = now
            await uow.leaderboards.update(leaderboard)

            # Generate and persist entries for significant diff events
            if events:
                entries = self.create_entries_from_diff_events(leaderboard, events)
                for entry in entries:
                    try:
                        await uow.entries.add(entry)
                    except Exception as exc:
                        logger.warning(
                            f"Could not persist leaderboard entry {entry.title}: {exc}"
                        )

            await uow.commit()
            return saved_snapshot, events

    async def poll_all_enabled(self) -> dict[str, Any]:
        """Poll all enabled leaderboards."""
        results: dict[str, Any] = {"polled": 0, "events_detected": 0, "errors": []}
        async with self._uow_factory() as uow:
            leaderboards = await uow.leaderboards.list(enabled_only=True)

        for lb in leaderboards:
            try:
                _, events = await self.poll_leaderboard(lb.id)
                results["polled"] += 1
                results["events_detected"] += len(events)
            except Exception as exc:
                results["errors"].append({"leaderboard": lb.name, "error": str(exc)})

        return results
