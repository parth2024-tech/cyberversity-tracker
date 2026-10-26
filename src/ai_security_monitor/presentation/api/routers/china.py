"""
China Intelligence Corridor API router.

Provides researcher-grade analytics, metrics, and bilingual terminologies
covering Chinese frontier foundation models (DeepSeek, Qwen, GLM, Kimi),
open-source repositories, academic breakthroughs, and cybersecurity research.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select

from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.models import EntryModel, SourceModel
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.limiter import limiter

china_router = APIRouter(prefix="/china")

KEY_CHINA_LABS = [
    {
        "name": "DeepSeek AI (深度求索)",
        "type": "Frontier AI Lab",
        "focus": "Reasoning architectures, MoE, V3/R1 models, open weights",
        "key_repos": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1"],
    },
    {
        "name": "Alibaba Qwen (通义千问)",
        "type": "Hyperscale AI Lab",
        "focus": "Open-weight LLMs, Qwen2.5-Coder, VL vision-language, agents",
        "key_repos": ["QwenLM/Qwen2.5", "QwenLM/Qwen2.5-Coder"],
    },
    {
        "name": "Shanghai AI Lab (上海人工智能实验室)",
        "type": "National Research Institute",
        "focus": "InternLM3, LMDeploy high-throughput inference, OpenDataLab",
        "key_repos": ["InternLM/InternLM", "InternLM/lmdeploy"],
    },
    {
        "name": "Zhipu AI / Tsinghua KEG (智谱AI / 清华大学)",
        "type": "Academic & Commercial Lab",
        "focus": "GLM-4 foundation models, CogVideo, agentic tool-use",
        "key_repos": ["THUDM/GLM-4", "THUDM/ChatGLM3"],
    },
    {
        "name": "Moonshot AI (月之暗面 Kimi)",
        "type": "Frontier AI Lab",
        "focus": "Long-context reasoning, k1.5 models, multi-turn exploration",
        "key_repos": ["MoonshotAI/Kimi-k1.5"],
    },
    {
        "name": "Tsinghua NISL Lab (清华大学网络与信息安全实验室)",
        "type": "Academic Cybersecurity Lab",
        "focus": "Network security, protocol vulnerabilities, system safety",
        "key_repos": ["NISL-Lab"],
    },
    {
        "name": "Qi-AnXin Technology (奇安信技术研究院 / XLab)",
        "type": "Enterprise Threat Research",
        "focus": "DNS threat intelligence, Botnets, APT tracking, vulnerability response",
        "key_repos": ["Qi-AnXin Threat Intel"],
    },
    {
        "name": "Qihoo 360 (360威胁情报中心)",
        "type": "National Cybersecurity Center",
        "focus": "APT threat intelligence, malware reverse engineering, zero-day research",
        "key_repos": ["360 CERT"],
    },
    {
        "name": "DarkNavy (暗黑海军网络安全)",
        "type": "Offensive Security Research",
        "focus": "Kernel security, hardware exploitation, supply-chain analysis",
        "key_repos": ["DarkNavy Security"],
    },
]


@china_router.get("/overview")
@limiter.limit("60/minute")
async def get_china_corridor_overview(request: Request):
    """Retrieve comprehensive China AI & Cybersecurity corridor metrics — cached 30s."""

    async def _fetch() -> dict[str, Any]:
        async with SqlAlchemyUnitOfWork() as uow:
            session = uow.session

            # Query China entries count by category
            stmt = (
                select(EntryModel.category, func.count(EntryModel.id))
                .join(SourceModel, EntryModel.source_id == SourceModel.id)
                .where(EntryModel.is_purged.is_(False))
                .where(
                    or_(
                        SourceModel.config.like('%"region": "china"%'),
                        SourceModel.config.like('%"country": "CN"%'),
                        SourceModel.config.like('%"country": "HK"%'),
                        EntryModel.extra_metadata.like('%"region": "china"%'),
                        EntryModel.extra_metadata.like('%"country": "CN"%'),
                        EntryModel.extra_metadata.like('%"country": "HK"%'),
                    )
                )
                .group_by(EntryModel.category)
            )

            result = await session.execute(stmt)
            rows = result.all()
            category_counts: dict[str, int] = dict(rows)  # type: ignore[arg-type]
            total = sum(category_counts.values())

            # Query recent 5 dispatches from China
            recent_stmt = (
                select(
                    EntryModel.id,
                    EntryModel.title,
                    EntryModel.url,
                    EntryModel.category,
                    EntryModel.published_at,
                )
                .join(SourceModel, EntryModel.source_id == SourceModel.id)
                .where(EntryModel.is_purged.is_(False))
                .where(
                    or_(
                        SourceModel.config.like('%"region": "china"%'),
                        SourceModel.config.like('%"country": "CN"%'),
                        SourceModel.config.like('%"country": "HK"%'),
                        EntryModel.extra_metadata.like('%"region": "china"%'),
                        EntryModel.extra_metadata.like('%"country": "CN"%'),
                    )
                )
                .order_by(EntryModel.published_at.desc())
                .limit(5)
            )
            recent_res = await session.execute(recent_stmt)
            recent_entries = [
                {
                    "id": r[0],
                    "title": r[1],
                    "url": r[2],
                    "category": r[3],
                    "published_at": r[4].isoformat() if r[4] else None,
                }
                for r in recent_res.all()
            ]

        return {
            "corridor": "China AI & Cyber Radar (中国前沿科技与网络安全)",
            "total_entries": total,
            "by_category": category_counts,
            "key_laboratories": KEY_CHINA_LABS,
            "recent_dispatches": recent_entries,
            "coverage_pillars": [
                "Frontier Foundation Models (DeepSeek, Qwen, GLM, Kimi)",
                "Open-Source Repositories & Serving Runtimes (LMDeploy, ModelScope)",
                "Academic Research (Tsinghua, SJTU, CAS, Fudan)",
                "Cyber Defense, Threat Intel & Vulnerability Research (Qi-AnXin, 360, DarkNavy)",
            ],
        }

    data = await response_cache.get_or_set("china_corridor_overview", 30.0, _fetch)
    headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=60"}
    return JSONResponse(content=data, headers=headers)


@china_router.get("/glossary")
async def get_china_glossary():
    """Return bilingual AI & Cybersecurity terminology dictionary for researchers."""
    glossary = [
        {
            "zh": "大语言模型 / 大模型",
            "en": "Foundation Large Language Model (LLM)",
            "category": "AI Architecture",
        },
        {
            "zh": "思维链 / 链式推理",
            "en": "Chain-of-Thought (CoT) Reasoning",
            "category": "Reasoning",
        },
        {
            "zh": "测试时计算扩展",
            "en": "Test-Time Compute Scaling",
            "category": "Scaling Laws",
        },
        {
            "zh": "强化学习对齐 (RL/DPO)",
            "en": "Reinforcement Learning & Direct Preference Optimization",
            "category": "Alignment",
        },
        {"zh": "开源权重", "en": "Open-Weights Release", "category": "Open Source"},
        {
            "zh": "端侧模型",
            "en": "On-Device / Edge SLM Deployment",
            "category": "Edge AI",
        },
        {
            "zh": "算力集群 / 显存占用",
            "en": "Compute Cluster / VRAM Footprint",
            "category": "Infrastructure",
        },
        {
            "zh": "推理加速 / 吞吐量",
            "en": "Inference Acceleration & Serving Throughput",
            "category": "Runtimes",
        },
        {
            "zh": "零日漏洞 (0day)",
            "en": "Zero-Day Vulnerability",
            "category": "Cybersecurity",
        },
        {
            "zh": "利用代码 (Exploit PoC)",
            "en": "Exploit Proof of Concept",
            "category": "Cybersecurity",
        },
        {
            "zh": "威胁情报 / APT",
            "en": "Advanced Persistent Threat (APT) Intelligence",
            "category": "Cybersecurity",
        },
        {
            "zh": "逆向工程",
            "en": "Reverse Engineering",
            "category": "Security Engineering",
        },
    ]
    return JSONResponse(content={"glossary": glossary, "count": len(glossary)})
