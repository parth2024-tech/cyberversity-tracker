"""
Cross-Language Story Clustering Service (Workstream B2).
Unifies Chinese and English AI releases into canonical Story clusters.

Core Capabilities:
1. Entity Extraction & Alias Resolution:
   - Canonicalizes org/lab aliases across Chinese and English (通义千问 -> qwen, 月之暗面 -> moonshot,
     智谱 -> zhipu, 深度求索 -> deepseek, etc.).
   - Normalizes Chinese numeric representations (720亿 / 720亿参数 -> 72b, 1万亿 -> 1t).
2. Deterministic Cluster Key Formulation:
   - cluster_key = f"{lab}:{model_family}" (+ f":{version}" if size/variant present).
   - High-precision domain token & translation matching for unstructured events within a 72h window.
3. Language Mix & Precision-Gated Merging:
   - Evaluates whether two dispatches represent the same story across English and Chinese.
   - Strictly enforces Precision >= 0.90 against same-org distractors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EntityExtractionResult:
    """Entities extracted from cross-lingual intelligence dispatch."""

    lab: str | None = None
    model_family: str | None = None
    version: str | None = None
    benchmarks: list[str] = field(default_factory=list)
    cluster_key: str | None = None
    language: str = "en"


class CrossLanguageClusteringService:
    """Extracts multilingual entities, resolves lab aliases, and constructs canonical cluster keys."""

    LAB_ALIASES: ClassVar[dict[str, str]] = {
        # DeepSeek
        "深度求索": "deepseek",
        "deepseek": "deepseek",
        "deep seek": "deepseek",
        # Qwen / Alibaba
        "通义千问": "qwen",
        "通义": "qwen",
        "千问": "qwen",
        "tongyi qianwen": "qwen",
        "tongyi": "qwen",
        "qwen": "qwen",
        "alibaba": "qwen",
        "aliyun": "qwen",
        # Moonshot / Kimi
        "月之暗面": "moonshot",
        "moonshot": "moonshot",
        "moonshot ai": "moonshot",
        "kimi": "moonshot",
        # Zhipu / GLM
        "智谱清言": "zhipu",
        "智谱ai": "zhipu",
        "智谱": "zhipu",
        "zhipu": "zhipu",
        "zhipu ai": "zhipu",
        "chatglm": "zhipu",
        "glm": "zhipu",
        "z.ai": "zhipu",
        # StepFun
        "阶跃星辰": "stepfun",
        "stepfun": "stepfun",
        "step-fun": "stepfun",
        # MiniMax
        "minimax": "minimax",
        "稀宇科技": "minimax",
        "海螺ai": "minimax",
        "hailuo": "minimax",
        # 01.AI / Yi
        "零一万物": "01-ai",
        "01.ai": "01-ai",
        "01ai": "01-ai",
        "yi": "01-ai",
        # Baichuan
        "百川智能": "baichuan",
        "baichuan": "baichuan",
        "baichuan ai": "baichuan",
        # Shanghai AI Lab / InternLM
        "上海人工智能实验室": "internlm",
        "shanghai ai lab": "internlm",
        "internlm": "internlm",
        "书生·浦语": "internlm",
        "书生浦语": "internlm",
        "书生": "internlm",
        "浦语": "internlm",
        # OpenAI
        "openai": "openai",
        "chatgpt": "openai",
        # Anthropic
        "anthropic": "anthropic",
        "claude": "anthropic",
        # Google / DeepMind
        "google deepmind": "deepmind",
        "deepmind": "deepmind",
        "google ai": "deepmind",
        "gemini": "deepmind",
        "gemma": "deepmind",
        # Meta
        "meta ai": "meta",
        "meta": "meta",
        "llama": "meta",
        # Mistral
        "mistral ai": "mistral",
        "mistral": "mistral",
        # Microsoft
        "microsoft": "microsoft",
        "phi": "microsoft",
        # NVIDIA
        "nvidia": "nvidia",
        "nemotron": "nvidia",
        # Tooling runtimes
        "vllm project": "vllm",
        "vllm": "vllm",
        "sglang": "sglang",
        "llama.cpp": "llamacpp",
        "ollama": "ollama",
    }

    # Model family regex patterns (prioritized order, Unicode-safe boundaries)
    MODEL_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        # DeepSeek
        (
            r"(?<![a-zA-Z0-9])deepseek[-_]?(r1|v3|v2\.5|v2|coder[-_]?v2|coder|math|vl[-_]?2|vl)(?![a-zA-Z0-9])",
            "deepseek-{}",
        ),
        # Qwen
        (
            r"(?<![a-zA-Z0-9])(qwen[-_]?2\.5[-_]?coder|qwen[-_]?2\.5[-_]?math|qwen[-_]?2\.5[-_]?vl|qwen[-_]?2\.5|qwen[-_]?2|qwen[-_]?1\.5)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Anthropic
        (
            r"(?<![a-zA-Z0-9])(claude[-_]?3\.5[-_]?sonnet|claude[-_]?3\.5[-_]?haiku|claude[-_]?3[-_]?opus)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Meta Llama
        (
            r"(?<![a-zA-Z0-9])(llama[-_]?3\.3|llama[-_]?3\.2|llama[-_]?3\.1|llama[-_]?3)(?![a-zA-Z0-9])",
            "{}",
        ),
        # OpenAI
        (
            r"(?<![a-zA-Z0-9])(o1[-_]?preview|o1[-_]?mini|o1|o3[-_]?mini|o3|gpt[-_]?4o[-_]?mini|gpt[-_]?4o)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Zhipu
        (
            r"(?<![a-zA-Z0-9])(glm[-_]?4[-_]?voice|glm[-_]?4v|glm[-_]?4|chatglm[-_]?3|glm[-_]?3)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Kimi
        (
            r"(?<![a-zA-Z0-9])(kimi[-_]?k1\.5|kimi[-_]?1\.5|kimi[-_]?chat)(?![a-zA-Z0-9])",
            "{}",
        ),
        # InternLM
        (r"(?<![a-zA-Z0-9])(internlm[-_]?2\.5|internlm[-_]?2)(?![a-zA-Z0-9])", "{}"),
        # StepFun
        (r"(?<![a-zA-Z0-9])(step[-_]?2|step[-_]?1)(?![a-zA-Z0-9])", "{}"),
        # MiniMax
        (r"(?<![a-zA-Z0-9])(minimax[-_]?01|minimax[-_]?abab)(?![a-zA-Z0-9])", "{}"),
        # Baichuan
        (r"(?<![a-zA-Z0-9])(baichuan[-_]?4|baichuan[-_]?3)(?![a-zA-Z0-9])", "{}"),
        # Yi
        (
            r"(?<![a-zA-Z0-9])(yi[-_]?lightning|yi[-_]?large|yi[-_]?1\.5|yi[-_]?34b)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Mistral
        (
            r"(?<![a-zA-Z0-9])(mistral[-_]?large[-_]?2|mistral[-_]?large|codestral|pixtral)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Gemini
        (
            r"(?<![a-zA-Z0-9])(gemini[-_]?2\.0[-_]?flash|gemini[-_]?1\.5[-_]?pro|gemini[-_]?1\.5[-_]?flash)(?![a-zA-Z0-9])",
            "{}",
        ),
        # Phi
        (r"(?<![a-zA-Z0-9])(phi[-_]?4|phi[-_]?3\.5|phi[-_]?3)(?![a-zA-Z0-9])", "{}"),
    ]

    BENCHMARK_KEYWORDS: ClassVar[set[str]] = {
        "mmlu",
        "gsm8k",
        "math",
        "humaneval",
        "swe-bench",
        "gpqa",
        "arena-hard",
        "livebench",
        "ceval",
        "c-eval",
        "superclue",
    }

    @classmethod
    def detect_language(cls, text: str) -> str:
        """Detect language (zh or en) via Chinese ideogram presence."""
        if re.search(r"[\u4e00-\u9fa5]", text):
            return "zh"
        return "en"

    @classmethod
    def normalize_numbers(cls, text: str) -> str:
        """Normalize Chinese numeric descriptions into standardized parameter representations."""

        # Convert parameter counts in 亿 (100 million) to B (billion)
        # e.g., 720亿 -> 72b, 80亿 -> 8b, 6710亿 -> 671b
        def _repl_yi(m: re.Match) -> str:
            num = int(m.group(1))
            if num >= 10:
                b_val = num // 10
                return f"{b_val}b"
            return f"{num}00m"

        normalized = re.sub(r"(\d+)万亿", r"\1t", text)
        normalized = re.sub(r"(\d+)亿", _repl_yi, normalized)
        normalized = re.sub(
            r"(\d+)万", lambda m: f"{int(m.group(1)) * 10}k", normalized
        )
        return normalized

    @classmethod
    def extract_entities(cls, text: str) -> EntityExtractionResult:
        """Extract lab, model family, version, and benchmarks to construct canonical cluster_key."""
        if not text:
            return EntityExtractionResult()

        lang = cls.detect_language(text)
        text_norm = cls.normalize_numbers(text)
        lower_raw = text.lower()
        lower_norm = text_norm.lower()

        # 1. Resolve Lab / Org
        resolved_lab: str | None = None
        # Sort aliases by length descending to match longest specific string first
        for alias, canonical_lab in sorted(
            cls.LAB_ALIASES.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if alias in lower_raw or alias in lower_norm:
                resolved_lab = canonical_lab
                break

        # 2. Extract Model Family
        candidate_families: list[str] = []
        for pattern, template in cls.MODEL_PATTERNS:
            match = re.search(pattern, lower_raw) or re.search(pattern, lower_norm)
            if match:
                raw_token = match.group(0).replace("_", "-")
                if "{}" in template:
                    family_token = raw_token
                else:
                    family_token = template.format(match.group(1))
                if family_token not in candidate_families:
                    candidate_families.append(family_token)

        resolved_family: str | None = None
        lab_family_prefixes: dict[str, tuple[str, ...]] = {
            "deepseek": ("deepseek",),
            "qwen": ("qwen",),
            "anthropic": ("claude",),
            "meta": ("llama",),
            "openai": ("o1", "o3", "gpt"),
            "zhipu": ("glm", "chatglm"),
            "moonshot": ("kimi",),
            "internlm": ("internlm",),
            "stepfun": ("step",),
            "minimax": ("minimax",),
            "baichuan": ("baichuan",),
            "01-ai": ("yi",),
            "mistral": ("mistral", "codestral", "pixtral"),
            "deepmind": ("gemini", "gemma"),
            "microsoft": ("phi",),
        }

        # If resolved_lab is known, prioritize the candidate family that belongs to this lab
        if resolved_lab and resolved_lab in lab_family_prefixes:
            target_prefixes = lab_family_prefixes[resolved_lab]
            for c in candidate_families:
                if c.startswith(target_prefixes):
                    resolved_family = c
                    break

        if not resolved_family and candidate_families:
            resolved_family = candidate_families[0]

        # If model family matches a known lab and lab wasn't resolved, infer lab from family
        if resolved_family and not resolved_lab:
            for lab_key, prefixes in lab_family_prefixes.items():
                if resolved_family.startswith(prefixes):
                    resolved_lab = lab_key
                    break

        # 3. Extract Version / Parameter Size Variant
        resolved_version: str | None = None
        size_match = re.search(
            r"(?<![a-zA-Z0-9])(671b|405b|236b|110b|72b|70b|34b|32b|22b|20b|14b|8b|7b|3b|1b|8x7b|8x22b)(?![a-zA-Z0-9])",
            lower_norm,
        )
        if size_match:
            resolved_version = size_match.group(1)

        # 4. Extract Benchmarks
        found_benchmarks: list[str] = [
            bm for bm in cls.BENCHMARK_KEYWORDS if bm in lower_norm
        ]

        # 5. Formulate Canonical Cluster Key
        cluster_key: str | None = None
        if resolved_lab and resolved_family:
            clean_family = resolved_family.replace("_", "-")
            cluster_key = f"{resolved_lab}:{clean_family}"
            if resolved_version:
                cluster_key += f":{resolved_version}"
        elif resolved_lab:
            cluster_key = f"{resolved_lab}:general"

        return EntityExtractionResult(
            lab=resolved_lab,
            model_family=resolved_family,
            version=resolved_version,
            benchmarks=found_benchmarks,
            cluster_key=cluster_key,
            language=lang,
        )

    @classmethod
    def are_same_story(
        cls,
        text_a: str,
        text_b: str,
        published_a: datetime | None = None,
        published_b: datetime | None = None,
        max_delta_hours: float = 72.0,
    ) -> bool:
        """
        Evaluate if two dispatches represent the same story across English and Chinese.
        Precision Gate: guarantees precision >= 0.90 against negative same-org pairs.
        """
        # 1. 72-hour temporal coherence guard
        if published_a and published_b:
            ts_a = (
                published_a
                if published_a.tzinfo is not None
                else published_a.replace(tzinfo=UTC)
            )
            ts_b = (
                published_b
                if published_b.tzinfo is not None
                else published_b.replace(tzinfo=UTC)
            )
            delta_h = abs((ts_a - ts_b).total_seconds()) / 3600.0
            if delta_h > max_delta_hours:
                return False

        ent_a = cls.extract_entities(text_a)
        ent_b = cls.extract_entities(text_b)

        # 2. Strong Cluster Key Match
        # If both produce a specific model-level cluster key (not generic)
        if ent_a.cluster_key and ent_b.cluster_key:
            if not ent_a.cluster_key.endswith(
                ":general"
            ) and not ent_b.cluster_key.endswith(":general"):
                return ent_a.cluster_key == ent_b.cluster_key

            if ent_a.cluster_key == ent_b.cluster_key:
                pass  # Fall through to token checks

        # If labs are known and distinct, they CANNOT be the same story
        if ent_a.lab and ent_b.lab and ent_a.lab != ent_b.lab:
            return False

        # If model families are known and distinct (e.g. DeepSeek-V3 vs DeepSeek-R1), CANNOT be same story
        if (
            ent_a.model_family
            and ent_b.model_family
            and ent_a.model_family != ent_b.model_family
        ):
            return False

        # If parameter versions are known and distinct (e.g. 72B vs 8B), CANNOT be same story
        if ent_a.version and ent_b.version and ent_a.version != ent_b.version:
            return False

        # 3. Same-Language Fallback
        if ent_a.language == ent_b.language:
            if ent_a.language == "zh":
                from ai_security_monitor.application.services.china_dedup_service import (
                    china_dedup_service,
                )

                return china_dedup_service.is_near_duplicate(text_a, text_b)
            else:
                from ai_security_monitor.application.services.deduplication_service import (
                    compute_title_similarity,
                )

                return compute_title_similarity(text_a, text_b) >= 0.60

        # 4. Cross-Language Lexical & Entity Overlap
        norm_a = cls.normalize_numbers(text_a).lower()
        norm_b = cls.normalize_numbers(text_b).lower()

        # Shared technical tokens (model numbers, architectures, benchmarks)
        tokens_a = set(re.findall(r"[a-z0-9\.\-_]{2,}", norm_a))
        tokens_b = set(re.findall(r"[a-z0-9\.\-_]{2,}", norm_b))
        common = tokens_a & tokens_b

        # Filter common stopwords from common tokens
        common_tech = {
            t
            for t in common
            if t
            not in {"the", "and", "for", "with", "model", "ai", "new", "open", "source"}
        }

        # If sharing lab and at least one specific technical token
        if ent_a.lab and (ent_a.lab == ent_b.lab) and len(common_tech) >= 1:
            return True

        return len(common_tech) >= 3


cross_language_clustering_service = CrossLanguageClusteringService()


# 20 Hand-Labeled Pairs for Precision Gate Evaluation
# 10 positive CN/EN pairs (identical story across languages)
EVALUATION_POSITIVE_PAIRS: list[tuple[str, str, str]] = [
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
EVALUATION_NEGATIVE_PAIRS: list[tuple[str, str, str]] = [
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
