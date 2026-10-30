"""add_labs_and_entry_lab_id

Revision ID: c2d3e4f5a6b7
Revises: make_source_url_nullable
Create Date: 2026-10-30 21:25:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "make_source_url_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHINA_LABS_SEED = [
    {
        "id": str(uuid4()),
        "name": "DeepSeek",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["deepseek-ai"],
        "github_orgs": ["deepseek-ai"],
        "modelscope_ids": ["deepseek-ai"],
        "wechat_accounts": ["deepseek"],
        "aliases": ["deepseek", "深度求索", "deepseek-r1", "deepseek-v3", "deepseek-coder", "deepseek-math"],
        "notes": "High-efficiency open-weights frontier lab (Hangzhou High-Flyer / DeepSeek AI)",
    },
    {
        "id": str(uuid4()),
        "name": "Qwen / Alibaba",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["Qwen"],
        "github_orgs": ["QwenLM", "alibaba"],
        "modelscope_ids": ["qwen"],
        "wechat_accounts": ["Alibaba_Cloud"],
        "aliases": ["qwen", "通义千问", "qwen2.5", "qwen-vl", "qwq"],
        "notes": "Alibaba Cloud Tongyi Lab / Qwen foundation models",
    },
    {
        "id": str(uuid4()),
        "name": "Zhipu AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["THUDM", "ZhipuAI"],
        "github_orgs": ["THUDM", "zai-org"],
        "modelscope_ids": ["ZhipuAI"],
        "wechat_accounts": ["ZhipuAI"],
        "aliases": ["zhipu", "智谱", "glm-4", "chatglm", "cogview", "cogvlm"],
        "notes": "Tsinghua spin-off / GLM foundation models",
    },
    {
        "id": str(uuid4()),
        "name": "Moonshot AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["moonshotai"],
        "github_orgs": ["MoonshotAI"],
        "modelscope_ids": ["moonshotai"],
        "wechat_accounts": ["MoonshotAI"],
        "aliases": ["moonshot", "月之暗面", "kimi"],
        "notes": "Long-context reasoning pioneer / Kimi model family",
    },
    {
        "id": str(uuid4()),
        "name": "MiniMax",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["MiniMaxAI"],
        "github_orgs": ["MiniMax-AI"],
        "modelscope_ids": ["MiniMax"],
        "wechat_accounts": ["MiniMax"],
        "aliases": ["minimax", "名之梦", "abab", "minimax-text"],
        "notes": "Frontier multimodal & MoE foundation models",
    },
    {
        "id": str(uuid4()),
        "name": "StepFun",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["stepfun-ai"],
        "github_orgs": ["stepfun-ai"],
        "modelscope_ids": ["stepfun-ai"],
        "wechat_accounts": ["StepFun"],
        "aliases": ["stepfun", "阶跃星辰", "step-1", "step-2"],
        "notes": "Step series multimodal and reasoning models",
    },
    {
        "id": str(uuid4()),
        "name": "ByteDance Seed",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["ByteDance"],
        "github_orgs": ["bytedance"],
        "modelscope_ids": ["ByteDance"],
        "wechat_accounts": ["ByteDance"],
        "aliases": ["bytedance", "字节跳动", "doubao", "豆包", "seed-tts"],
        "notes": "ByteDance AI Lab / Doubao foundation models",
    },
    {
        "id": str(uuid4()),
        "name": "Tencent Hunyuan",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["tencent"],
        "github_orgs": ["Tencent"],
        "modelscope_ids": ["Tencent-Hunyuan"],
        "wechat_accounts": ["Tencent"],
        "aliases": ["hunyuan", "混元", "tencent hunyuan"],
        "notes": "Tencent Hunyuan foundation models & HunyuanDiT",
    },
    {
        "id": str(uuid4()),
        "name": "Baidu",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["baidu"],
        "github_orgs": ["PaddlePaddle", "baidu"],
        "modelscope_ids": ["baidu"],
        "wechat_accounts": ["Baidu"],
        "aliases": ["baidu", "百度", "ernie", "文心一言", "paddlepaddle"],
        "notes": "Baidu Ernie foundation models & PaddlePaddle framework",
    },
    {
        "id": str(uuid4()),
        "name": "Huawei",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["Huawei", "Noah-Ark"],
        "github_orgs": ["huawei-noah"],
        "modelscope_ids": ["Huawei"],
        "wechat_accounts": ["Huawei"],
        "aliases": ["huawei", "华为", "pangu", "盘古", "ascend", "noah's ark"],
        "notes": "Huawei Noah's Ark Lab / Pangu foundation models & Ascend AI",
    },
    {
        "id": str(uuid4()),
        "name": "iFlytek",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["iFLYTEK"],
        "github_orgs": ["iflytek"],
        "modelscope_ids": ["iFLYTEK"],
        "wechat_accounts": ["iFLYTEK"],
        "aliases": ["iflytek", "科大讯飞", "spark", "星火"],
        "notes": "iFlytek Spark cognitive foundation model family",
    },
    {
        "id": str(uuid4()),
        "name": "Shanghai AI Lab",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["internlm", "Shanghai_AI_Laboratory"],
        "github_orgs": ["InternLM"],
        "modelscope_ids": ["Shanghai_AI_Laboratory"],
        "wechat_accounts": ["Shanghai_AI_Laboratory"],
        "aliases": ["shanghai ai lab", "上海人工智能实验室", "internlm", "书生", "lmdeploy"],
        "notes": "Shanghai Artificial Intelligence Laboratory / InternLM ecosystem",
    },
    {
        "id": str(uuid4()),
        "name": "01.AI",
        "region": "china",
        "country": "CN",
        "hf_orgs": ["01-ai"],
        "github_orgs": ["01-ai"],
        "modelscope_ids": ["01ai"],
        "wechat_accounts": ["01ai"],
        "aliases": ["01.ai", "01-ai", "零一万物", "yi-", "yi-34b", "yi-lightning"],
        "notes": "Kai-Fu Lee founded frontier lab / Yi foundation models",
    },
]


def upgrade() -> None:
    # 1. Create labs table
    op.create_table(
        "labs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column("country", sa.String(length=10), nullable=False),
        sa.Column("hf_orgs", sa.JSON(), nullable=False),
        sa.Column("github_orgs", sa.JSON(), nullable=False),
        sa.Column("modelscope_ids", sa.JSON(), nullable=False),
        sa.Column("wechat_accounts", sa.JSON(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_labs_name", "labs", ["name"], unique=True)
    op.create_index("ix_labs_region", "labs", ["region"])

    # 2. Add lab_id and subject_region to entries table
    with op.batch_alter_table("entries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("lab_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("subject_region", sa.String(length=50), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_entries_lab_id",
            "labs",
            ["lab_id"],
            ["id"],
        )
        batch_op.create_index("ix_entries_lab_id", ["lab_id"])
        batch_op.create_index("ix_entries_subject_region", ["subject_region"])

    # 3. Seed verified China frontier AI labs
    now_dt = datetime.now(UTC)
    labs_table = sa.table(
        "labs",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("region", sa.String),
        sa.column("country", sa.String),
        sa.column("hf_orgs", sa.JSON),
        sa.column("github_orgs", sa.JSON),
        sa.column("modelscope_ids", sa.JSON),
        sa.column("wechat_accounts", sa.JSON),
        sa.column("aliases", sa.JSON),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    rows = []
    for lab in CHINA_LABS_SEED:
        rows.append(
            {
                "id": lab["id"],
                "name": lab["name"],
                "region": lab["region"],
                "country": lab["country"],
                "hf_orgs": lab["hf_orgs"],
                "github_orgs": lab["github_orgs"],
                "modelscope_ids": lab["modelscope_ids"],
                "wechat_accounts": lab["wechat_accounts"],
                "aliases": lab["aliases"],
                "notes": lab["notes"],
                "created_at": now_dt,
                "updated_at": now_dt,
            }
        )
    op.bulk_insert(labs_table, rows)


def downgrade() -> None:
    with op.batch_alter_table("entries", schema=None) as batch_op:
        batch_op.drop_index("ix_entries_subject_region")
        batch_op.drop_index("ix_entries_lab_id")
        batch_op.drop_constraint("fk_entries_lab_id", type_="foreignkey")
        batch_op.drop_column("subject_region")
        batch_op.drop_column("lab_id")

    op.drop_index("ix_labs_region", table_name="labs")
    op.drop_index("ix_labs_name", table_name="labs")
    op.drop_table("labs")
