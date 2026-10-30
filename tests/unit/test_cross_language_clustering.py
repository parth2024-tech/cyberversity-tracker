"""
Unit tests for Cross-Language Story Clustering (Feature 6).
Evaluates entity resolution, number normalization, 20 hand-labeled pairs (precision gate >= 0.90),
coverage summary reporting, and database repository persistence.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_security_monitor.application.services.cross_language_clustering import (
    CrossLanguageClusteringService,
    backfill_stories_clustering,
    cross_language_clustering_service,
)
from ai_security_monitor.application.services.deduplication_service import (
    DeduplicationService,
)
from ai_security_monitor.domain.entities import (
    Category,
    Entry,
    Source,
    SourceType,
    Story,
)
from ai_security_monitor.infrastructure.database.models import Base
from ai_security_monitor.infrastructure.database.repositories import (
    SQLAlchemyEntryRepository,
    SQLAlchemySourceRepository,
    SQLAlchemyStoryRepository,
)
from ai_security_monitor.infrastructure.database.unit_of_work import UnitOfWork


def test_chinese_number_normalization():
    svc = CrossLanguageClusteringService()
    assert svc.normalize_numbers("720亿参数模型发布") == "72b参数模型发布"
    assert svc.normalize_numbers("80亿小模型") == "8b小模型"
    assert svc.normalize_numbers("140亿参数") == "14b参数"
    assert svc.normalize_numbers("100万长上下文") == "1000k长上下文"
    assert svc.normalize_numbers("1万亿全模态") == "1t全模态"


def test_lab_alias_resolution_and_cluster_key():
    svc = CrossLanguageClusteringService()

    ent_deepseek = svc.extract_entities("深度求索推出DeepSeek-R1大模型")
    assert ent_deepseek.lab == "deepseek"
    assert ent_deepseek.model_family == "deepseek-r1"
    assert ent_deepseek.cluster_key == "deepseek:deepseek-r1"
    assert ent_deepseek.language == "zh"

    ent_qwen = svc.extract_entities("Alibaba releases Qwen-2.5-Coder-72B open-weights")
    assert ent_qwen.lab == "qwen"
    assert ent_qwen.model_family == "qwen-2.5-coder"
    assert ent_qwen.version == "72b"
    assert ent_qwen.cluster_key == "qwen:qwen-2.5-coder:72b"
    assert ent_qwen.language == "en"

    ent_kimi = svc.extract_entities("月之暗面发布Kimi-k1.5多模态推理模型")
    assert ent_kimi.lab == "moonshot"
    assert ent_kimi.model_family == "kimi-k1.5"
    assert ent_kimi.cluster_key == "moonshot:kimi-k1.5"


# 20 Hand-Labeled Pairs for Precision Gate Evaluation
# 10 positive CN/EN pairs (identical story across languages)
POSITIVE_PAIRS = [
    (
        "深度求索正式开源DeepSeek-R1推理大模型，强化学习突破新高度",
        "DeepSeek open-sources DeepSeek-R1 reasoning model, matching o1 performance",
        "deepseek-r1",
    ),
    (
        "阿里通义千问开源Qwen-2.5-Coder-72B代码模型，刷新多项编程评测榜单",
        "Alibaba releases Qwen-2.5-Coder-72B open-weight coding LLM",
        "qwen-2.5-coder-72b",
    ),
    (
        "月之暗面发布Kimi-k1.5多模态长文本推理模型，支持大规模长思维链",
        "Moonshot AI unveils Kimi-k1.5 multimodal reasoning model with long context",
        "kimi-k1.5",
    ),
    (
        "智谱AI开源端到端语音大模型GLM-4-Voice，支持实时双向语音对齐",
        "Zhipu AI introduces GLM-4-Voice end-to-end speech foundation model",
        "glm-4-voice",
    ),
    (
        "上海人工智能实验室开源书生·浦语InternLM-2.5-20B模型，支持100万长上下文",
        "Shanghai AI Lab releases InternLM-2.5-20B supporting 1M context window",
        "internlm-2.5-20b",
    ),
    (
        "MiniMax发布MiniMax-01全模态混合专家架构大模型",
        "MiniMax announces MiniMax-01 lightning-fast MoE multimodal foundation model",
        "minimax-01",
    ),
    (
        "阶跃星辰推出Step-2万亿参数多模态大模型，具备极强复杂逻辑推理能力",
        "StepFun debuts Step-2 trillion-parameter multimodal reasoning model",
        "step-2",
    ),
    (
        "百川智能发布最新旗舰大模型Baichuan-4，大幅提升中文长文本综合问答能力",
        "Baichuan AI launches Baichuan-4 frontier LLM with superior Chinese capabilities",
        "baichuan-4",
    ),
    (
        "零一万物正式推出旗舰模型Yi-Lightning，登顶LMSYS盲测榜单超越GPT-4o",
        "01.AI unveils Yi-Lightning claiming top rank on LMSYS Chatbot Arena",
        "yi-lightning",
    ),
    (
        "vLLM推理框架深度适配DeepSeek-R1，吞吐量提升300%",
        "vLLM adds full-stack day-0 optimization for DeepSeek-R1 inference engine",
        "vllm-deepseek-r1",
    ),
]

# 10 negative same-org pairs (same organization, different models - MUST NOT MERGE)
NEGATIVE_PAIRS = [
    (
        "深度求索发布DeepSeek-V3基础大模型，总参数量671B",
        "DeepSeek introduces DeepSeek-R1 reasoning model",
        "deepseek-v3 vs deepseek-r1",
    ),
    (
        "阿里开源Qwen-2.5-Coder专注代码生成与自动修复",
        "Alibaba releases Qwen-2.5-Math specialized for mathematical reasoning",
        "qwen-coder vs qwen-math",
    ),
    (
        "Anthropic launches Claude 3.5 Sonnet with enhanced coding capability",
        "Anthropic releases Claude 3.5 Haiku high-speed lightweight model",
        "claude-sonnet vs claude-haiku",
    ),
    (
        "Meta open-sources Llama 3.1 405B flagship model",
        "Meta releases Llama 3.2 lightweight edge vision models",
        "llama-3.1 vs llama-3.2",
    ),
    (
        "OpenAI launches GPT-4o real-time voice and vision model",
        "OpenAI introduces o1 reasoning model with chain of thought",
        "gpt-4o vs o1",
    ),
    (
        "Mistral AI releases Mistral Large 2 with 128k context",
        "Mistral AI launches Codestral 22B code generation model",
        "mistral-large-2 vs codestral",
    ),
    (
        "Google updates Gemini 1.5 Pro with 2M token context window",
        "Google launches Gemini 2.0 Flash real-time multimodal model",
        "gemini-1.5-pro vs gemini-2.0-flash",
    ),
    (
        "智谱AI全面推出新一代GLM-4基座模型",
        "Zhipu AI releases ChatGLM-3 conversation model for developers",
        "glm-4 vs chatglm-3",
    ),
    (
        "上海人工智能实验室开源InternLM-2基础模型",
        "Shanghai AI Lab introduces InternLM-2.5 next generation model",
        "internlm-2 vs internlm-2.5",
    ),
    (
        "月之暗面发布Kimi-k1.5推理模型",
        "Moonshot AI updates Kimi Chat consumer web application",
        "kimi-k1.5 vs kimi-chat",
    ),
]


def test_20_pair_precision_gate():
    """
    Precision Gate: evaluates 20 hand-labeled pairs (10 positive, 10 negative).
    Guarantees Precision >= 0.90 (hard requirement) and Recall >= 0.85 before feeding ranking.
    """
    now = datetime.now(UTC)

    # 1. Evaluate 10 Positive Pairs
    true_positives = 0
    false_negatives = 0
    for cn_text, en_text, pair_label in POSITIVE_PAIRS:
        matched = cross_language_clustering_service.are_same_story(
            cn_text,
            en_text,
            published_a=now,
            published_b=now + timedelta(hours=2),
            max_delta_hours=72.0,
        )
        if matched:
            true_positives += 1
        else:
            false_negatives += 1

    # 2. Evaluate 10 Negative Same-Org Pairs
    false_positives = 0
    true_negatives = 0
    for text_a, text_b, pair_label in NEGATIVE_PAIRS:
        matched = cross_language_clustering_service.are_same_story(
            text_a,
            text_b,
            published_a=now,
            published_b=now + timedelta(hours=2),
            max_delta_hours=72.0,
        )
        if matched:
            false_positives += 1
        else:
            true_negatives += 1

    total_predicted_positive = true_positives + false_positives
    precision = (
        true_positives / total_predicted_positive
        if total_predicted_positive > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )

    # Precision Gate Assertion
    assert precision >= 0.90, (
        f"Precision {precision:.2f} failed threshold 0.90! "
        f"FP: {false_positives}, TP: {true_positives}"
    )
    assert recall >= 0.85, (
        f"Recall {recall:.2f} failed threshold 0.85! "
        f"FN: {false_negatives}, TP: {true_positives}"
    )
    assert false_positives == 0, (
        f"Detected {false_positives} false mergers in same-org negative pairs!"
    )


def test_story_coverage_summary_formatting():
    """Verify human-readable reporting: 'first reported by (source, time), also covered by N sources across English and Chinese'."""
    story = Story(
        title="DeepSeek-R1 Open-Source Reasoning",
        canonical_url="https://deepseek.com/r1",
        cluster_key="deepseek:deepseek-r1",
        first_seen_at=datetime(2026, 1, 20, 10, 0, tzinfo=UTC),
        first_source_name="Weixin / 机器之心",
        language_mix={"zh": 1, "en": 2},
        sources=["Weixin / 机器之心", "HackerNews", "X / Twitter"],
        entry_ids=[uuid4(), uuid4(), uuid4()],
    )

    summary = story.coverage_summary
    assert "First reported by Weixin / 机器之心 (2026-01-20 10:00 UTC)" in summary
    assert "also covered by 3 sources across English and Chinese" in summary


def test_deduplication_service_cross_language_merging():
    """Test that DeduplicationService merges Chinese and English entries into one story with coverage summary."""
    dedup = DeduplicationService()
    now = datetime.now(UTC)

    # Ingest Chinese entry
    entry_cn = Entry(
        source_id=uuid4(),
        title="深度求索正式开源DeepSeek-R1推理大模型",
        url="https://mp.weixin.qq.com/s/deepseek_r1_announcement",
        content_hash="hash_cn_r1",
        summary="深度求索团队今日发布开源推理模型DeepSeek-R1，基于强化学习",
        published_at=now,
        category=Category.AI_MODELS,
    )
    e1, s1, is_new1 = dedup.process_candidate(entry_cn, source_name="机器之心")
    assert is_new1 is True
    assert s1.cluster_key == "deepseek:deepseek-r1"
    assert s1.language_mix == {"zh": 1}
    assert e1.story_id == s1.id

    # Ingest English corroborating entry 3 hours later
    entry_en = Entry(
        source_id=uuid4(),
        title="DeepSeek open-sources DeepSeek-R1 reasoning model",
        url="https://news.ycombinator.com/item?id=42000000",
        content_hash="hash_en_r1",
        summary="DeepSeek-R1 released with MIT open-weights matching OpenAI o1 benchmark",
        published_at=now + timedelta(hours=3),
        category=Category.AI_MODELS,
    )
    e2, s2, is_new2 = dedup.process_candidate(entry_en, source_name="HackerNews")
    assert is_new2 is False
    assert s2.id == s1.id
    assert s2.entry_count == 2
    assert s2.source_count == 2
    assert s2.language_mix == {"zh": 1, "en": 1}
    assert e2.story_id == s1.id
    assert "also covered by 2 sources across English and Chinese" in s2.coverage_summary


@pytest.mark.asyncio
async def test_story_database_repository_persistence():
    """Verify StoryModel, EntryModel.story_id, and SQLAlchemyStoryRepository in SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        src_repo = SQLAlchemySourceRepository(session)
        entry_repo = SQLAlchemyEntryRepository(session)
        story_repo = SQLAlchemyStoryRepository(session)

        # 1. Add Source
        source = Source(
            name="Test Source",
            category=Category.AI_TECH,
            type=SourceType.RSS,
            url="https://example.com/rss",
        )
        saved_source = await src_repo.add(source)

        # 2. Add Story
        story = Story(
            title="Qwen-2.5-Coder-72B Open Weights",
            canonical_url="https://github.com/qwenlm/qwen2.5-coder",
            cluster_key="qwen:qwen-2.5-coder:72b",
            first_source_id=saved_source.id,
            language_mix={"en": 1, "zh": 1},
            entry_count=2,
            source_count=2,
            confidence_score=0.75,
            heat_score=2.1,
            heat_badge="surge",
            is_primary=True,
        )
        saved_story = await story_repo.add(story)
        assert saved_story.id is not None
        assert saved_story.cluster_key == "qwen:qwen-2.5-coder:72b"

        # 3. Add Entries linked to Story
        entry1 = Entry(
            source_id=saved_source.id,
            title="Alibaba releases Qwen-2.5-Coder-72B",
            url="https://example.com/e1",
            content_hash="h1",
            published_at=datetime.now(UTC),
            category=Category.AI_MODELS,
            story_id=saved_story.id,
        )
        saved_e1 = await entry_repo.add(entry1)
        assert saved_e1.story_id == saved_story.id

        entry2 = Entry(
            source_id=saved_source.id,
            title="阿里通义千问开源Qwen-2.5-Coder-72B模型",
            url="https://example.com/e2",
            content_hash="h2",
            published_at=datetime.now(UTC),
            category=Category.AI_MODELS,
            story_id=saved_story.id,
        )
        saved_e2 = await entry_repo.add(entry2)
        assert saved_e2.story_id == saved_story.id

        # 4. Fetch Story by cluster_key
        fetched_story = await story_repo.get_by_cluster_key("qwen:qwen-2.5-coder:72b")
        assert fetched_story is not None
        assert fetched_story.id == saved_story.id
        assert fetched_story.heat_badge == "surge"
        assert len(fetched_story.entry_ids) == 2
        assert saved_e1.id in fetched_story.entry_ids
        assert saved_e2.id in fetched_story.entry_ids

        # 5. List active stories
        active = await story_repo.list_active_within(window_hours=72)
        assert len(active) == 1
        assert active[0].cluster_key == "qwen:qwen-2.5-coder:72b"

    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_stories_clustering_routine():
    """Verify backfill_stories_clustering links existing unclustered entries into stories."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        uow = UnitOfWork(session=session)

        # Create source
        src = Source(
            name="Tech Lab",
            category=Category.AI_TECH,
            type=SourceType.RSS,
            url="https://lab.ai/rss",
        )
        saved_src = await uow.sources.add(src)

        now = datetime.now(UTC)
        # Entry A: Chinese DeepSeek-R1
        e_cn = Entry(
            source_id=saved_src.id,
            title="深度求索正式开源DeepSeek-R1推理模型",
            url="https://lab.ai/deepseek-r1-cn",
            content_hash="hash_cn_backfill",
            published_at=now - timedelta(days=1),
            category=Category.AI_MODELS,
        )
        await uow.entries.add(e_cn)

        # Entry B: English DeepSeek-R1 (2 hours later)
        e_en = Entry(
            source_id=saved_src.id,
            title="DeepSeek open-sources DeepSeek-R1 reasoning model",
            url="https://lab.ai/deepseek-r1-en",
            content_hash="hash_en_backfill",
            published_at=now - timedelta(days=1) + timedelta(hours=2),
            category=Category.AI_MODELS,
        )
        await uow.entries.add(e_en)

        # Run backfill
        stats = await backfill_stories_clustering(uow, window_days=14)
        assert stats["entries_processed"] == 2
        assert stats["stories_created"] == 1
        assert stats["stories_merged"] == 1

        # Check story in repository
        story = await uow.stories.get_by_cluster_key("deepseek:deepseek-r1")
        assert story is not None
        assert story.entry_count == 2
        assert story.language_mix.get("zh") == 1
        assert story.language_mix.get("en") == 1

    await engine.dispose()
