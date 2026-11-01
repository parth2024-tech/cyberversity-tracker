"""
Canonical AI Entity Taxonomy and Multilingual Alias Registry.

Defines language-independent canonical entities (frontier labs, foundation models,
infrastructure runtimes) with their multilingual and script-specific aliases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AliasSpec:
    """Specification for an entity alias."""

    alias: str
    lang: str | None = None  # 'zh', 'en', None (universal)
    script: str | None = None  # 'Hans', 'Hant', 'Latn'
    source: str = "manual"  # 'manual', 'org_rename', 'mined'
    confidence: float = 1.0


@dataclass(frozen=True)
class CanonicalEntitySpec:
    """Specification for a canonical entity."""

    canonical_id: str
    type: str  # 'lab', 'model', 'benchmark', 'runtime', 'org'
    canonical_name: str
    status: str = "active"
    aliases: list[AliasSpec] = field(default_factory=list)


CANONICAL_ENTITIES_SEED: list[CanonicalEntitySpec] = [
    # Labs & Organizations
    CanonicalEntitySpec(
        canonical_id="lab:deepseek",
        type="lab",
        canonical_name="DeepSeek",
        aliases=[
            AliasSpec(alias="DeepSeek", lang="en"),
            AliasSpec(alias="deepseek-ai", lang="en"),
            AliasSpec(alias="deepseek", lang="en"),
            AliasSpec(alias="深度求索", lang="zh", script="Hans"),
            AliasSpec(alias="杭州深度求索", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:qwen",
        type="lab",
        canonical_name="Alibaba Qwen",
        aliases=[
            AliasSpec(alias="Qwen", lang="en"),
            AliasSpec(alias="Alibaba Qwen", lang="en"),
            AliasSpec(alias="QwenLM", lang="en"),
            AliasSpec(alias="Alibaba-NLP", lang="en"),
            AliasSpec(alias="通义千问", lang="zh", script="Hans"),
            AliasSpec(alias="通義千問", lang="zh", script="Hant"),
            AliasSpec(alias="阿里通义", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:zhipu",
        type="lab",
        canonical_name="Zhipu AI",
        aliases=[
            AliasSpec(alias="Zhipu AI", lang="en"),
            AliasSpec(alias="ZhipuAI", lang="en"),
            AliasSpec(alias="THUDM", lang="en"),
            AliasSpec(alias="zai-org", lang="en", source="org_rename"),  # HF renamed org
            AliasSpec(alias="智谱AI", lang="zh", script="Hans"),
            AliasSpec(alias="智谱", lang="zh", script="Hans"),
            AliasSpec(alias="北京智谱华章", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:moonshot",
        type="lab",
        canonical_name="Moonshot AI",
        aliases=[
            AliasSpec(alias="Moonshot AI", lang="en"),
            AliasSpec(alias="MoonshotAI", lang="en"),
            AliasSpec(alias="moonshotai", lang="en"),
            AliasSpec(alias="Kimi", lang="en"),
            AliasSpec(alias="月之暗面", lang="zh", script="Hans"),
            AliasSpec(alias="北京月之暗面", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:shanghai_ai_lab",
        type="lab",
        canonical_name="Shanghai AI Laboratory",
        aliases=[
            AliasSpec(alias="Shanghai AI Laboratory", lang="en"),
            AliasSpec(alias="Shanghai_AI_Laboratory", lang="en"),
            AliasSpec(alias="InternLM", lang="en"),
            AliasSpec(alias="LMDeploy", lang="en"),
            AliasSpec(alias="上海人工智能实验室", lang="zh", script="Hans"),
            AliasSpec(alias="书生·浦语", lang="zh", script="Hans"),
            AliasSpec(alias="书生浦语", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:minimax",
        type="lab",
        canonical_name="MiniMax",
        aliases=[
            AliasSpec(alias="MiniMax", lang="en"),
            AliasSpec(alias="MiniMaxAI", lang="en"),
            AliasSpec(alias="稀宇科技", lang="zh", script="Hans"),
            AliasSpec(alias="名之梦", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:stepfun",
        type="lab",
        canonical_name="StepFun",
        aliases=[
            AliasSpec(alias="StepFun", lang="en"),
            AliasSpec(alias="stepfun-ai", lang="en"),
            AliasSpec(alias="阶跃星辰", lang="zh", script="Hans"),
            AliasSpec(alias="階躍星辰", lang="zh", script="Hant"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:01_ai",
        type="lab",
        canonical_name="01.AI",
        aliases=[
            AliasSpec(alias="01.AI", lang="en"),
            AliasSpec(alias="01-ai", lang="en"),
            AliasSpec(alias="Yi", lang="en"),
            AliasSpec(alias="零一万物", lang="zh", script="Hans"),
            AliasSpec(alias="零一萬物", lang="zh", script="Hant"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:baai",
        type="lab",
        canonical_name="BAAI",
        aliases=[
            AliasSpec(alias="BAAI", lang="en"),
            AliasSpec(alias="北京智源人工智能研究院", lang="zh", script="Hans"),
            AliasSpec(alias="智源研究院", lang="zh", script="Hans"),
            AliasSpec(alias="智源", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:modelscope",
        type="lab",
        canonical_name="ModelScope",
        aliases=[
            AliasSpec(alias="ModelScope", lang="en"),
            AliasSpec(alias="modelscope", lang="en"),
            AliasSpec(alias="魔搭社区", lang="zh", script="Hans"),
            AliasSpec(alias="魔搭", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:openai",
        type="lab",
        canonical_name="OpenAI",
        aliases=[
            AliasSpec(alias="OpenAI", lang="en"),
            AliasSpec(alias="openai", lang="en"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:anthropic",
        type="lab",
        canonical_name="Anthropic",
        aliases=[
            AliasSpec(alias="Anthropic", lang="en"),
            AliasSpec(alias="anthropic", lang="en"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:meta_ai",
        type="lab",
        canonical_name="Meta AI",
        aliases=[
            AliasSpec(alias="Meta AI", lang="en"),
            AliasSpec(alias="FAIR", lang="en"),
            AliasSpec(alias="Facebook AI Research", lang="en"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="lab:mistral",
        type="lab",
        canonical_name="Mistral AI",
        aliases=[
            AliasSpec(alias="Mistral AI", lang="en"),
            AliasSpec(alias="MistralAI", lang="en"),
            AliasSpec(alias="mistral", lang="en"),
        ],
    ),

    # Frontier Models
    CanonicalEntitySpec(
        canonical_id="model:deepseek_v3",
        type="model",
        canonical_name="DeepSeek-V3",
        aliases=[
            AliasSpec(alias="DeepSeek-V3", lang="en"),
            AliasSpec(alias="DeepSeek V3", lang="en"),
            AliasSpec(alias="deepseek-v3", lang="en"),
            AliasSpec(alias="深度求索V3", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="model:deepseek_r1",
        type="model",
        canonical_name="DeepSeek-R1",
        aliases=[
            AliasSpec(alias="DeepSeek-R1", lang="en"),
            AliasSpec(alias="DeepSeek R1", lang="en"),
            AliasSpec(alias="deepseek-r1", lang="en"),
            AliasSpec(alias="R1", lang="en"),
            AliasSpec(alias="深度求索R1", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="model:qwen_2_5",
        type="model",
        canonical_name="Qwen2.5",
        aliases=[
            AliasSpec(alias="Qwen2.5", lang="en"),
            AliasSpec(alias="Qwen 2.5", lang="en"),
            AliasSpec(alias="Qwen-2.5", lang="en"),
            AliasSpec(alias="通义千问2.5", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="model:glm_4",
        type="model",
        canonical_name="GLM-4",
        aliases=[
            AliasSpec(alias="GLM-4", lang="en"),
            AliasSpec(alias="GLM4", lang="en"),
            AliasSpec(alias="GLM-4-Plus", lang="en"),
            AliasSpec(alias="GLM-4-Flash", lang="en"),
            AliasSpec(alias="智谱GLM-4", lang="zh", script="Hans"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="model:kimi_k1_5",
        type="model",
        canonical_name="Kimi k1.5",
        aliases=[
            AliasSpec(alias="Kimi k1.5", lang="en"),
            AliasSpec(alias="Kimi-k1.5", lang="en"),
            AliasSpec(alias="Kimi 1.5", lang="en"),
        ],
    ),
    CanonicalEntitySpec(
        canonical_id="model:internlm_2_5",
        type="model",
        canonical_name="InternLM2.5",
        aliases=[
            AliasSpec(alias="InternLM2.5", lang="en"),
            AliasSpec(alias="InternLM 2.5", lang="en"),
            AliasSpec(alias="书生浦语2.5", lang="zh", script="Hans"),
        ],
    ),
]


def build_alias_index() -> dict[str, str]:
    """Build normalized lower-case lookup map from alias to canonical_id."""
    index: dict[str, str] = {}
    for entity in CANONICAL_ENTITIES_SEED:
        for alias_spec in entity.aliases:
            norm = alias_spec.alias.strip().lower()
            if norm:
                index[norm] = entity.canonical_id
        # Also index canonical name
        index[entity.canonical_name.strip().lower()] = entity.canonical_id
    return index
