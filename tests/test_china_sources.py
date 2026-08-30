"""
Test suite for China AI & Cybersecurity Intelligence Sources,
Heuristic bilingual analysis, and regional filtering.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.domain.entities import Entry, Category
from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import HeuristicAnalyzer
from ai_security_monitor.presentation.api.main import create_app
import uuid
from datetime import datetime, timezone


def test_china_sources_configuration_loaded():
    """Verify that China AI and Cybersecurity sources are properly configured in YAML."""
    config = load_sources()
    china_sources = [s for s in config.sources if s.region == "china" or s.country in ("CN", "HK")]
    
    # We configured 19 verified China sources
    assert len(china_sources) >= 15
    
    # Verify core entities exist
    names = {s.name for s in china_sources}
    assert any("CNNVD" in n for n in names)
    assert any("360" in n for n in names)
    assert any("Qi-AnXin" in n for n in names)
    assert any("DeepSeek" in n for n in names)
    assert any("GovCERT" in n for n in names)
    assert any("arXiv" in n for n in names)


@pytest.mark.asyncio
async def test_chinese_bilingual_threat_heuristics():
    """Verify that the heuristic analyzer correctly detects Chinese zero-days and AI models."""
    analyzer = HeuristicAnalyzer()
    entry = Entry(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title="DeepSeek-R1 曝出严重零日漏洞：提示注入实现远程代码执行在野利用",
        url="https://example.com/deepseek-rce",
        content_hash="china_test_hash_1",
        summary="奇安信技术研究院监测到针对开源大模型 DeepSeek 与 Qwen 的高危攻击利用链，攻击者利用越狱漏洞与系统提示词注入完成提权与任意代码执行。",
        published_at=datetime.now(timezone.utc),
        category=Category.VULNERABILITIES,
        tags=["DeepSeek", "Qwen", "0day", "RCE"],
        metadata={"region": "china", "country": "CN"}
    )
    
    analysis = await analyzer.analyze(entry)
    
    # Velocity should be elevated due to 零日 / 远程代码执行 / 0day
    assert analysis.threat_velocity >= 50
    # Affected ecosystem should detect DeepSeek and Qwen
    eco_str = " ".join(analysis.affected_ecosystem or [])
    assert "DeepSeek" in eco_str or "Qwen" in eco_str


@pytest.mark.asyncio
async def test_api_entries_china_theatre_filter():
    """Verify that querying /api/entries with region=china returns Chinese intelligence."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/entries?region=china&limit=20")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert data["total"] > 0
        
        # Check that returned entries have region china or country CN/HK
        entries = data["entries"]
        assert len(entries) > 0
        for e in entries:
            reg = e.get("region", "").lower()
            cntry = e.get("country", "").upper()
            assert reg == "china" or cntry in ("CN", "HK")
