"""Unit tests for Feature 8: Benchmark and Leaderboard Tracking.

Verifies:
1. Parsers: LMSYS Chatbot Arena and Open LLM Leaderboard parsing with fixtures.
2. Error resilience: Corrupted payload / schema layout changes raise LeaderboardParseError and update status to BROKEN.
3. Diff Engine: Accurately detects:
   - New #1 SOTA shifts (model dethroning previous leader)
   - Rank surges >= 3 (e.g. +4 spots)
   - Rank drops >= 3 (e.g. -3 spots)
   - New entrants in Top 20
   - Filters out minor noise (rank delta 1 or 2).
4. Entry Generation: Formats authoritative pipeline entries with metadata and hashes.
5. End-to-end service polling and snapshot persistence.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from ai_security_monitor.application.services.leaderboard_service import (
    LeaderboardDiffEngine,
    LeaderboardParseError,
    LeaderboardService,
    LMSYSArenaParser,
    OpenLLMLeaderboardParser,
)
from ai_security_monitor.domain.entities import Category, Leaderboard
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork

# ---------------------------------------------------------------------------
# Fixture Data
# ---------------------------------------------------------------------------

SAMPLE_LMSYS_PAYLOAD = {
    "leaderboard": [
        {
            "rank": 1,
            "model": "gpt-4o-2024-05-13",
            "rating": 1286,
            "organization": "OpenAI",
        },
        {
            "rank": 2,
            "model": "claude-3-5-sonnet-20240620",
            "rating": 1283,
            "organization": "Anthropic",
        },
        {
            "rank": 3,
            "model": "gemini-1.5-pro",
            "rating": 1260,
            "organization": "Google",
        },
        {
            "rank": 4,
            "model": "llama-3.1-405b-instruct",
            "rating": 1255,
            "organization": "Meta",
        },
        {"rank": 5, "model": "deepseek-v3", "rating": 1250, "organization": "DeepSeek"},
        {
            "rank": 6,
            "model": "mistral-large-2",
            "rating": 1245,
            "organization": "Mistral",
        },
    ]
}

SAMPLE_OPEN_LLM_PAYLOAD = [
    {
        "rank": 1,
        "fullname": "meta-llama/Llama-3.3-70B-Instruct",
        "average": 42.15,
        "org": "meta-llama",
    },
    {
        "rank": 2,
        "fullname": "Qwen/Qwen2.5-72B-Instruct",
        "average": 41.80,
        "org": "Qwen",
    },
    {
        "rank": 3,
        "fullname": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "average": 40.50,
        "org": "deepseek-ai",
    },
]


# ---------------------------------------------------------------------------
# Parser Tests
# ---------------------------------------------------------------------------


class TestLeaderboardParsers:
    def test_lmsys_arena_parser_success(self):
        parser = LMSYSArenaParser()
        rows = parser.parse(SAMPLE_LMSYS_PAYLOAD)

        assert len(rows) == 6
        assert rows[0]["rank"] == 1
        assert rows[0]["model"] == "gpt-4o-2024-05-13"
        assert rows[0]["score"] == 1286
        assert rows[0]["org"] == "OpenAI"

        assert rows[4]["rank"] == 5
        assert rows[4]["model"] == "deepseek-v3"

    def test_open_llm_parser_success(self):
        parser = OpenLLMLeaderboardParser()
        rows = parser.parse(SAMPLE_OPEN_LLM_PAYLOAD)

        assert len(rows) == 3
        assert rows[0]["rank"] == 1
        assert rows[0]["model"] == "meta-llama/Llama-3.3-70B-Instruct"
        assert rows[0]["score"] == 42.15
        assert rows[0]["org"] == "meta-llama"

    def test_corrupt_payload_raises_parse_error(self):
        parser = LMSYSArenaParser()

        with pytest.raises(LeaderboardParseError):
            parser.parse("<html>Not JSON</html>")

        with pytest.raises(LeaderboardParseError):
            parser.parse({"unexpected_key": 123})

        with pytest.raises(LeaderboardParseError):
            parser.parse([])


# ---------------------------------------------------------------------------
# Diff Engine Tests
# ---------------------------------------------------------------------------


class TestLeaderboardDiffEngine:
    def test_diff_engine_detects_sota_shift_surges_and_entrants(self):
        engine = LeaderboardDiffEngine()

        snapshot_a_rows = [
            {"rank": 1, "model": "gpt-4o", "score": 1286, "org": "OpenAI"},
            {
                "rank": 2,
                "model": "claude-3-5-sonnet",
                "score": 1283,
                "org": "Anthropic",
            },
            {"rank": 3, "model": "gemini-1.5-pro", "score": 1260, "org": "Google"},
            {"rank": 4, "model": "llama-3.1-405b", "score": 1255, "org": "Meta"},
            {"rank": 5, "model": "deepseek-v3", "score": 1250, "org": "DeepSeek"},
            {"rank": 6, "model": "mistral-large-2", "score": 1245, "org": "Mistral"},
        ]

        # Snapshot B:
        # - deepseek-v3 jumps from #5 to #1 (New #1 SOTA shift)
        # - qwen-2.5-72b debuts at #4 (New Entrant in Top 20)
        # - mistral-large-2 drops from #6 to #9 (Rank Drop -3)
        # - gpt-4o drops #1 -> #2 (minor move -1, ignored)
        # - claude drops #2 -> #3 (minor move -1, ignored)
        # - gemini drops #3 -> #5 (minor move -2, ignored)
        # - llama drops #4 -> #6 (minor move -2, ignored)
        snapshot_b_rows = [
            {"rank": 1, "model": "deepseek-v3", "score": 1350, "org": "DeepSeek"},
            {"rank": 2, "model": "gpt-4o", "score": 1286, "org": "OpenAI"},
            {
                "rank": 3,
                "model": "claude-3-5-sonnet",
                "score": 1283,
                "org": "Anthropic",
            },
            {"rank": 4, "model": "qwen-2.5-72b", "score": 1270, "org": "Alibaba"},
            {"rank": 5, "model": "gemini-1.5-pro", "score": 1260, "org": "Google"},
            {"rank": 6, "model": "llama-3.1-405b", "score": 1255, "org": "Meta"},
            {"rank": 9, "model": "mistral-large-2", "score": 1230, "org": "Mistral"},
        ]

        events = engine.compute_diff(
            snapshot_a_rows, snapshot_b_rows, "LMSYS Chatbot Arena"
        )

        event_types = {e.event_type: e for e in events}

        # 1. New #1 event for DeepSeek-V3
        assert "new_number_one" in event_types
        sota_event = event_types["new_number_one"]
        assert sota_event.model == "deepseek-v3"
        assert sota_event.new_rank == 1
        assert sota_event.prev_rank == 5
        assert sota_event.severity == "HIGH"
        assert "dethroning gpt-4o" in sota_event.summary

        # 2. New Entrant event for Qwen-2.5-72B
        assert "new_entrant" in event_types
        entrant_event = event_types["new_entrant"]
        assert entrant_event.model == "qwen-2.5-72b"
        assert entrant_event.new_rank == 4
        assert entrant_event.severity == "HIGH"

        # 3. Rank Drop event for Mistral-Large-2 (fell 3 spots: 6 -> 9)
        assert "rank_drop" in event_types
        drop_event = event_types["rank_drop"]
        assert drop_event.model == "mistral-large-2"
        assert drop_event.new_rank == 9
        assert drop_event.prev_rank == 6
        assert drop_event.rank_delta == -3

        # 4. Assert minor moves were NOT reported (noise filtering)
        models_reported = {e.model for e in events}
        assert "gpt-4o" not in models_reported  # only dropped 1
        assert "claude-3-5-sonnet" not in models_reported  # only dropped 1
        assert "gemini-1.5-pro" not in models_reported  # only dropped 2
        assert "llama-3.1-405b" not in models_reported  # only dropped 2

    def test_identical_snapshots_emit_zero_diff_events(self):
        engine = LeaderboardDiffEngine()
        rows = [
            {"rank": 1, "model": "gpt-4o", "score": 1286},
            {"rank": 2, "model": "claude-3-5", "score": 1283},
        ]
        events = engine.compute_diff(rows, rows, "Arena")
        assert len(events) == 0


# ---------------------------------------------------------------------------
# Entry Generation & Persistence Tests
# ---------------------------------------------------------------------------


class TestLeaderboardService:
    def test_create_entries_from_diff_events(self):
        service = LeaderboardService()
        lb = Leaderboard(
            id=uuid4(),
            name="LMSYS Chatbot Arena",
            url="https://chat.lmsys.org/",
            parser="lmsys_arena",
        )

        engine = LeaderboardDiffEngine()
        snapshot_a = [{"rank": 1, "model": "model-a", "score": 100}]
        snapshot_b = [{"rank": 1, "model": "model-b", "score": 110}]
        events = engine.compute_diff(snapshot_a, snapshot_b, lb.name)

        entries = service.create_entries_from_diff_events(lb, events)

        assert len(entries) == 1
        entry = entries[0]
        assert "[Benchmark SOTA]" in entry.title
        assert "model-b" in entry.title
        assert entry.category == Category.AI_MODELS
        assert entry.metadata["is_leaderboard_event"] is True
        assert entry.metadata["event_type"] == "new_number_one"
        assert len(entry.content_hash) == 64

    @pytest.mark.asyncio
    async def test_poll_leaderboard_end_to_end_with_fixtures(self):
        service = LeaderboardService()

        # 1. Seed leaderboard
        seeded = await service.seed_default_leaderboards()
        assert len(seeded) >= 2
        arena_lb = next(lb for lb in seeded if lb.parser == "lmsys_arena")

        # 2. First Poll (Baseline snapshot)
        snap1, events1 = await service.poll_leaderboard(
            arena_lb.id, fixture_payload=SAMPLE_LMSYS_PAYLOAD
        )
        assert snap1.row_count == 6
        assert len(events1) == 0  # No previous snapshot to diff against

        # 3. Second Poll with significant movements
        modified_payload = {
            "leaderboard": [
                {
                    "rank": 1,
                    "model": "deepseek-v3",
                    "rating": 1350,
                    "organization": "DeepSeek",
                },
                {
                    "rank": 2,
                    "model": "gpt-4o-2024-05-13",
                    "rating": 1286,
                    "organization": "OpenAI",
                },
                {
                    "rank": 3,
                    "model": "claude-3-5-sonnet-20240620",
                    "rating": 1283,
                    "organization": "Anthropic",
                },
                {
                    "rank": 4,
                    "model": "qwen-2.5-72b",
                    "rating": 1270,
                    "organization": "Alibaba",
                },
                {
                    "rank": 5,
                    "model": "gemini-1.5-pro",
                    "rating": 1260,
                    "organization": "Google",
                },
                {
                    "rank": 6,
                    "model": "llama-3.1-405b-instruct",
                    "rating": 1255,
                    "organization": "Meta",
                },
                {
                    "rank": 9,
                    "model": "mistral-large-2",
                    "rating": 1230,
                    "organization": "Mistral",
                },
            ]
        }

        snap2, events2 = await service.poll_leaderboard(
            arena_lb.id, fixture_payload=modified_payload
        )
        assert snap2.row_count == 7
        assert len(events2) >= 3  # New #1, Qwen entrant, Mistral drop

        # Verify database persisted diff events
        async with UnitOfWork() as uow:
            latest = await uow.leaderboards.get_latest_snapshot(arena_lb.id)
            assert latest is not None
            assert latest.id == snap2.id
            assert len(latest.diff_events) == len(events2)

    @pytest.mark.asyncio
    async def test_corrupt_payload_marks_status_broken(self):
        service = LeaderboardService()
        seeded = await service.seed_default_leaderboards()
        arena_lb = next(lb for lb in seeded if lb.parser == "lmsys_arena")

        with pytest.raises(LeaderboardParseError):
            await service.poll_leaderboard(arena_lb.id, fixture_payload="corrupt html")

        # Verify status in database was updated to BROKEN
        async with UnitOfWork() as uow:
            updated_lb = await uow.leaderboards.get(arena_lb.id)
            assert updated_lb is not None
            assert updated_lb.status == "BROKEN"
