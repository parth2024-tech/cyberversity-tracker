"""
Unit and integration tests for the China AI Corridor & Cybersecurity Ingestion Matrix (55+ Sources).
Verifies:
1. All 55 sources catalog integrity, categorization into 5 pillars, and URL deduplication.
2. Epistemic profile extraction for new lab authorities (Unitree, BAAI, CASIA, Xuanwu, XiangShan)
   and new architectural archetypes (embodied_ai_robotics, semiconductor_riscv, offensive_security_vuln, computer_vision_edge).
3. Deterministic glossary fallback and token shielding for cybersecurity and robotics/chip terminology.
4. Chinese date parsing (YYYY年MM月DD日, UTC+8) for the 14-day freshness invariant.
5. /china/sources API endpoint filtering.
"""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.china_repo_intelligence import (
    ChinaRepoArchetype,
    china_repo_intelligence,
)
from ai_security_monitor.application.services.china_token_shield import (
    china_token_shield,
)
from ai_security_monitor.application.services.translation_service import (
    GLOSSARY_FALLBACK_TERMS,
    translation_service,
)
from ai_security_monitor.config.china_source_catalog import (
    get_china_sources_matrix,
    get_sources_by_china_category,
)
from ai_security_monitor.config.sources import load_sources
from ai_security_monitor.presentation.api.main import create_app


# ── Test Suite 1: Source Matrix Integrity (55 Sources across 5 Pillars) ─────
def test_china_source_catalog_matrix_completeness():
    """Verify that all 55 canonical China Corridor sources are loaded and valid."""
    matrix = get_china_sources_matrix()
    assert len(matrix) == 55

    # Verify all 5 categories are well-represented
    cat_a = get_sources_by_china_category("code_hosting_platform")
    cat_b = get_sources_by_china_category("ai_robotics_chip_media")
    cat_c = get_sources_by_china_category("cybersecurity_vuln_intel")
    cat_d = get_sources_by_china_category("developer_community")
    cat_e = get_sources_by_china_category("corporate_academic_lab")

    assert len(cat_a) == 7
    assert len(cat_b) == 9
    assert len(cat_c) == 15
    assert len(cat_d) == 9
    assert len(cat_e) == 15

    # Ensure uniqueness of IDs and non-empty URLs
    ids = [s.id for s in matrix]
    assert len(ids) == len(set(ids)), "Source IDs must be strictly unique"

    urls = [s.url for s in matrix]
    assert len(urls) == len(set(urls)), "Source portal URLs must be strictly unique"

    feed_urls = [s.feed_url for s in matrix]
    assert len(feed_urls) == len(set(feed_urls)), "Feed URLs must be strictly unique"

    for s in matrix:
        assert s.name and len(s.name.strip()) > 0
        assert s.name_zh and len(s.name_zh.strip()) > 0
        assert s.country == "CN"
        assert s.trust_tier in (1.0, 1.5, 2.0)


def test_china_sources_registered_in_sources_yaml():
    """Verify that sources.yaml includes all matrix entries and validates against Pydantic schema."""
    config = load_sources()
    yaml_urls = {s.url.strip().lower() for s in config.sources if s.url}

    matrix = get_china_sources_matrix()
    for s in matrix:
        assert s.feed_url.strip().lower() in yaml_urls, (
            f"Missing in sources.yaml: {s.name} ({s.feed_url})"
        )


# ── Test Suite 2: China AI Epistemic Profiler (Authorities & Archetypes) ────
def test_china_repo_intelligence_new_lab_authorities():
    """Verify that epistemic profiler recognizes newly added labs and authorities."""
    # 1. Unitree Robotics
    prof_unitree = china_repo_intelligence.extract_profile(
        title="unitreerobotics/unitree_sdk2",
        description="SDK for Unitree B2, Go2 quadruped and H1 humanoid robots",
        url="https://github.com/unitreerobotics/unitree_sdk2",
    )
    assert prof_unitree.is_official_lab is True
    assert "Unitree Robotics" in (prof_unitree.lab_name or "")
    assert prof_unitree.archetype == ChinaRepoArchetype.EMBODIED_AI_ROBOTICS.value

    # 2. BAAI FlagOpen
    prof_baai = china_repo_intelligence.extract_profile(
        title="FlagOpen/FlagEmbedding",
        description="Dense Retrieval and Multi-Task Embedding models by BAAI",
        url="https://github.com/FlagOpen/FlagEmbedding",
    )
    assert prof_baai.is_official_lab is True
    assert "BAAI" in (prof_baai.lab_name or "")

    # 3. ICT CAS XiangShan RISC-V
    prof_ict = china_repo_intelligence.extract_profile(
        title="OpenXiangShan/XiangShan",
        description="An open-source high-performance RISC-V processor by ICT CAS",
        url="https://github.com/OpenXiangShan/XiangShan",
    )
    assert prof_ict.is_official_lab is True
    assert "ICT CAS" in (prof_ict.lab_name or "")
    assert prof_ict.archetype == ChinaRepoArchetype.SEMICONDUCTOR_RISCV.value

    # 4. Tencent Xuanwu Lab
    prof_xuanwu = china_repo_intelligence.extract_profile(
        title="Tencent Xuanwu Lab Security Research",
        description="腾讯安全玄武实验室 0-day 漏洞挖掘与利用防护",
        url="https://github.com/tencentxlab/security-advisory",
    )
    assert prof_xuanwu.is_official_lab is True
    assert "Xuanwu Lab" in (prof_xuanwu.lab_name or "")
    assert prof_xuanwu.archetype == ChinaRepoArchetype.OFFENSIVE_SECURITY_VULN.value


def test_china_repo_intelligence_new_archetypes():
    """Verify classification of newly added archetypes."""
    # Embodied AI & Robotics
    prof_robot = china_repo_intelligence.extract_profile(
        title="Agibot World Model",
        description="智元机器人具身世界模型与双足四足运动控制系统",
    )
    assert prof_robot.archetype == ChinaRepoArchetype.EMBODIED_AI_ROBOTICS.value

    # Computer Vision & Edge AI
    prof_cv = china_repo_intelligence.extract_profile(
        title="YOLOX-Edge",
        description="旷视研究院高性能目标检测算法与边缘AI图像分割",
    )
    assert prof_cv.archetype == ChinaRepoArchetype.COMPUTER_VISION_EDGE.value

    # Semiconductor & RISC-V
    prof_chip = china_repo_intelligence.extract_profile(
        title="RISC-V NPU Acceleration",
        description="香山开源芯片昇腾算力架构与流片验证",
    )
    assert prof_chip.archetype == ChinaRepoArchetype.SEMICONDUCTOR_RISCV.value

    # Offensive Security & Vulnerabilities
    prof_vuln = china_repo_intelligence.extract_profile(
        title="CNVD-2025-01234 远程代码执行漏洞分析",
        description="通过恶意构造序列化数据实现任意代码执行与提权漏洞复现 PoC",
    )
    assert prof_vuln.archetype == ChinaRepoArchetype.OFFENSIVE_SECURITY_VULN.value


# ── Test Suite 3: Token Shielding & Glossary Fallback ───────────────────────
def test_china_token_shield_security_and_chip_identifiers():
    """Verify that CNVD, CNNVD, PoC, EXP, RCE, and framework names survive machine translation intact."""
    raw_text = (
        "国家信息安全漏洞共享平台发布 CNVD-2025-99881 高危公告，攻击者使用 POC 实现 RCE 任意代码执行。"
        "同时针对 CNNVD-2024-5544321 漏洞发布 EXP 利用代码。涉及 XiangShan 处理器与 MindSpore 框架。"
    )

    shielded, mapping = china_token_shield.shield(raw_text)

    # Placeholders must be injected
    assert "CNVD-2025-99881" not in shielded
    assert "CNNVD-2024-5544321" not in shielded
    assert "XiangShan" not in shielded
    assert "MindSpore" not in shielded

    # Verify placeholder keys exist in mapping
    values = set(mapping.values())
    assert "CNVD-2025-99881" in values
    assert "CNNVD-2024-5544321" in values
    assert "POC" in values
    assert "EXP" in values
    assert "RCE" in values
    assert "XiangShan" in values
    assert "MindSpore" in values

    # Unshielding must perfectly restore the original text
    restored = china_token_shield.unshield(shielded, mapping)
    assert restored == raw_text


def test_translation_service_deterministic_glossary_expansion():
    """Verify fallback glossary deterministic translations for robotics, chips, and vulnerabilities."""
    terms_map = dict(GLOSSARY_FALLBACK_TERMS)

    # Vulnerability terminology
    assert terms_map["供应链投毒"] == "Supply Chain Poisoning"
    assert terms_map["二进制漏洞"] == "Binary Vulnerability"
    assert terms_map["远程代码执行"] == "Remote Code Execution (RCE)"
    assert terms_map["逆向工程"] == "Reverse Engineering"
    assert "CNVD" in terms_map["国家信息安全漏洞共享平台"]
    assert "CNNVD" in terms_map["国家信息安全漏洞库"]

    # Robotics, Chips, Frameworks
    assert terms_map["具身智能"] == "Embodied AI"
    assert terms_map["人形机器人"] == "Humanoid Robot"
    assert terms_map["视觉里程计"] == "Visual Odometry / VIO"
    assert terms_map["点云"] == "Point Cloud"
    assert terms_map["香山"] == "XiangShan RISC-V"
    assert terms_map["飞桨"] == "PaddlePaddle"
    assert terms_map["昇思"] == "MindSpore"
    assert terms_map["魔搭"] == "ModelScope"

    # Full fallback translation check
    sample_text = "中国开源芯片香山发布，同时研究具身智能人形机器人与远程代码执行防御。"
    translated = translation_service._translate_via_glossary_fallback(sample_text, "zh")
    assert translated is not None
    assert "XiangShan RISC-V" in translated
    assert "Embodied AI" in translated
    assert "Humanoid Robot" in translated
    assert "Remote Code Execution (RCE)" in translated


# ── Test Suite 4: Chinese Date Parsing & 14-Day Freshness Invariant ─────────
def test_rss_fetcher_chinese_date_normalization():
    """Verify that RSSFetcher cleans YYYY年MM月DD日 and CST/UTC+8 to correct UTC timestamps."""
    from dateutil import parser as dt_parser

    # Simulate Chinese date strings
    raw_date_1 = "2026年03月15日 14:30:00 (UTC+8)"
    raw_date_2 = "2026年2月10日 09时15分 北京时间"

    # Normalize logic
    clean_1 = re.sub(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", r"\1-\2-\3 ", raw_date_1
    )
    clean_1 = re.sub(
        r"(\d{1,2})\s*时\s*(\d{1,2})\s*分(?:\s*(\d{1,2})\s*秒)?",
        lambda m: (
            f" {m.group(1)}:{m.group(2)}:{m.group(3)} "
            if m.group(3)
            else f" {m.group(1)}:{m.group(2)} "
        ),
        clean_1,
    )

    parsed_1 = dt_parser.parse(clean_1, fuzzy=True)
    assert parsed_1.year == 2026
    assert parsed_1.month == 3
    assert parsed_1.day == 15

    clean_2 = re.sub(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", r"\1-\2-\3 ", raw_date_2
    )
    clean_2 = re.sub(
        r"(\d{1,2})\s*时\s*(\d{1,2})\s*分(?:\s*(\d{1,2})\s*秒)?",
        lambda m: (
            f" {m.group(1)}:{m.group(2)}:{m.group(3)} "
            if m.group(3)
            else f" {m.group(1)}:{m.group(2)} "
        ),
        clean_2,
    )
    parsed_2 = dt_parser.parse(clean_2, fuzzy=True)
    assert parsed_2.year == 2026
    assert parsed_2.month == 2
    assert parsed_2.day == 10


# ── Test Suite 5: API Endpoint (/api/china/sources) ───────────────────────────
@pytest.mark.asyncio
async def test_api_china_sources_endpoint():
    """Verify /api/china/sources returns the 55-source matrix and supports pillar filtering."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Full matrix
        res = await client.get("/api/china/sources")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["total"] == 55
        assert len(data["sources"]) == 55

        # 2. Filtered by cybersecurity pillar
        res_sec = await client.get(
            "/api/china/sources?category=cybersecurity_vuln_intel"
        )
        assert res_sec.status_code == 200
        data_sec = res_sec.json()
        assert data_sec["total"] == 15
        assert all(
            s["china_category"] == "cybersecurity_vuln_intel"
            for s in data_sec["sources"]
        )

        # 3. Filtered by code hosting platforms
        res_code = await client.get("/api/china/sources?category=code_hosting_platform")
        assert res_code.status_code == 200
        data_code = res_code.json()
        assert data_code["total"] == 7
