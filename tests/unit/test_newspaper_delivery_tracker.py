"""
Unit tests for NewspaperDeliveryTracker deduplication and cooldown logic.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_security_monitor.application.services.newspaper_delivery_tracker import (
    NewspaperDeliveryTracker,
)


@pytest.fixture
def temp_tracker(tmp_path: Path) -> NewspaperDeliveryTracker:
    state_file = tmp_path / "delivery_state.json"
    return NewspaperDeliveryTracker(state_file=state_file)


def test_first_dispatch_allowed(temp_tracker: NewspaperDeliveryTracker):
    allowed, reason = temp_tracker.should_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Qwen3.8-27B",
        min_cooldown_hours=4.0,
    )
    assert allowed is True
    assert "Eligible" in reason


def test_duplicate_edition_blocked(temp_tracker: NewspaperDeliveryTracker):
    temp_tracker.record_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Qwen3.8-27B",
    )
    # Attempt to send same edition number
    allowed, reason = temp_tracker.should_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Different Story Title",
        min_cooldown_hours=0,
    )
    assert allowed is False
    assert "already been dispatched" in reason


def test_duplicate_lead_story_blocked(temp_tracker: NewspaperDeliveryTracker):
    temp_tracker.record_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="NeuronGuard: Robust LLM Safety Alignment",
    )
    # Attempt to send new edition number with identical lead story
    allowed, reason = temp_tracker.should_dispatch(
        channel="telegram",
        edition_number=2213,
        lead_story="NeuronGuard: Robust LLM Safety Alignment",
        min_cooldown_hours=0,
    )
    assert allowed is False
    assert "identical" in reason


def test_cooldown_enforcement(temp_tracker: NewspaperDeliveryTracker):
    temp_tracker.record_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Story A",
    )
    # Immediate attempt with different story and edition
    allowed, reason = temp_tracker.should_dispatch(
        channel="telegram",
        edition_number=2213,
        lead_story="Story B",
        min_cooldown_hours=4.0,
    )
    assert allowed is False
    assert "Cooldown active" in reason


def test_force_override_bypasses_all_gates(temp_tracker: NewspaperDeliveryTracker):
    temp_tracker.record_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Story A",
    )
    allowed, reason = temp_tracker.should_dispatch(
        channel="telegram",
        edition_number=2212,
        lead_story="Story A",
        min_cooldown_hours=4.0,
        force=True,
    )
    assert allowed is True
    assert "forced" in reason


def test_persistence_across_instances(tmp_path: Path):
    state_file = tmp_path / "delivery_state.json"
    tracker1 = NewspaperDeliveryTracker(state_file=state_file)
    tracker1.record_dispatch(
        channel="telegram", edition_number=2205, lead_story="Story X"
    )

    # Second instance reading from same file
    tracker2 = NewspaperDeliveryTracker(state_file=state_file)
    allowed, reason = tracker2.should_dispatch(
        channel="telegram",
        edition_number=2205,
        lead_story="Story Y",
    )
    assert allowed is False
    assert "already been dispatched" in reason
