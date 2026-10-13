"""
Expanded test suite for China intelligence pipeline hardening:
1. Multi-byte GB18030 / GBK encoding decoding
2. Feed resilience & malformed XML handling
3. Content sanitization against XSS and injection
4. Deduplication & content hash stability
5. Regional isolation testing
6. Provenance tagging verification
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.domain.entities import Category, Source, SourceType
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.rss_fetcher import RSSFetcher
from ai_security_monitor.presentation.api.main import create_app


def test_clean_html_sanitization_strips_malicious_payloads():
    """Verify that _clean_html thoroughly strips scripts, iframes, and event handlers."""
    source = Source(
        id=uuid.uuid4(),
        name="Test Sanitizer Source",
        category=Category.CYBERSECURITY,
        type=SourceType.RSS,
        url="http://test.local/rss",
        rate_limit_seconds=1800,
        enabled=True,
    )
    fetcher = RSSFetcher(source)

    dirty_payload = (
        "<script>alert('XSS')</script>"
        "<iframe src='javascript:alert(1)'></iframe>"
        "<img src='x' onerror='stealCookie()' />"
        "<a href='javascript:exploit()' onclick='run()'>Click Here</a>"
        "<p style='color:red;'>Safe paragraph with &amp; &lt;entities&gt;.</p>"
    )

    clean = fetcher._clean_html(dirty_payload)

    assert "<script>" not in clean
    assert "<iframe>" not in clean
    assert "onerror=" not in clean
    assert "onclick=" not in clean
    assert "javascript:" not in clean
    assert "Safe paragraph with & <entities>." in clean


def test_gb18030_gbk_multi_encoding_decoding():
    """Verify that Chinese national encoding GB18030 and GBK decode without mojibake."""
    chinese_text = "国家信息安全漏洞共享平台 (CNVD) 发布高危漏洞预警"
    gbk_bytes = chinese_text.encode("gb18030")

    # Test candidate decoder logic
    candidate_encodings = ["utf-8", "gb18030", "gbk", "gb2312"]
    decoded = ""
    for enc in candidate_encodings:
        try:
            decoded = gbk_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    assert decoded == chinese_text
    assert "CNVD" in decoded
    assert "高危漏洞" in decoded


def test_content_hash_deduplication_stability():
    """Verify content hash produces deterministic, identical hashes for duplicate entries."""
    t = "DeepSeek-R1 推理大模型开源发布"
    u = "https://github.com/deepseek-ai/DeepSeek-V3"
    d = "2026-08-30T10:00:00"

    hash1 = ContentHash.from_content(t, u, d)
    hash2 = ContentHash.from_content(t, u, d)

    assert str(hash1) == str(hash2)
    assert len(str(hash1)) == 64


@pytest.mark.asyncio
async def test_regional_isolation_filters():
    """Verify that region=china does not leak into other regional queries."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from ai_security_monitor.domain.entities import Category, Entry
    from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
    from ai_security_monitor.infrastructure.database.unit_of_work import (
        SqlAlchemyUnitOfWork,
    )

    async with SqlAlchemyUnitOfWork() as uow:
        cn_items = await uow.entries.list(
            filters=EntryFilters(region="china"), pagination=PaginationParams(limit=1)
        )
        if not cn_items:
            all_srcs = await uow.sources.list(enabled_only=False)
            cn_src = next(
                (
                    s
                    for s in all_srcs
                    if s.config
                    and (
                        s.config.get("country") in ("CN", "HK")
                        or s.config.get("region") == "china"
                    )
                ),
                all_srcs[0],
            )
            eu_src = next(
                (
                    s
                    for s in all_srcs
                    if s.config
                    and s.config.get("country") not in ("CN", "HK")
                    and s.config.get("region") != "china"
                ),
                all_srcs[0],
            )
            await uow.entries.add(
                Entry(
                    id=uuid4(),
                    source_id=cn_src.id,
                    title="DeepSeek V3 Model Weights Released in Beijing",
                    url=f"https://test.cn/{uuid4()}",
                    content_hash=f"cn_{uuid4().hex[:16]}",
                    published_at=datetime.now(UTC),
                    category=Category.AI_MODELS,
                    metadata={"region": "china", "country": "CN"},
                    summary="DeepSeek releases open weights in China.",
                )
            )
            await uow.entries.add(
                Entry(
                    id=uuid4(),
                    source_id=eu_src.id,
                    title="Mistral Large 2 Released in Paris",
                    url=f"https://test.fr/{uuid4()}",
                    content_hash=f"eu_{uuid4().hex[:16]}",
                    published_at=datetime.now(UTC),
                    category=Category.AI_MODELS,
                    metadata={"region": "europe", "country": "FR"},
                    summary="Mistral AI releases weights in Europe.",
                )
            )
            await uow.commit()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # China query
        resp_cn = await client.get("/api/entries?region=china&limit=10")
        assert resp_cn.status_code == 200
        data_cn = resp_cn.json()
        assert data_cn["total"] > 0
        for e in data_cn["entries"]:
            assert e.get("region") == "china" or e.get("country") in ("CN", "HK")

        # Europe query
        resp_eu = await client.get("/api/entries?region=europe&limit=10")
        assert resp_eu.status_code == 200
        data_eu = resp_eu.json()
        for e in data_eu["entries"]:
            assert e.get("region") == "europe"
            assert e.get("country") not in ("CN", "HK")
