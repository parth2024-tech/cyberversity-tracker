"""
Unit tests for Pre-Translation Community Noise Gate in monitor_service.py
and china_repo_intelligence.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from ai_security_monitor.application.services.china_repo_intelligence import (
    china_repo_intelligence,
)
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.infrastructure.fetchers.base import FetchResult


def test_china_repo_intelligence_is_community_noise():
    """Verify is_community_noise detects generic tutorials while preserving high-signal topics."""
    # 1. Noisy tutorial / interview / install strings
    assert (
        china_repo_intelligence.is_community_noise("Python从零开始小白入门教程与实战")
        is True
    )
    assert (
        china_repo_intelligence.is_community_noise(
            "2026年大厂高频面试题汇总八股文面试宝典"
        )
        is True
    )
    assert (
        china_repo_intelligence.is_community_noise("PyTorch环境安装配置与CUDA踩坑记录")
        is True
    )
    assert (
        china_repo_intelligence.is_community_noise("手把手教你本地部署保姆级教程")
        is True
    )

    # 2. High-signal topics that must NEVER be discarded even if containing tutorial words
    # A. National Vulnerability ID (CNVD)
    assert (
        china_repo_intelligence.is_community_noise(
            "CNVD-2026-10294 某大模型推理框架远程代码执行漏洞复现与入门教程"
        )
        is False
    )

    # B. CNNVD Vulnerability ID
    assert (
        china_repo_intelligence.is_community_noise(
            "CNNVD-202603-128 漏洞环境安装与利用链分析"
        )
        is False
    )

    # C. RISC-V & XiangShan Chip
    assert (
        china_repo_intelligence.is_community_noise(
            "香山高性能RISC-V处理器核开源芯片流片验证与环境配置"
        )
        is False
    )

    # D. Embodied AI & Robotics
    assert (
        china_repo_intelligence.is_community_noise(
            "宇树科技具身智能人形机器人运动控制开发入门指南"
        )
        is False
    )
    assert (
        china_repo_intelligence.is_community_noise(
            "智元四足机器人SLAM导航系统环境安装与测试"
        )
        is False
    )

    # 3. Clean technical article
    assert (
        china_repo_intelligence.is_community_noise(
            "基于DeepSeek-R1的强化学习GRPO蒸馏架构深度剖析"
        )
        is False
    )


@pytest.mark.asyncio
async def test_monitor_service_pre_translation_noise_gate():
    """Verify monitor_service discards noisy entries from community sources at zero translation cost,
    while leaving tier_1_authority sources intact and preserving high-signal community items.
    """
    from ai_security_monitor.application.services.monitor_service import MonitorService

    # Setup mock sources
    community_source = Source(
        id=uuid4(),
        name="CSDN (China Software Developer Network - AI Hub)",
        category=Category.AI_TECH,
        type=SourceType.RSS,
        url="https://www.csdn.net",
        config={
            "region": "china",
            "country": "CN",
            "language": "zh",
            "spoken_language_code": "zh",
            "china_category": "developer_community",
            "trust_tier": "tier_3_community",
        },
    )

    authority_source = Source(
        id=uuid4(),
        name="FreeBuf (Cybersecurity & Vulnerability Intelligence)",
        category=Category.CYBERSECURITY,
        type=SourceType.RSS,
        url="https://www.freebuf.com",
        config={
            "region": "china",
            "country": "CN",
            "language": "zh",
            "spoken_language_code": "zh",
            "china_category": "cybersecurity_vuln_intel",
            "trust_tier": "tier_1_authority",
        },
    )

    now = datetime.now(UTC)

    # 1. Community noisy entry
    noisy_entry = Entry(
        id=uuid4(),
        source_id=community_source.id,
        category=Category.AI_TECH,
        content_hash="1" * 64,
        title="2026年最新深度学习环境安装配置与踩坑记录",
        summary="详细记录Ubuntu 24.04下配置CUDA和PyTorch的环境安装入门教程",
        url="https://blog.csdn.net/test/article/1",
        published_at=now,
    )

    # 2. Community breakthrough entry (CNVD)
    cnvd_entry = Entry(
        id=uuid4(),
        source_id=community_source.id,
        category=Category.AI_TECH,
        content_hash="2" * 64,
        title="CNVD-2026-44812 大模型知识库系统RCE漏洞实战环境配置",
        summary="针对CNVD-2026-44812漏洞的深入复现和免杀利用分析",
        url="https://blog.csdn.net/test/article/2",
        published_at=now,
    )

    # 3. Authority source entry (even if having tutorial wording, authority source must pass)
    authority_entry = Entry(
        id=uuid4(),
        source_id=authority_source.id,
        category=Category.CYBERSECURITY,
        content_hash="3" * 64,
        title="FreeBuf漏洞挖掘入门教程：攻防演练中的红蓝对抗技巧",
        summary="FreeBuf专栏作者分享实战攻防与二进制逆向经验",
        url="https://www.freebuf.com/articles/123",
        published_at=now,
    )

    # Mock fetcher to return entries
    mock_fetcher = AsyncMock()

    with (
        patch(
            "ai_security_monitor.infrastructure.fetchers.base.fetcher_registry.get"
        ) as mock_get_fetcher,
        patch(
            "ai_security_monitor.application.services.translation_service.translation_service.translate_entry_async"
        ) as mock_translate,
    ):
        mock_get_fetcher.return_value = lambda src: mock_fetcher
        monitor = MonitorService()

        # A. Process community source with noisy entry + CNVD breakthrough entry
        from ai_security_monitor.domain.entities import FetchStatus

        mock_fetcher.fetch.return_value = FetchResult(
            entries=[noisy_entry, cnvd_entry],
            entries_new=2,
            entries_total=2,
            status=FetchStatus.SUCCESS,
        )
        await monitor.fetch_source(community_source)

        # In mock_translate calls: cnvd_entry was translated, but noisy_entry was NEVER translated!
        translated_entries = [call.args[0] for call in mock_translate.call_args_list]
        translated_titles = [e.title for e in translated_entries]

        assert (
            "CNVD-2026-44812 大模型知识库系统RCE漏洞实战环境配置" in translated_titles
        )
        assert "2026年最新深度学习环境安装配置与踩坑记录" not in translated_titles

        # B. Process authority source with tutorial wording
        mock_translate.reset_mock()
        mock_fetcher.fetch.return_value = FetchResult(
            entries=[authority_entry],
            entries_new=1,
            entries_total=1,
            status=FetchStatus.SUCCESS,
        )
        await monitor.fetch_source(authority_source)

        translated_auth = [call.args[0] for call in mock_translate.call_args_list]
        translated_auth_titles = [e.title for e in translated_auth]
        assert (
            "FreeBuf漏洞挖掘入门教程：攻防演练中的红蓝对抗技巧"
            in translated_auth_titles
        )
