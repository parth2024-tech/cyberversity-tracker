"""
Unit and integration tests for Feature 1: Source Health Dashboard.
Tests deterministic state machine, worst-first priority sorting, HTTP 304 / 404 / HTML / redirect handling,
entries_filtered logging, and /api/health/sources query filtering.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.source_health_service import (
    compute_source_state,
    source_health_service,
)
from ai_security_monitor.domain.entities import (
    SourceHealthState,
)
from ai_security_monitor.infrastructure.database.models import (
    FetchLogModel,
    SourceHealthModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemySourceHealthRepository,
)
from ai_security_monitor.presentation.api.main import app


def test_compute_source_state_blocked_on_http_403_and_429():
    """HTTP 403 and 429 immediately result in BLOCKED state."""
    state_403 = compute_source_state(last_http_status=403)
    assert state_403 == SourceHealthState.BLOCKED

    state_429 = compute_source_state(last_http_status=429)
    assert state_429 == SourceHealthState.BLOCKED


def test_compute_source_state_blocked_on_html_error():
    """HTML returned instead of XML feed immediately results in BLOCKED state."""
    state = compute_source_state(last_http_status=200, is_html_error=True)
    assert state == SourceHealthState.BLOCKED


def test_compute_source_state_redirected():
    """Host difference between target and final URL results in REDIRECTED state."""
    state = compute_source_state(last_http_status=200, is_redirected=True)
    assert state == SourceHealthState.REDIRECTED


def test_compute_source_state_dead_on_consecutive_failures():
    """5 or more consecutive failures result in DEAD state."""
    state = compute_source_state(consecutive_failures=5)
    assert state == SourceHealthState.DEAD

    state_over = compute_source_state(consecutive_failures=8)
    assert state_over == SourceHealthState.DEAD


def test_compute_source_state_by_entry_freshness():
    """Deterministic transitions: OK (<7d) -> STALE (7-14d) -> DEAD (>14d)."""
    now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)

    # 3 days old -> OK
    recent = now - timedelta(days=3)
    assert (
        compute_source_state(last_fetch_at=now, last_new_entry_at=recent, now=now)
        == SourceHealthState.OK
    )

    # 10 days old -> STALE
    stale = now - timedelta(days=10)
    assert (
        compute_source_state(last_fetch_at=now, last_new_entry_at=stale, now=now)
        == SourceHealthState.STALE
    )

    # 15 days old -> DEAD
    dead = now - timedelta(days=15)
    assert (
        compute_source_state(last_fetch_at=now, last_new_entry_at=dead, now=now)
        == SourceHealthState.DEAD
    )


def test_compute_source_state_pending_when_never_fetched():
    """A source that has never been polled returns PENDING rather than false DEAD."""
    assert (
        compute_source_state(last_fetch_at=None, last_new_entry_at=None)
        == SourceHealthState.PENDING
    )


def test_compute_source_state_by_consecutive_zero_runs():
    """Consecutive zero runs with no entries yet: 3-4 -> STALE, 5+ -> DEAD."""
    now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)

    # Zero runs 3 -> STALE
    assert (
        compute_source_state(
            last_fetch_at=now,
            last_new_entry_at=None,
            consecutive_zero_runs=3,
            now=now,
        )
        == SourceHealthState.STALE
    )

    # Zero runs 5 -> DEAD
    assert (
        compute_source_state(
            last_fetch_at=now,
            last_new_entry_at=None,
            consecutive_zero_runs=5,
            now=now,
        )
        == SourceHealthState.DEAD
    )


@pytest.mark.asyncio
async def test_sync_source_from_db_streak_and_filtered(test_uow):
    """Verify that HTTP 304 does NOT increment zero-runs, filtered entries are tracked,
    and consecutive failures/zero runs are accurately counted from DB."""
    session = test_uow.session
    source_id = str(uuid4())

    src_model = SourceModel(
        id=source_id,
        name="Test Feed A",
        url="https://example.com/feed.xml",
        type="rss",
        category="ai_research",
        enabled=True,
        config={"region": "china", "country": "CN", "tier": 1.0},
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    session.add(src_model)
    await session.flush()

    # Log 1: Success with 304 (Not Modified)
    session.add(
        FetchLogModel(
            id=str(uuid4()),
            source_id=source_id,
            source_name="Test Feed A",
            status="success",
            entries_new=0,
            entries_total=0,
            entries_filtered=0,
            http_status=304,
            fetched_at=datetime.now(UTC) - timedelta(hours=3),
        )
    )

    # Log 2: Success with 5 total entries but 0 new because all 5 were filtered (e.g. non-AI)
    session.add(
        FetchLogModel(
            id=str(uuid4()),
            source_id=source_id,
            source_name="Test Feed A",
            status="success",
            entries_new=0,
            entries_total=5,
            entries_filtered=5,
            http_status=200,
            fetched_at=datetime.now(UTC) - timedelta(hours=6),
        )
    )
    await session.flush()

    # Sync source health
    health_model = await source_health_service.sync_source_from_db(session, src_model)
    assert health_model is not None
    assert health_model.last_http_status == 304
    # Because log 1 was 304, it did not increment zero-run streak.
    # Log 2 had entries_new == 0, so zero_runs is 1 (not 2).
    assert health_model.consecutive_zero_runs == 1
    assert health_model.consecutive_failures == 0


@pytest.mark.asyncio
async def test_worst_first_priority_sorting(test_uow):
    """Test worst-first sorting: BLOCKED > REDIRECTED > DEAD > STALE > PENDING > OK."""
    session = test_uow.session
    repo = SQLAlchemySourceHealthRepository(session)

    # Create sources in various states
    states = [
        ("Source OK", SourceHealthState.OK, 200, 10),
        ("Source PENDING", SourceHealthState.PENDING, None, 0),
        ("Source STALE", SourceHealthState.STALE, 200, 0),
        ("Source DEAD", SourceHealthState.DEAD, 200, 0),
        ("Source REDIRECTED", SourceHealthState.REDIRECTED, 200, 0),
        ("Source BLOCKED", SourceHealthState.BLOCKED, 403, 0),
    ]

    for name, st, http_st, yld in states:
        sid = str(uuid4())
        src = SourceModel(
            id=sid,
            name=name,
            url=f"https://example.com/{name}",
            type="rss",
            category="ai_research",
            enabled=True,
            config={"region": "global", "tier": 2.0},
        )
        session.add(src)
        await session.flush()

        h_model = SourceHealthModel(
            id=str(uuid4()),
            source_id=sid,
            state=st.value,
            last_http_status=http_st,
            seven_day_yield=yld,
            consecutive_failures=0,
            consecutive_zero_runs=0,
            updated_at=datetime.now(UTC),
        )
        session.add(h_model)

    await session.commit()

    results = await repo.list()
    assert len(results) == 6

    # Check order: BLOCKED (1), REDIRECTED (2), DEAD (3), STALE (4), PENDING (5), OK (6)
    order_states = [r["state"] for r in results]
    assert order_states == ["BLOCKED", "REDIRECTED", "DEAD", "STALE", "PENDING", "OK"]


@pytest.mark.asyncio
async def test_api_health_sources_filtering():
    """Test GET /api/health/sources endpoint with state and region filters."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Query all
        res = await client.get("/api/health/sources")
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "sources" in data
        assert isinstance(data["sources"], list)

        # Query filtered by non-existent region
        res_empty = await client.get("/api/health/sources?region=non_existent_galaxy")
        assert res_empty.status_code == 200
        assert res_empty.json()["total"] == 0


@pytest.mark.asyncio
async def test_rss_fetcher_redirection_normalization(monkeypatch):
    """Test host redirection logic: www vs apex is not redirected, but domain change is."""
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from ai_security_monitor.domain.entities import Category, Source, SourceType
    from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher

    src = Source(
        id=uuid4(),
        name="Redirection Test Source",
        url="https://example.com/feed.xml",
        type=SourceType.RSS,
        category=Category.AI_RESEARCH,
        enabled=True,
    )

    class MockContext:
        def __init__(self, response):
            self.mock_client = AsyncMock()
            self.mock_client.get.return_value = response

        async def __aenter__(self):
            return self.mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # 1. www redirect should NOT trigger is_redirected
    fetcher_www = RSSFetcher(src, max_retries=0)
    resp_www = MagicMock(spec=httpx.Response)
    resp_www.status_code = 200
    resp_www.url = httpx.URL("https://www.example.com/feed.xml")
    resp_www.headers = {"content-type": "application/rss+xml"}
    resp_www.content = b"<rss><channel><title>OK</title></channel></rss>"
    resp_www.text = "<rss><channel><title>OK</title></channel></rss>"
    resp_www.raise_for_status = MagicMock()

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kwargs: MockContext(resp_www),
    )
    await fetcher_www._fetch_raw()
    assert fetcher_www._is_redirected is False

    # 2. Complete domain change SHOULD trigger is_redirected
    fetcher_diff = RSSFetcher(src, max_retries=0)
    resp_diff = MagicMock(spec=httpx.Response)
    resp_diff.status_code = 200
    resp_diff.url = httpx.URL("https://different-domain.com/feed.xml")
    resp_diff.headers = {"content-type": "application/rss+xml"}
    resp_diff.content = b"<rss><channel><title>OK</title></channel></rss>"
    resp_diff.text = "<rss><channel><title>OK</title></channel></rss>"
    resp_diff.raise_for_status = MagicMock()

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kwargs: MockContext(resp_diff),
    )
    await fetcher_diff._fetch_raw()
    assert fetcher_diff._is_redirected is True
