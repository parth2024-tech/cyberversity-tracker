"""
Unit and integration test suite for the High-Recall Intelligence Architecture.
Tests all 10 core techniques from Deliverable C:
1. HTTP Conditional Request Handshake (ETag / If-Modified-Since)
2. Dual-Channel Ingestion (XML Sitemaps + Google News Sitemaps)
3. Trafilatura Heuristic Extraction with Recall Cascades
4. Adaptive Dynamic Scheduling (entry_frequency)
5. Canonical URL Normalization & Tracking Param Pruning
6. Dual-Tier Deduplication: SimHash (64-bit) & MinHash (64-Permutation)
7. Resource-Governed Worker Scaling (AutoscaledPool)
8. Decoupled Factual Confidence vs. Importance Scoring
9. Zero-Daemon Search & Storage: SQLite WAL + FTS5 BM25 Search
10. Automated Lincoln-Petersen / Chapman Capture-Recapture Recall Auditing
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.article_extractor import (
    ArticleExtractor,
)
from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
    canonicalize_url,
    compute_minhash64,
    compute_simhash64,
    extract_title_tokens,
    minhash_jaccard_similarity,
    simhash_hamming_distance,
)
from ai_security_monitor.application.services.recall_auditor import (
    RecallAuditorService,
    calculate_chapman_estimate,
)
from ai_security_monitor.application.services.source_health_service import (
    SourceHealthMetrics,
    SourceHealthService,
)
from ai_security_monitor.application.services.triage_scoring_pipeline import (
    compute_decoupled_scores,
)
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    Source,
    SourceType,
    Story,
)
from ai_security_monitor.infrastructure.fetchers.autoscaled_pool import (
    AutoscaledPool,
    get_system_resource_metrics,
)
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher
from ai_security_monitor.infrastructure.fetchers.sitemap_fetcher import (
    SitemapFetcher,
)


# ── Technique 1: HTTP Conditional Handshake ─────────────────────────────────
@pytest.mark.asyncio
async def test_rss_fetcher_conditional_handshake(monkeypatch):
    """Verify ETag and If-Modified-Since headers are injected and HTTP 304 returns empty list."""
    source = Source(
        id=uuid4(),
        name="Test Feed",
        category=Category.AI_MODELS,
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
        config={"etag": '"abc123xyz"', "last_modified": "Mon, 19 Oct 2026 12:00:00 GMT"},
    )
    fetcher = RSSFetcher(source)

    class Mock304Response:
        status_code = 304
        headers = {}
        content = b""

    async def mock_get(self, url, **kwargs):
        assert self.headers.get("if-none-match") == '"abc123xyz"'
        assert self.headers.get("if-modified-since") == "Mon, 19 Oct 2026 12:00:00 GMT"
        return Mock304Response()

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await fetcher._fetch_raw()
    assert result == []


# ── Technique 2: Dual-Channel XML Sitemap Ingestion ─────────────────────────
def test_sitemap_fetcher_xml_parsing():
    """Verify XML sitemap parsing extracts loc and filters items by 14-day freshness window."""
    source = Source(
        id=uuid4(),
        name="AI Lab Sitemap",
        category=Category.AI_TECH,
        type=SourceType.SITEMAP,
        url="https://example.com/sitemap.xml",
    )
    fetcher = SitemapFetcher(source)

    fresh_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    stale_date = (datetime.now(UTC) - timedelta(days=20)).isoformat()

    sample_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
        <url>
            <loc>https://example.com/fresh-ai-breakthrough</loc>
            <lastmod>{fresh_date}</lastmod>
            <news:news>
                <news:publication>
                    <news:name>AI Lab</news:name>
                    <news:language>en</news:language>
                </news:publication>
                <news:publication_date>{fresh_date}</news:publication_date>
                <news:title>Frontier Reasoning Model Breakthrough</news:title>
            </news:news>
        </url>
        <url>
            <loc>https://example.com/stale-archive-article</loc>
            <lastmod>{stale_date}</lastmod>
        </url>
    </urlset>
    """.encode()

    entries = fetcher._parse_sitemap_xml(sample_xml)
    assert len(entries) == 1
    assert entries[0]["title"] == "Frontier Reasoning Model Breakthrough"
    assert entries[0]["url"] == "https://example.com/fresh-ai-breakthrough"
    assert entries[0]["metadata"]["channel"] == "sitemap"


# ── Technique 3: Trafilatura Heuristic Extraction ───────────────────────────
@pytest.mark.asyncio
async def test_trafilatura_extraction_cascade(monkeypatch):
    """Verify Trafilatura extract is prioritized for web articles."""
    extractor = ArticleExtractor()

    sample_html = """
    <!DOCTYPE html>
    <html>
        <body>
            <nav><a href="/">Home</a></nav>
            <article>
                <h1>DeepSeek-R1 Architecture Overview</h1>
                <p>DeepSeek-R1 introduces high-efficiency reinforcement learning without supervised fine-tuning.
                The model demonstrates frontier reasoning capabilities across mathematical benchmarks and coding harnesses.
                This technical briefing outlines the inference optimization and kernel serving strategies.</p>
                <p>Large-scale test-time compute scaling exhibits emergent self-verification behavior across complex tasks.</p>
            </article>
            <footer>Copyright 2026</footer>
        </body>
    </html>
    """

    class MockWebResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = sample_html
        content = sample_html.encode("utf-8")

    import httpx
    async def mock_get(self, url, **kwargs):
        return MockWebResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await extractor._extract_generic_web("https://example.com/deepseek-r1", "example.com")
    assert result is not None
    assert "DeepSeek-R1" in result or "reasoning" in result.lower()
    assert len(result.split()) >= 20


# ── Technique 4: Adaptive Dynamic Scheduling ────────────────────────────────
def test_adaptive_dynamic_scheduling():
    """Verify entry_frequency calculation and adaptive polling interval scaling."""
    metrics = SourceHealthMetrics(
        source_name="High Velocity Lab",
        source_type="rss",
        category="ai_models",
        recent_entry_counts=[6, 7, 5, 8],
    )
    # High frequency (> 5 entries/run) should scale to 180s (3 min)
    assert metrics.entry_frequency >= 5.0
    assert metrics.adaptive_polling_interval_seconds == 180

    dormant = SourceHealthMetrics(
        source_name="Dormant Blog",
        source_type="rss",
        category="ai_tech",
        total_runs=5,
        success_count=1,
        recent_entry_counts=[0, 0, 0],
    )
    # Dormant feed should back off to hours
    assert dormant.adaptive_polling_interval_seconds >= 7200

    service = SourceHealthService()
    service._sources["High Velocity Lab"] = metrics
    assert service.get_adaptive_interval("High Velocity Lab") == 180
    assert service.get_adaptive_interval("Unknown Source", fallback_seconds=3600) == 3600


# ── Technique 5: Canonical URL Normalization ────────────────────────────────
def test_canonical_url_normalization():
    """Verify tracking parameters, standard ports, and domain variations are pruned."""
    # Tracking parameters and ports
    url1 = "https://example.com:443/article?utm_source=twitter&utm_medium=social&fbclid=12345&id=99#comments"
    canon1 = canonicalize_url(url1)
    assert canon1 == "https://example.com/article?id=99"

    # arXiv PDF to standard abstract landing page
    arxiv_url = "https://arxiv.org/pdf/2401.12345.pdf"
    assert canonicalize_url(arxiv_url) == "https://arxiv.org/abs/2401.12345"

    # GitHub release to canonical repository slug
    github_url = "https://github.com/vllm-project/vllm/releases/tag/v0.6.2"
    assert canonicalize_url(github_url) == "https://github.com/vllm-project/vllm"


# ── Technique 6: Dual-Tier Deduplication (SimHash & MinHash) ────────────────
def test_simhash_and_minhash_deduplication():
    """Verify 64-bit SimHash Hamming distance and 64-permutation MinHash Jaccard."""
    # SimHash near-duplicate check
    text_a = (
        "DeepSeek releases DeepSeek-R1 open weights reasoning model with state of the art performance "
        "across all benchmarks and coding tasks in production environments"
    )
    text_b = (
        "DeepSeek releases DeepSeek-R1 open weights reasoning model with state of the art performance "
        "across all benchmarks and coding tasks in production systems"
    )
    text_c = (
        "NVIDIA Blackwell B200 GPU architecture delivers unprecedented FP4 matrix performance "
        "for hyperscale datacenter inference and training workloads"
    )

    sh_a = compute_simhash64(text_a)
    sh_b = compute_simhash64(text_b)
    sh_c = compute_simhash64(text_c)

    dist_ab = simhash_hamming_distance(sh_a, sh_b)
    dist_ac = simhash_hamming_distance(sh_a, sh_c)

    assert dist_ab <= 4  # Near duplicate
    assert dist_ac > 10  # Distinct story

    # MinHash headline Jaccard check
    tokens_a = extract_title_tokens("DeepSeek Unveils R1 Reasoning Model Weights")
    tokens_b = extract_title_tokens("DeepSeek Releases R1 Reasoning Model Open Weights")
    tokens_c = extract_title_tokens("Ollama Adds Support for Local GPU Quantization")

    sig_a = compute_minhash64(tokens_a)
    sig_b = compute_minhash64(tokens_b)
    sig_c = compute_minhash64(tokens_c)

    jaccard_ab = minhash_jaccard_similarity(sig_a, sig_b)
    jaccard_ac = minhash_jaccard_similarity(sig_a, sig_c)

    assert jaccard_ab >= 0.35  # Syndicated wire variation
    assert jaccard_ac < 0.15   # Unrelated

    # Verify integration with DeduplicationService
    dedup = DeduplicationService(similarity_threshold=0.60, minhash_threshold=0.35)
    e1 = Entry(
        source_id=uuid4(),
        title="DeepSeek Unveils R1 Reasoning Model Weights",
        url="https://reuters.com/deepseek-r1?utm_source=rss",
        content_hash="hash1",
        summary=text_a,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    e2 = Entry(
        source_id=uuid4(),
        title="DeepSeek Releases R1 Reasoning Model Open Weights",
        url="https://bloomberg.com/deepseek-r1-launch?ref=feed",
        content_hash="hash2",
        summary=text_b,
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )

    _, story1, is_new1 = dedup.process_candidate(e1, source_name="Reuters")
    assert is_new1 is True

    _, story2, is_new2 = dedup.process_candidate(e2, source_name="Bloomberg")
    assert is_new2 is False
    assert story1.id == story2.id
    assert story1.source_count == 2
    assert story1.confidence_score == 0.75  # 0.50 + 0.25 * log2(2)


# ── Technique 7: Resource-Governed Scaling (AutoscaledPool) ─────────────────
@pytest.mark.asyncio
async def test_autoscaled_pool_resource_governance():
    """Verify AutoscaledPool respects host memory limits."""
    metrics = get_system_resource_metrics()
    assert "ram_percent" in metrics
    assert "available_mb" in metrics

    pool = AutoscaledPool(max_concurrency=4, min_concurrency=1, ram_high_threshold=80.0)
    concurrency = pool.evaluate_target_concurrency()
    assert concurrency in (1, 2, 4)

    # Acquire and release
    async with pool:
        pass


# ── Technique 8: Decoupled Factual Confidence vs. Importance ─────────────────
def test_decoupled_factual_confidence_and_importance():
    """Verify logarithmic confidence scales with domain count and importance decays with age."""
    entry = Entry(
        source_id=uuid4(),
        title="DeepSeek-R1 Reasoning Architecture Breakthrough",
        url="https://deepseek.com/r1",
        content_hash="hash_r1",
        summary="Reinforcement learning test-time compute breakthrough",
        published_at=datetime.now(UTC) - timedelta(hours=24),
        category=Category.AI_MODELS,
    )

    scores = compute_decoupled_scores(entry)
    assert scores["factual_confidence"] == 0.50  # Single source base
    assert scores["base_importance"] == 1.00     # Reasoning breakthrough
    assert scores["importance_score"] < 1.00     # Decayed after 24h
    assert scores["importance_score"] > 0.85

    # Multi-source corroboration confidence check
    story = Story(
        title="Test Story",
        canonical_url="https://example.com",
        fingerprint="fp",
        category=Category.AI_MODELS,
        sources=["DomainA"],
        entry_ids=[uuid4()],
        source_count=1,
        confidence_score=0.50,
    )
    e_extra = Entry(
        source_id=uuid4(),
        title="Corroboration",
        url="https://another-domain.com",
        content_hash="hash_corr",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    story.add_entry(e_extra, source_name="DomainB")
    assert story.confidence_score == 0.75  # 0.50 + 0.25 * log2(2)

    e_extra2 = Entry(
        source_id=uuid4(),
        title="Corroboration 2",
        url="https://third-domain.com",
        content_hash="hash_corr2",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    story.add_entry(e_extra2, source_name="DomainC")
    e_extra3 = Entry(
        source_id=uuid4(),
        title="Corroboration 3",
        url="https://fourth-domain.com",
        content_hash="hash_corr3",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
    )
    story.add_entry(e_extra3, source_name="DomainD")
    assert story.confidence_score == 1.00  # 0.50 + 0.25 * log2(4)


# ── Technique 9: SQLite WAL + FTS5 Full-Text Search ─────────────────────────
def test_sqlite_fts5_triggers_and_bm25_search():
    """Verify SQLite FTS5 table and insert/update/delete triggers perform BM25 ranking."""
    con = sqlite3.connect(":memory:")
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")

    cur.execute("CREATE TABLE entries (id TEXT PRIMARY KEY, title TEXT, summary TEXT, category TEXT, is_purged INTEGER DEFAULT 0)")
    cur.execute("CREATE VIRTUAL TABLE entries_fts USING fts5(title, summary, category, entry_id UNINDEXED)")

    cur.execute("""
    CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(entry_id, title, summary, category) VALUES (new.id, new.title, new.summary, new.category);
    END;
    """)
    cur.execute("""
    CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
        DELETE FROM entries_fts WHERE entry_id = old.id;
    END;
    """)
    cur.execute("""
    CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
        DELETE FROM entries_fts WHERE entry_id = old.id;
        INSERT INTO entries_fts(entry_id, title, summary, category) VALUES (new.id, new.title, new.summary, new.category);
    END;
    """)

    # Insert items
    cur.execute("INSERT INTO entries VALUES ('id1', 'DeepSeek-V3 Open Weights Release', 'Mixture of experts model architecture', 'ai_models', 0)")
    cur.execute("INSERT INTO entries VALUES ('id2', 'vLLM Fast Inference Engine', 'High throughput paged attention serving', 'cyber_tools', 0)")

    # BM25 Search
    results = cur.execute(
        "SELECT entry_id, title, bm25(entries_fts) as rank FROM entries_fts WHERE entries_fts MATCH 'DeepSeek' ORDER BY rank ASC"
    ).fetchall()
    assert len(results) == 1
    assert results[0][0] == "id1"

    # Delete item and verify trigger synchronization
    cur.execute("DELETE FROM entries WHERE id = 'id1'")
    after_del = cur.execute("SELECT entry_id FROM entries_fts WHERE entry_id = 'id1'").fetchall()
    assert len(after_del) == 0


# ── Technique 10: Lincoln-Petersen Recall Auditor ───────────────────────────
def test_lincoln_petersen_chapman_recall_auditor():
    """Verify Chapman estimator calculations for total universe and empirical recall."""
    # n1 = 100, n2 = 60, m = 40
    # N = ((101 * 61) / 41) - 1 = floor(149.26) = 149
    # Captured = 100 + 60 - 40 = 120
    # Recall = 120 / 149 = 80.54%
    res = calculate_chapman_estimate(n1_rss=100, n2_sitemap=60, overlap_m=40)
    assert res["estimated_universe_N"] == 149
    assert res["total_captured"] == 120
    assert res["empirical_recall_pct"] == 80.54
    assert res["coverage_gap_pct"] == 19.46
    assert res["ci_95"][0] <= 149 <= res["ci_95"][1]

    # Verify Auditor service with mock entries
    auditor = RecallAuditorService(window_days=14)
    now = datetime.now(UTC)
    entries = [
        Entry(source_id=uuid4(), title="Art 1", url="https://example.com/art1", content_hash="h1", published_at=now, category=Category.AI_MODELS, metadata={"channel": "rss"}),
        Entry(source_id=uuid4(), title="Art 2", url="https://example.com/art2", content_hash="h2", published_at=now, category=Category.AI_MODELS, metadata={"channel": "rss"}),
        Entry(source_id=uuid4(), title="Art 2", url="https://example.com/art2", content_hash="h2_sm", published_at=now, category=Category.AI_MODELS, metadata={"channel": "sitemap"}),
        Entry(source_id=uuid4(), title="Art 3", url="https://example.com/art3", content_hash="h3", published_at=now, category=Category.AI_MODELS, metadata={"channel": "sitemap"}),
    ]

    audit = auditor.audit_entries(entries)
    assert audit["n1_rss"] == 2
    assert audit["n2_sitemap"] == 2
    assert audit["overlap_m"] == 1
    assert audit["total_captured"] == 3
    assert audit["status"] == "dual_channel_verified"
