"""
Unit and integration tests for Frontier AI Lab & Regional Coverage Reporting (Phase 1, Feature 2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.coverage_service import (
    CoverageService,
    detect_entry_lab,
)
from ai_security_monitor.domain.entities import Lab
from ai_security_monitor.infrastructure.database.models import (
    EntryModel,
    LabModel,
    SourceModel,
)
from ai_security_monitor.presentation.api.main import create_app


def _make_dummy_lab(
    name: str,
    region: str = "china",
    hf_orgs: list[str] | None = None,
    github_orgs: list[str] | None = None,
    modelscope_ids: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Lab:
    return Lab(
        id=uuid4(),
        name=name,
        region=region,
        country="CN",
        hf_orgs=hf_orgs or [],
        github_orgs=github_orgs or [],
        modelscope_ids=modelscope_ids or [],
        aliases=aliases or [],
        notes=f"Test lab {name}",
    )


def test_detect_entry_lab_metadata_matching():
    """Verify lab detection via metadata (author, org, repo slugs)."""
    deepseek = _make_dummy_lab(
        name="DeepSeek",
        hf_orgs=["deepseek-ai"],
        github_orgs=["deepseek-ai"],
        aliases=["deepseek", "深度求索"],
    )
    qwen = _make_dummy_lab(
        name="Qwen / Alibaba",
        hf_orgs=["Qwen"],
        github_orgs=["QwenLM"],
        aliases=["qwen", "通义千问"],
    )
    labs = [deepseek, qwen]

    # HF author match
    match = detect_entry_lab(
        title="New model release",
        summary="Weights released",
        url="https://example.com",
        metadata={"author": "deepseek-ai"},
        labs=labs,
    )
    assert match is not None
    assert match.name == "DeepSeek"

    # GitHub repo match
    match_gh = detect_entry_lab(
        title="Repo updated",
        summary="README update",
        url="https://example.com",
        metadata={"github_repo": "QwenLM/Qwen2.5-Coder"},
        labs=labs,
    )
    assert match_gh is not None
    assert match_gh.name == "Qwen / Alibaba"


def test_detect_entry_lab_url_and_bilingual_token_matching():
    """Verify lab detection via URL path slugs and bilingual tokens in text."""
    deepseek = _make_dummy_lab(
        name="DeepSeek",
        hf_orgs=["deepseek-ai"],
        aliases=["deepseek", "深度求索", "deepseek-r1"],
    )
    zhipu = _make_dummy_lab(
        name="Zhipu AI",
        hf_orgs=["THUDM"],
        aliases=["zhipu", "智谱", "glm-4"],
    )
    labs = [deepseek, zhipu]

    # URL path slug matching
    match_url = detect_entry_lab(
        title="Foundation Model Checkpoint",
        summary="Model weights uploaded",
        url="https://huggingface.co/deepseek-ai/DeepSeek-V3",
        metadata=None,
        labs=labs,
    )
    assert match_url is not None
    assert match_url.name == "DeepSeek"

    # Chinese token matching
    match_zh = detect_entry_lab(
        title="深度求索开源全新推理模型架构",
        summary="展现出极强的推理与代码生成能力",
        url="https://technode.com/story/123",
        metadata=None,
        labs=labs,
    )
    assert match_zh is not None
    assert match_zh.name == "DeepSeek"

    # Alias / acronym matching
    match_alias = detect_entry_lab(
        title="Release notes for GLM-4 and Agentic Workflows",
        summary="Zhipu announces updated long-context model",
        url="https://venturebeat.com/glm-4",
        metadata=None,
        labs=labs,
    )
    assert match_alias is not None
    assert match_alias.name == "Zhipu AI"

    # Non-matching entry
    match_none = detect_entry_lab(
        title="Generic Python tool for database backup",
        summary="A simple CLI tool written in Python",
        url="https://github.com/random/backup-tool",
        metadata=None,
        labs=labs,
    )
    assert match_none is None


def test_publisher_vs_subject_region_attribution():
    """Verify that a US publication reporting on a Chinese lab attributes subject_region='china'."""
    deepseek = _make_dummy_lab(
        name="DeepSeek",
        region="china",
        aliases=["deepseek", "深度求索"],
    )
    labs = [deepseek]

    # US TechCrunch article about DeepSeek
    matched = detect_entry_lab(
        title="How DeepSeek Shook Silicon Valley With Open Weights",
        summary="TechCrunch analysis of DeepSeek's low-cost frontier reasoning model",
        url="https://techcrunch.com/2026/01/deepseek-reasoning",
        metadata=None,
        labs=labs,
    )
    assert matched is not None
    assert matched.region == "china"
    assert matched.name == "DeepSeek"


@pytest.mark.asyncio
async def test_generate_coverage_report_logic(test_db_engine):
    """Verify coverage report calculates regional share and correctly identifies lab gaps."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        # Seed 3 distinct labs
        lab_active1 = LabModel(
            id=str(uuid4()),
            name="Lab Alpha",
            region="china",
            country="CN",
            hf_orgs=["lab-alpha"],
            github_orgs=["lab-alpha"],
            modelscope_ids=[],
            wechat_accounts=[],
            aliases=["alpha", "阿尔法"],
            notes="Active lab 1",
        )
        lab_active2 = LabModel(
            id=str(uuid4()),
            name="Lab Beta",
            region="china",
            country="CN",
            hf_orgs=["lab-beta"],
            github_orgs=["lab-beta"],
            modelscope_ids=[],
            wechat_accounts=[],
            aliases=["beta", "贝塔"],
            notes="Active lab 2",
        )
        lab_gap = LabModel(
            id=str(uuid4()),
            name="Lab Silent",
            region="china",
            country="CN",
            hf_orgs=["lab-silent"],
            github_orgs=["lab-silent"],
            modelscope_ids=[],
            wechat_accounts=[],
            aliases=["silent", "静音"],
            notes="Gap lab with 0 entries",
        )
        session.add_all([lab_active1, lab_active2, lab_gap])

        # Seed sources (1 china, 1 us)
        src_china = SourceModel(
            id=str(uuid4()),
            name="China AI News",
            type="rss",
            category="ai_ecosystem",
            url="https://example.cn/feed.xml",
            config={"region": "china", "tier": 1.0},
            enabled=True,
            rate_limit_seconds=60,
        )
        src_us = SourceModel(
            id=str(uuid4()),
            name="US Tech News",
            type="rss",
            category="ai_ecosystem",
            url="https://example.com/feed.xml",
            config={"region": "us", "tier": 1.0},
            enabled=True,
            rate_limit_seconds=60,
        )
        session.add_all([src_china, src_us])
        await session.flush()

        now = datetime.now(UTC)
        # Entry for Lab Alpha (within 7d)
        e1 = EntryModel(
            id=str(uuid4()),
            source_id=src_china.id,
            lab_id=lab_active1.id,
            subject_region="china",
            title="Lab Alpha announces breakthrough",
            url="https://example.cn/story1",
            content_hash="hash_alpha",
            published_at=now - timedelta(days=2),
            summary="Alpha reasoning model",
            category="ai_ecosystem",
            is_purged=False,
        )
        # Entry for Lab Beta (within 20d)
        e2 = EntryModel(
            id=str(uuid4()),
            source_id=src_us.id,
            lab_id=lab_active2.id,
            subject_region="china",
            title="Lab Beta releases weights",
            url="https://example.com/story2",
            content_hash="hash_beta",
            published_at=now - timedelta(days=15),
            summary="Beta vision model",
            category="ai_ecosystem",
            is_purged=False,
        )
        session.add_all([e1, e2])
        await session.commit()

        service = CoverageService()
        report = await service.generate_coverage_report(
            session=session,
            target_region="china",
            now=now,
            auto_backfill=False,
        )

        assert "summary" in report
        assert "regions" in report
        assert "labs" in report
        assert "gaps" in report
        assert "markdown_report" in report

        # Verify gap lab identification
        gap_lab_names = [g["name"] for g in report["gaps"]["inactive_labs"]]
        assert "Lab Silent" in gap_lab_names

        # Verify active lab counts
        lab_reports = {item["name"]: item for item in report["labs"]}
        assert lab_reports["Lab Alpha"]["entries_30d"] == 1
        assert lab_reports["Lab Alpha"]["status"] == "ACTIVE"
        assert lab_reports["Lab Silent"]["entries_30d"] == 0
        assert lab_reports["Lab Silent"]["status"] == "GAP"

        # Verify markdown report format contains expected tables
        md = report["markdown_report"]
        assert "Regional & Frontier AI Lab Coverage Report" in md
        assert "#### 1. Regional Ecosystem Share" in md
        assert "#### 2. Frontier AI Lab Coverage" in md
        assert "#### 3. Intelligence Blind Spots & Gaps" in md
        assert "Lab Silent" in md


@pytest.mark.asyncio
async def test_coverage_api_endpoints():
    """Verify GET /api/coverage and POST /api/coverage/backfill API endpoints."""
    from ai_security_monitor.config.settings import settings

    app = create_app()
    admin_headers = {}
    if settings.api.admin_api_key:
        admin_headers["X-Admin-Key"] = settings.api.admin_api_key

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test GET /api/coverage
        resp = await client.get("/api/coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "regions" in data
        assert "labs" in data
        assert "gaps" in data
        assert "markdown_report" in data or "markdown_table" in data

        # Test GET /api/coverage?region=china
        resp_china = await client.get("/api/coverage?region=china")
        assert resp_china.status_code == 200
        china_data = resp_china.json()
        assert china_data["target_region"] == "china"

        # Test POST /api/coverage/backfill
        resp_bf = await client.post("/api/coverage/backfill", headers=admin_headers)
        assert resp_bf.status_code == 200
        bf_data = resp_bf.json()
        assert bf_data["status"] == "success"
        assert "tagged_count" in bf_data

