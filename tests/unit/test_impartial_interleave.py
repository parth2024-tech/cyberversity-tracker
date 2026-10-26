"""Unit tests for the Feed Impartiality and Source Diversity Interleaver."""

from __future__ import annotations

from ai_security_monitor.presentation.api.routers.entries import interleave_impartial


def test_interleave_impartial_empty_and_short():
    """Empty or short lists below max_consecutive should return unchanged."""
    assert interleave_impartial([]) == []
    single = [{"id": "1", "source_name": "Source A"}]
    assert interleave_impartial(single, max_consecutive=2) == single


def test_interleave_impartial_prevents_single_source_monopoly():
    """Dominant source should not appear more than max_consecutive times in succession when alternatives exist."""
    items = [
        {"id": "a1", "source_name": "Source A"},
        {"id": "a2", "source_name": "Source A"},
        {"id": "a3", "source_name": "Source A"},
        {"id": "a4", "source_name": "Source A"},
        {"id": "b1", "source_name": "Source B"},
        {"id": "c1", "source_name": "Source C"},
    ]

    interleaved = interleave_impartial(items, max_consecutive=2)

    assert len(interleaved) == len(items)

    # Check that in the interleaved list, before other sources are exhausted,
    # Source A never appears 3 times consecutively
    consecutive = 0
    last_src = None
    for item in interleaved[:4]:
        src = item["source_name"]
        if src == last_src:
            consecutive += 1
        else:
            last_src = src
            consecutive = 1
        assert consecutive <= 2

    # Specifically, b1 should be pulled forward to break a1, a2 streak before a3
    seq = [x["id"] for x in interleaved]
    assert seq == ["a1", "a2", "b1", "a3", "a4", "c1"]


def test_interleave_impartial_graceful_drain_when_single_source_left():
    """When other sources run out, remaining items from the dominant source are drained cleanly."""
    items = [
        {"id": "a1", "source_name": "Source A"},
        {"id": "a2", "source_name": "Source A"},
        {"id": "a3", "source_name": "Source A"},
        {"id": "a4", "source_name": "Source A"},
        {"id": "b1", "source_name": "Source B"},
    ]

    interleaved = interleave_impartial(items, max_consecutive=2)
    seq = [x["id"] for x in interleaved]
    assert seq == ["a1", "a2", "b1", "a3", "a4"]
