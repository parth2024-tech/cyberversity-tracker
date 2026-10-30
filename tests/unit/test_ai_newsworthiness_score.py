"""
Unit tests for AI Newsworthiness Scoring Service (Score v2 - Feature 4).
Evaluates 5 modular sub-components, 30 hand-rated stories rank correlation,
dynamic percentile calibration, and database persistence.
"""

import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def spearman_rank_correlation(x: list[float], y: list[float]) -> float:
    """Compute Spearman's rank correlation coefficient using standard library."""
    n = len(x)
    if n <= 1:
        return 1.0

    def get_ranks(values: list[float]) -> list[float]:
        sorted_indices = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for rank, idx in enumerate(sorted_indices):
            ranks[idx] = float(rank + 1)
        return ranks

    rx = get_ranks(x)
    ry = get_ranks(y)
    d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d_sq) / (n * (n**2 - 1))


from ai_security_monitor.application.services.newsworthiness_scoring_service import (
    NewsworthinessScoringService,
    newsworthiness_scoring_service,
)
from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Entry,
    Source,
    SourceType,
)
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyAnalysisRepository,
    SQLAlchemyEntryRepository,
    SQLAlchemySourceRepository,
)


def test_source_weight_tiers():
    svc = NewsworthinessScoringService()
    assert svc.compute_source_weight(1.0) == 25.0
    assert svc.compute_source_weight(0.8) == 25.0
    assert svc.compute_source_weight(1.2) == 18.0
    assert svc.compute_source_weight(1.5) == 18.0
    assert svc.compute_source_weight(1.8) == 10.0
    assert svc.compute_source_weight(2.0) == 10.0
    assert svc.compute_source_weight(3.0) == 5.0


def test_corroboration_score():
    svc = NewsworthinessScoringService()
    assert svc.compute_corroboration_score(1) == 0.0
    assert svc.compute_corroboration_score(2) == 12.0
    assert svc.compute_corroboration_score(3) == 18.0
    assert svc.compute_corroboration_score(4) == 25.0
    assert svc.compute_corroboration_score(10) == 25.0


def test_recency_score_decay():
    svc = NewsworthinessScoringService()
    now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

    # Published right now: 15.0
    assert svc.compute_recency_score(now, ref_time=now) == 15.0

    # Published 24h ago (1 half-life): ~7.5
    ts_24h = now - timedelta(hours=24)
    assert math.isclose(
        svc.compute_recency_score(ts_24h, ref_time=now), 7.5, abs_tol=0.1
    )

    # Published 48h ago (2 half-lives): ~3.75
    ts_48h = now - timedelta(hours=48)
    assert math.isclose(
        svc.compute_recency_score(ts_48h, ref_time=now), 3.75, abs_tol=0.1
    )


def test_entity_importance():
    svc = NewsworthinessScoringService()
    # Tier 1 Frontier Foundation Model Labs (20.0)
    assert (
        svc.compute_entity_importance("DeepSeek-R1 achieves state-of-the-art reasoning")
        == 20.0
    )
    assert svc.compute_entity_importance("Alibaba releases Qwen-2.5-Coder-72B") == 20.0
    assert svc.compute_entity_importance("Anthropic launches Claude 3.5 Sonnet") == 20.0
    assert (
        svc.compute_entity_importance("Moonshot Kimi-k1.5 multimodal release") == 20.0
    )

    # Tier 1.5 Open-Source AI Infrastructure & Inference Runtimes (15.0)
    assert (
        svc.compute_entity_importance("vLLM adds day-0 support for FP8 quantization")
        == 15.0
    )
    assert (
        svc.compute_entity_importance("Ollama releases local embedding model serving")
        == 15.0
    )
    assert (
        svc.compute_entity_importance(
            "SGLang optimizes speculative decoding throughput"
        )
        == 15.0
    )

    # General AI Architecture (10.0)
    assert svc.compute_entity_importance("Novel transformer architecture paper") == 10.0

    # Generic tech / no AI entities (5.0)
    assert svc.compute_entity_importance("Quarterly tech industry summary") == 5.0


def test_content_signal():
    svc = NewsworthinessScoringService()
    # Release verbs only (+6)
    assert svc.compute_content_signal("Team releases new product") == 6.0
    # Release (+6) + Benchmarks (+5) = 11.0
    assert (
        svc.compute_content_signal(
            "Team launches model with 85% MMLU and 92% HumanEval"
        )
        == 11.0
    )
    # Release (+6) + Benchmarks (+5) + Code link (+4) = 15.0 (max cap)
    assert (
        svc.compute_content_signal(
            "Team releases weights on github.com with 85% MMLU",
            url="https://github.com/org/repo",
        )
        == 15.0
    )


# Golden Set: 30 Hand-Rated AI Stories Across Spectrum
# Format: (title, summary, url, tier, n_sources, hours_old, expected_tier_rank 1=highest)
GOLDEN_SET_30 = [
    # Top Tier: Major Frontier Releases (Expected Rank ~85-100)
    (
        "DeepSeek-R1: Open-Sourced Reasoning LLM via Pure Reinforcement Learning",
        "DeepSeek releases DeepSeek-R1 weights with 79.8% AIME and 90.8% MATH, open on huggingface.co.",
        "https://huggingface.co/deepseek-ai/DeepSeek-R1",
        1.0,
        4,
        2,
        95.0,
    ),
    (
        "Alibaba Open-Sources Qwen-2.5-Coder-72B Coding Foundation Model",
        "Alibaba releases Qwen-2.5-Coder-72B open weights, scoring 88.4% on HumanEval, code on github.com.",
        "https://github.com/QwenLM/Qwen2.5-Coder",
        1.0,
        4,
        3,
        94.0,
    ),
    (
        "Anthropic Launches Claude 3.5 Sonnet with Computer Use Capabilities",
        "Anthropic unveils upgraded Claude 3.5 Sonnet with 49.0% on SWE-bench Verified.",
        "https://anthropic.com/news/claude-3-5-sonnet",
        1.0,
        3,
        4,
        88.0,
    ),
    (
        "OpenAI Introduces o1 Reasoning Model with Deliberative Chain of Thought",
        "OpenAI launches o1 reasoning model with 83% on International Mathematical Olympiad qualifiers.",
        "https://openai.com/index/introducing-openai-o1-preview",
        1.0,
        4,
        5,
        90.0,
    ),
    (
        "Meta Releases Llama 3.1 405B Flagship Open Weights Model",
        "Meta open-sources Llama 3.1 405B with 128k context window and 88.6% on MMLU, available on huggingface.co.",
        "https://huggingface.co/meta-llama/Llama-3.1-405B",
        1.0,
        3,
        6,
        87.0,
    ),
    (
        "Moonshot AI Unveils Kimi-k1.5 Long-Context Multimodal Reasoning LLM",
        "Moonshot AI releases Kimi-k1.5 supporting 2M context and long chain-of-thought mathematical reasoning.",
        "https://moonshot.cn/kimi-k1.5",
        1.0,
        3,
        6,
        87.0,
    ),
    (
        "Zhipu AI Launches GLM-4-Voice End-to-End Real-Time Speech Model",
        "Zhipu AI open-sources GLM-4-Voice with low latency speech-to-speech alignment, code on github.com.",
        "https://github.com/THUDM/GLM-4-Voice",
        1.0,
        3,
        8,
        85.0,
    ),
    (
        "Mistral AI Releases Mistral Large 2 with 128k Context",
        "Mistral AI announces Mistral Large 2 123B model with 84.0% MMLU and code execution on github.com.",
        "https://mistral.ai/news/mistral-large-2407",
        1.0,
        2,
        8,
        80.0,
    ),
    (
        "01.AI Debuts Yi-Lightning Claiming Top Rank on LMSYS Leaderboard",
        "01.AI launches Yi-Lightning model with 13.5% throughput gain and top LMSYS Chatbot Arena score.",
        "https://01.ai/news/yi-lightning",
        1.0,
        2,
        10,
        78.0,
    ),
    (
        "Shanghai AI Lab Open-Sources InternLM-2.5-20B with 1M Context",
        "Shanghai AI Lab releases InternLM-2.5-20B model weights with 1M context window on github.com.",
        "https://github.com/InternLM/InternLM",
        1.0,
        2,
        12,
        76.0,
    ),
    # Mid-High Tier: AI Infrastructure & Inference Runtimes (Expected Rank ~65-75)
    (
        "vLLM v0.7.0 Adds Chunked Prefill and FP8 Kernel Speedups",
        "vLLM releases v0.7.0 with 3.2x tokens/s throughput optimization for DeepSeek and Llama models on github.com.",
        "https://github.com/vllm-project/vllm",
        1.5,
        2,
        6,
        72.0,
    ),
    (
        "SGLang Introduces RadixAttention for High-Throughput Serving",
        "SGLang open-sources RadixAttention memory cache reducing latency by 4x across multi-turn chats.",
        "https://github.com/sgl-project/sglang",
        1.5,
        2,
        12,
        68.0,
    ),
    (
        "llama.cpp Adds Vulkan Shader Kernels for AMD and Apple Silicon",
        "llama.cpp releases new quantization kernel optimizations achieving 60 tokens/s on M-series chips.",
        "https://github.com/ggerganov/llama.cpp",
        1.5,
        2,
        14,
        66.0,
    ),
    (
        "Ollama 0.5.0 Enables Multi-Model Concurrent Serving",
        "Ollama announces multi-model GPU concurrency with automatic VRAM paging for local models.",
        "https://github.com/ollama/ollama",
        1.5,
        2,
        18,
        64.0,
    ),
    (
        "Unsloth Open-Sources 5x Faster Fine-Tuning for Llama 3.3",
        "Unsloth releases memory-efficient Triton kernels cutting VRAM usage by 80% for local fine-tuning.",
        "https://github.com/unslothai/unsloth",
        1.5,
        1,
        8,
        55.0,
    ),
    (
        "Triton 3.0 Delivers Automated Block-Level Kernel Compilation",
        "OpenAI releases Triton 3.0 with cross-architecture backends for NVIDIA and AMD GPUs.",
        "https://github.com/triton-lang/triton",
        1.5,
        1,
        14,
        51.0,
    ),
    (
        "PyTorch 2.5 Introduces Enhanced TorchDynamo Caching",
        "PyTorch releases 2.5 with CUDA graph capture improvements and 15% training throughput speedups.",
        "https://pytorch.org/blog/pytorch-2-5",
        1.5,
        1,
        20,
        48.0,
    ),
    (
        "Megatron-LM v0.8 Adds Pipeline Parallelism Enhancements",
        "NVIDIA releases Megatron-LM updates for FP8 MoE training on Blackwell B200 clusters.",
        "https://github.com/NVIDIA/Megatron-LM",
        1.5,
        1,
        24,
        45.0,
    ),
    (
        "Axolotl Adds Direct Preference Optimization Support for MoE",
        "Axolotl library open-sources DPO training configurations for DeepSeek and Qwen checkpoints.",
        "https://github.com/axolotl-ai-cloud/axolotl",
        1.5,
        1,
        28,
        42.0,
    ),
    (
        "TensorRT-LLM 0.15 Benchmarks Sub-Millisecond TTFT on H100",
        "NVIDIA releases TensorRT-LLM 0.15 with optimized speculative decoding kernels.",
        "https://github.com/NVIDIA/TensorRT-LLM",
        1.5,
        1,
        36,
        38.0,
    ),
    # Mid Tier: Media Corroborated Tech Analysis (Expected Rank ~45-55)
    (
        "Inside DeepSeek's Architecture: How Reinforcement Learning Replaced SFT",
        "Analysis of DeepSeek-R1 reasoning breakthroughs and compute efficiency compared to OpenAI o1.",
        "https://technode.com/2026/01/22/deepseek-architecture",
        2.0,
        2,
        8,
        52.0,
    ),
    (
        "Open-Weights Ecosystem Grows: How Qwen and Llama Challenge Proprietary Labs",
        "Comparative benchmark study examining open-weight developer adoption across Asia and the US.",
        "https://huggingface.co/blog/open-weights-momentum",
        2.0,
        2,
        16,
        46.0,
    ),
    (
        "The Rise of Chinese Frontier Models on LMSYS Chatbot Arena",
        "Overview of DeepSeek, Qwen, and Kimi taking top rankings on public LLM leaderboards.",
        "https://scmp.com/tech/ai-leaderboard",
        2.0,
        2,
        24,
        42.0,
    ),
    (
        "Local AI Boom: Why Developers are Running 8B Models on Laptops",
        "Examination of Ollama and llama.cpp adoption among developer workflows.",
        "https://hackernews.com/item?id=41000",
        2.0,
        1,
        12,
        32.0,
    ),
    (
        "Inference Cost Plunge: How FP8 Kernels Slashed Cloud GPU Budgets",
        "Technical report on vLLM and TensorRT-LLM deployment economics for production startups.",
        "https://theinformation.com/ai-inference-costs",
        2.0,
        1,
        24,
        28.0,
    ),
    # Low Tier: Generic Commentary & Opinion Blogs (Expected Rank ~15-30)
    (
        "My Experience Building a Toy Chatbot with Vector Embeddings",
        "Personal developer blog post discussing weekend hobby project with Python.",
        "https://dev.to/author/my-chatbot",
        2.5,
        1,
        24,
        22.0,
    ),
    (
        "5 Thoughts on the Future of Artificial Intelligence in 2026",
        "General opinion essay discussing workforce trends and corporate AI adoption.",
        "https://medium.com/@writer/future-of-ai",
        2.5,
        1,
        36,
        18.0,
    ),
    (
        "Why Prompt Engineering is Evolving into Workflow Engineering",
        "Discussion piece exploring system prompts versus structured agent frameworks.",
        "https://substack.com/post/prompt-engineering",
        2.5,
        1,
        48,
        15.0,
    ),
    (
        "A Brief History of Convolutional Neural Networks",
        "Retrospective blog post summarizing classical deep learning vision architectures from 2015.",
        "https://blog.personal.io/cnn-history",
        3.0,
        1,
        72,
        12.0,
    ),
    (
        "Reflections on Attending a Regional Tech Meetup",
        "Social recap of a local developer networking evening with no technical benchmarks or code.",
        "https://techmeetup.org/recap",
        3.0,
        1,
        96,
        10.0,
    ),
]


def test_30_story_golden_set_rank_correlation():
    """
    Evaluates newsworthiness score across 30 hand-rated stories.
    Asserts Spearman rank correlation r_s >= 0.70 between computed score and hand-rated rank.
    """
    now = datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
    computed_scores: list[float] = []
    expected_scores: list[float] = []

    for (
        title,
        summary,
        url,
        tier,
        n_sources,
        hours_old,
        expected,
    ) in GOLDEN_SET_30:
        pub_at = now - timedelta(hours=hours_old)
        entry = Entry(
            source_id=uuid4(),
            title=title,
            summary=summary,
            url=url,
            content_hash=f"hash_{title[:10]}",
            published_at=pub_at,
            category=Category.AI_MODELS,
            metadata={"source_count": n_sources, "tier": tier},
        )
        score, _ = newsworthiness_scoring_service.score_entry(
            entry, ref_time=now, corroboration_count=n_sources
        )
        computed_scores.append(score)
        expected_scores.append(expected)

    # Compute Spearman rank correlation
    corr = spearman_rank_correlation(computed_scores, expected_scores)

    assert corr >= 0.70, (
        f"Spearman rank correlation {corr:.3f} failed minimum 0.70 threshold!"
    )
    assert corr >= 0.85, f"Rank correlation {corr:.3f} is lower than ideal target 0.85!"

    # Major frontier releases strictly outscore low tier blog posts
    top_release_score = computed_scores[0]  # DeepSeek-R1
    low_blog_score = computed_scores[-1]  # Tech meetup recap
    assert top_release_score > low_blog_score + 40.0, (
        f"DeepSeek-R1 ({top_release_score}) should dominate generic blog ({low_blog_score})"
    )


def test_dynamic_percentile_calibration():
    """Verify lane-based empirical percentile calculations (P25, P50, P75, P90, P95)."""
    scores = [
        15.0,
        22.0,
        28.0,
        35.0,
        42.0,
        50.0,
        58.0,
        65.0,
        72.0,
        80.0,
        88.0,
        95.0,
    ]
    pcts = newsworthiness_scoring_service.calculate_percentiles(scores)

    assert "p25" in pcts
    assert "p50" in pcts
    assert "p75" in pcts
    assert "p90" in pcts
    assert "p95" in pcts

    # Monotonicity of percentiles
    assert pcts["p25"] < pcts["p50"] < pcts["p75"] < pcts["p90"] <= pcts["p95"]
    assert math.isclose(pcts["p50"], 54.0, abs_tol=5.0)


@pytest.mark.asyncio
async def test_score_v2_database_persistence():
    """Verify score_v2 and score_components_json storage in SQLAlchemyAnalysisRepository."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        src_repo = SQLAlchemySourceRepository(session)
        entry_repo = SQLAlchemyEntryRepository(session)
        analysis_repo = SQLAlchemyAnalysisRepository(session)

        # 1. Source & Entry
        source = Source(
            name="DeepSeek Lab",
            category=Category.AI_MODELS,
            type=SourceType.RSS,
            url="https://deepseek.com",
            tier=1.0,
        )
        saved_source = await src_repo.add(source)

        entry = Entry(
            source_id=saved_source.id,
            title="DeepSeek-R1 Open-Source Weights Released",
            url="https://deepseek.com/r1",
            content_hash="hash_r1_test",
            published_at=datetime.now(UTC),
            category=Category.AI_MODELS,
        )
        saved_entry = await entry_repo.add(entry)

        # 2. Add Analysis with score_v2 & score_components
        comp = {
            "source_weight": 25.0,
            "corroboration": 12.0,
            "recency": 15.0,
            "entity_importance": 20.0,
            "content_signal": 15.0,
            "total_score": 87.0,
        }
        analysis = Analysis(
            entry_id=saved_entry.id,
            attack_vector="Reasoning Architecture",
            risk_assessment="SOTA AIME and MATH benchmarks",
            mitigation="Open weights available on HuggingFace",
            threat_velocity=95,
            severity_index=90,
            score_v2=87.0,
            score_components=comp,
            model=AnalysisModel.HEURISTIC,
        )
        saved_analysis = await analysis_repo.add(analysis)
        assert saved_analysis.score_v2 == 87.0
        assert saved_analysis.score_components is not None
        assert saved_analysis.score_components["source_weight"] == 25.0
        assert saved_analysis.newsworthiness_score == 87.0

        # 3. Read back via Entry
        refetched_entry = await entry_repo.get(saved_entry.id)
        assert refetched_entry is not None
        assert refetched_entry.analysis is not None
        assert refetched_entry.analysis.score_v2 == 87.0
        assert refetched_entry.analysis.score_components["total_score"] == 87.0

        # 4. Fallback test when score_v2 is None
        analysis_no_v2 = Analysis(
            entry_id=uuid4(),
            attack_vector="Legacy",
            risk_assessment="Legacy",
            mitigation="Legacy",
            threat_velocity=65,
            severity_index=50,
            score_v2=None,
        )
        assert analysis_no_v2.newsworthiness_score == 65.0

    await engine.dispose()
