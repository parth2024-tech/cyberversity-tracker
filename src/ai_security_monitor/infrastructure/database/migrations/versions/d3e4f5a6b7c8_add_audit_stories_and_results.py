"""add_audit_stories_and_results

Revision ID: d3e4f5a6b7c8
Revises: make_source_url_nullable
Create Date: 2026-10-30 21:55:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BENCHMARK_STORIES_SEED = [
    {
        "id": str(uuid4()),
        "title": "DeepSeek-V2.5 & DeepInfer Open Source Inference Engine",
        "lab_name": "DeepSeek",
        "region": "china",
        "release_date": datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/deepseek-ai/DeepSeek-V2.5",
        "model_names": [
            "deepseek-v2.5",
            "deepseek v2.5",
            "deepinfer",
            "deepseek-coder-v2",
        ],
        "org_tokens": ["deepseek", "深度求索"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Alibaba Qwen 2.5 Foundation & Specialized Models (72B, Coder, Math)",
        "lab_name": "Qwen / Alibaba",
        "region": "china",
        "release_date": datetime(2026, 9, 19, 8, 0, 0, tzinfo=UTC),
        "canonical_url": "https://qwenlm.github.io/blog/qwen2.5/",
        "model_names": ["qwen2.5", "qwen 2.5", "qwen2.5-coder", "qwen2.5-math", "qwq"],
        "org_tokens": ["qwen", "alibaba", "通义千问"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Qwen 2.5-Coder 32B Code Generation SOTA Release",
        "lab_name": "Qwen / Alibaba",
        "region": "china",
        "release_date": datetime(2026, 10, 24, 6, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/QwenLM/Qwen2.5-Coder",
        "model_names": ["qwen2.5-coder-32b", "qwen 2.5-coder", "qwen2.5-coder"],
        "org_tokens": ["qwen", "qwenlm", "alibaba"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "ByteDance Seed-TTS & Doubao Multimodal Models",
        "lab_name": "ByteDance",
        "region": "china",
        "release_date": datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/Bytedance/Seed-TTS",
        "model_names": ["seed-tts", "seedtts", "doubao", "豆包"],
        "org_tokens": ["bytedance", "字节跳动"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "MiniMax Video-01 Generation & abab 6.5s MoE Release",
        "lab_name": "MiniMax",
        "region": "china",
        "release_date": datetime(2026, 9, 10, 9, 0, 0, tzinfo=UTC),
        "canonical_url": "https://huggingface.co/MiniMaxAI",
        "model_names": ["video-01", "abab 6.5s", "abab6.5s", "minimax-text"],
        "org_tokens": ["minimax", "名之梦"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Shanghai AI Lab InternLM 2.5 & LMDeploy Serving Architecture",
        "lab_name": "Shanghai AI Lab",
        "region": "china",
        "release_date": datetime(2026, 9, 20, 4, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/InternLM/lmdeploy",
        "model_names": ["internlm2.5", "internlm 2.5", "lmdeploy", "书生"],
        "org_tokens": ["shanghai ai lab", "internlm"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Moonshot AI Kimi 1.5 Ultra Long-Context Reasoning",
        "lab_name": "Moonshot AI",
        "region": "china",
        "release_date": datetime(2026, 10, 10, 8, 0, 0, tzinfo=UTC),
        "canonical_url": "https://kimi.moonshot.cn/",
        "model_names": ["kimi", "moonshot 1.5", "moonshot-v1"],
        "org_tokens": ["moonshot", "月之暗面"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Zhipu AI GLM-4-9B Open Weights & CogView4 Generation",
        "lab_name": "Zhipu AI",
        "region": "china",
        "release_date": datetime(2026, 9, 15, 7, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/THUDM/GLM-4",
        "model_names": ["glm-4", "glm-4-9b", "cogview4", "chatglm"],
        "org_tokens": ["zhipu", "智谱", "thudm"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Meta Llama 3.2 Multimodal Vision (11B/90B) and Lightweight Models",
        "lab_name": "Meta AI",
        "region": "us",
        "release_date": datetime(2026, 9, 25, 17, 0, 0, tzinfo=UTC),
        "canonical_url": "https://ai.meta.com/blog/llama-3-2-connect-2024/",
        "model_names": [
            "llama 3.2",
            "llama-3.2",
            "llama-3.2-11b",
            "llama-3.2-3b",
            "llama-3.2-1b",
        ],
        "org_tokens": ["meta", "meta ai"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Anthropic Upgraded Claude 3.5 Sonnet & Computer Use Capability",
        "lab_name": "Anthropic",
        "region": "us",
        "release_date": datetime(2026, 10, 22, 13, 0, 0, tzinfo=UTC),
        "canonical_url": "https://www.anthropic.com/news/3-5-models-and-computer-use",
        "model_names": [
            "claude 3.5 sonnet",
            "computer use",
            "claude 3.5 haiku",
            "claude-3-5",
        ],
        "org_tokens": ["anthropic", "claude"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "OpenAI o1-preview & o1-mini Reasoning Architecture",
        "lab_name": "OpenAI",
        "region": "us",
        "release_date": datetime(2026, 9, 12, 17, 0, 0, tzinfo=UTC),
        "canonical_url": "https://openai.com/index/introducing-openai-o1-preview/",
        "model_names": ["o1-preview", "o1-mini", "strawberry", "openai o1"],
        "org_tokens": ["openai"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Mistral Pixtral 12B Open Multimodal Model",
        "lab_name": "Mistral AI",
        "region": "europe",
        "release_date": datetime(2026, 9, 11, 14, 0, 0, tzinfo=UTC),
        "canonical_url": "https://mistral.ai/news/pixtral-12b/",
        "model_names": ["pixtral", "pixtral 12b", "pixtral-12b"],
        "org_tokens": ["mistral", "mistral ai"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Mistral Ministral 3B & 8B Edge Foundation Models",
        "lab_name": "Mistral AI",
        "region": "europe",
        "release_date": datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC),
        "canonical_url": "https://mistral.ai/news/ministral/",
        "model_names": ["ministral", "ministral 3b", "ministral 8b", "ministral-8b"],
        "org_tokens": ["mistral", "mistral ai"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Google Gemini 1.5 Flash-8B Production Availability",
        "lab_name": "Google DeepMind",
        "region": "us",
        "release_date": datetime(2026, 10, 3, 16, 0, 0, tzinfo=UTC),
        "canonical_url": "https://developers.googleblog.com/en/gemini-15-flash-8b-is-general-availability/",
        "model_names": ["gemini 1.5 flash-8b", "flash-8b", "gemini-1.5-flash-8b"],
        "org_tokens": ["google", "deepmind"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "vLLM v0.6 High-Performance Distributed LLM Engine",
        "lab_name": "vLLM Project",
        "region": "global",
        "release_date": datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/vllm-project/vllm/releases/tag/v0.6.2",
        "model_names": ["vllm v0.6", "vllm 0.6", "vllm-project"],
        "org_tokens": ["vllm"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "SGLang v0.3 RadixAttention Inference Runtime",
        "lab_name": "LMSYS / SGLang",
        "region": "global",
        "release_date": datetime(2026, 9, 28, 20, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/sgl-project/sglang",
        "model_names": ["sglang v0.3", "sglang", "radixattention"],
        "org_tokens": ["sglang", "lmsys"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Hugging Face Transformers v4.45 Architecture Support",
        "lab_name": "Hugging Face",
        "region": "global",
        "release_date": datetime(2026, 9, 18, 15, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/huggingface/transformers/releases/tag/v4.45.0",
        "model_names": ["transformers v4.45", "transformers 4.45"],
        "org_tokens": ["hugging face", "huggingface"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Baidu ERNIE 4.0 Turbo & High-Speed Inference Engine",
        "lab_name": "Baidu",
        "region": "china",
        "release_date": datetime(2026, 9, 4, 11, 0, 0, tzinfo=UTC),
        "canonical_url": "https://cloud.baidu.com/article/ernie-turbo",
        "model_names": ["ernie 4.0", "ernie-4.0-turbo", "文心一言"],
        "org_tokens": ["baidu", "百度"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Huawei Ascend MindSpore 2.3 & Pangu Foundation Updates",
        "lab_name": "Huawei",
        "region": "china",
        "release_date": datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC),
        "canonical_url": "https://www.mindspore.cn/",
        "model_names": ["mindspore 2.3", "pangu", "盘古", "ascend"],
        "org_tokens": ["huawei", "华为"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Cognition FrontierCode 2.0 Hardened Coding Benchmark",
        "lab_name": "Cognition AI",
        "region": "us",
        "release_date": datetime(2026, 10, 27, 16, 0, 0, tzinfo=UTC),
        "canonical_url": "https://www.cognition.ai/blog",
        "model_names": ["frontiercode", "frontiercode 2.0", "cognition"],
        "org_tokens": ["cognition"],
        "added_by": "system",
    },
    {
        "id": str(uuid4()),
        "title": "Ollama 0.3.12 Structured Output & Vision Model Integration",
        "lab_name": "Ollama",
        "region": "global",
        "release_date": datetime(2026, 9, 26, 19, 0, 0, tzinfo=UTC),
        "canonical_url": "https://github.com/ollama/ollama/releases/tag/v0.3.12",
        "model_names": ["ollama 0.3.12", "ollama structured outputs", "ollama vision"],
        "org_tokens": ["ollama"],
        "added_by": "system",
    },
]


def upgrade() -> None:
    """Create audit_stories and audit_results tables and seed benchmark stories."""
    # 1. Create audit_stories
    op.create_table(
        "audit_stories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("lab_name", sa.String(100), nullable=False),
        sa.Column("region", sa.String(50), nullable=False, server_default="global"),
        sa.Column("release_date", sa.DateTime(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("model_names", sa.JSON(), nullable=False),
        sa.Column("org_tokens", sa.JSON(), nullable=False),
        sa.Column("added_by", sa.String(50), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_stories_title", "audit_stories", ["title"])
    op.create_index("ix_audit_stories_lab_name", "audit_stories", ["lab_name"])
    op.create_index("ix_audit_stories_region", "audit_stories", ["region"])
    op.create_index("ix_audit_stories_release_date", "audit_stories", ["release_date"])

    # 2. Create audit_results
    op.create_table(
        "audit_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "story_id",
            sa.String(36),
            sa.ForeignKey("audit_stories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("captured", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("lag_hours", sa.Float(), nullable=True),
        sa.Column(
            "matched_entry_id",
            sa.String(36),
            sa.ForeignKey("entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("matched_source", sa.String(255), nullable=True),
        sa.Column(
            "match_method", sa.String(50), nullable=False, server_default="token_window"
        ),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_results_story_id", "audit_results", ["story_id"])
    op.create_index("ix_audit_results_run_at", "audit_results", ["run_at"])
    op.create_index("ix_audit_results_captured", "audit_results", ["captured"])
    op.create_index(
        "ix_audit_results_matched_entry_id", "audit_results", ["matched_entry_id"]
    )

    # 3. Seed verified benchmark stories
    now_dt = datetime.now(UTC)
    stories_table = sa.table(
        "audit_stories",
        sa.column("id", sa.String),
        sa.column("title", sa.String),
        sa.column("lab_name", sa.String),
        sa.column("region", sa.String),
        sa.column("release_date", sa.DateTime),
        sa.column("canonical_url", sa.String),
        sa.column("model_names", sa.JSON),
        sa.column("org_tokens", sa.JSON),
        sa.column("added_by", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    seed_rows = []
    for s in BENCHMARK_STORIES_SEED:
        seed_rows.append(
            {
                "id": s["id"],
                "title": s["title"],
                "lab_name": s["lab_name"],
                "region": s["region"],
                "release_date": s["release_date"],
                "canonical_url": s["canonical_url"],
                "model_names": s["model_names"],
                "org_tokens": s["org_tokens"],
                "added_by": s["added_by"],
                "created_at": now_dt,
                "updated_at": now_dt,
            }
        )

    op.bulk_insert(stories_table, seed_rows)


def downgrade() -> None:
    """Drop audit_results and audit_stories tables."""
    op.drop_table("audit_results")
    op.drop_table("audit_stories")
