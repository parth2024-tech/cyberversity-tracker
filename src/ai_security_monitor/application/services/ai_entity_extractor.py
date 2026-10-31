"""
AI Entity and Benchmark Extractor for Knowledge Graph (Pillar 4).
Performs deterministic, high-precision extraction of Model Names, GitHub Repos,
ArXiv Preprints, Benchmarks & Metrics, Organizations, and Runtimes.
"""

from __future__ import annotations

import re
from uuid import UUID

from ai_security_monitor.domain.entities import AIEntity, EntityType, Entry

# 1. Frontier & Open-Weight Model Regex Patterns
MODEL_PATTERNS = [
    r"\b(DeepSeek-(?:R1|V3|V2\.5|V2|Coder(?:-V2)?|Math|Prover))\b",
    r"\b(Qwen(?:2\.5|2|1\.5)?-(?:Coder|Math|VL|Omni|Turbo|Plus|Max|\d+B(?:\.\d+B)?))\b",
    r"\b(Llama-(?:3\.3|3\.2|3\.1|3|2)-(?:\d+B|Instruct|Vision|[0-9]+b))\b",
    r"\b(Claude-(?:3\.7-Sonnet|3\.5-Sonnet|3\.5-Haiku|3-Opus|3-Sonnet|3-Haiku))\b",
    r"\b(Gemini-(?:2\.0-Flash|2\.0-Pro|1\.5-Pro|1\.5-Flash|Ultra|Flash-Thinking))\b",
    r"\b(GPT-4o(?:-mini)?|GPT-4\.5|o1(?:-mini|-preview)?|o3(?:-mini)?)\b",
    r"\b(Mistral-(?:Large(?:-2)?|Small|Nemo|Pixtral|Codestral|Embed))\b",
    r"\b(Gemma-(?:2|1\.1)-(?:\d+b|Instruct))\b",
    r"\b(Phi-(?:4|3\.5|3)-(?:mini|medium|vision))\b",
    r"\b(Kimi-(?:k1\.5|1\.5|Chat))\b",
    r"\b(GLM-(?:4-Voice|4-9B|4-Long|4|Zero))\b",
    r"\b(FLUX\.1-(?:dev|schnell|pro))\b",
    r"\b(Stable Diffusion 3\.5|SDXL)\b",
]

# 2. Known AI Organizations and Labs
ORGANIZATION_PATTERNS = [
    r"\b(DeepSeek)\b",
    r"\b(Anthropic)\b",
    r"\b(OpenAI)\b",
    r"\b(Google DeepMind|DeepMind)\b",
    r"\b(Meta AI|Meta)\b",
    r"\b(Microsoft)\b",
    r"\b(Alibaba Cloud|Alibaba|Qwen Team)\b",
    r"\b(Mistral AI)\b",
    r"\b(Zhipu AI)\b",
    r"\b(Moonshot AI)\b",
    r"\b(ByteDance)\b",
    r"\b(NVIDIA)\b",
    r"\b(xAI)\b",
]

# 3. AI Benchmarks
BENCHMARK_NAMES = [
    "SWE-bench Verified",
    "SWE-bench Lite",
    "SWE-bench",
    "MMLU-Pro",
    "MMLU",
    "HumanEval Plus",
    "HumanEval",
    "GSM8K",
    "MATH-500",
    "MATH",
    "AIME 2026",
    "AIME 2025",
    "AIME 2024",
    "AIME",
    "Chatbot Arena",
    "GPQA Diamond",
    "GPQA",
    "LiveCodeBench",
    "ARC-AGI",
    "Arena-Hard",
    "MBPP",
]

# 4. Hardware and Inference Runtimes
HARDWARE_PATTERNS = [
    r"\b(NVIDIA (?:H100|H200|B200|GB200|Blackwell|Hopper|RTX 4090|RTX 5090))\b",
    r"\b(H100|H200|B200|GB200|Blackwell|RTX 4090|RTX 5090)\b",
    r"\b(TPU v5p|TPU v6e)\b",
    r"\b(Apple Silicon|Apple M4 Max|Apple M4|Apple M3|Apple MLX|MLX)\b",
    r"\b(vLLM|Ollama|llama\.cpp|SGLang|TensorRT-LLM)\b",
]

# 5. GitHub Repositories Regex
GITHUB_REPO_REGEX = re.compile(
    r"(?:https?://github\.com/|github\.com/)([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)

# 6. ArXiv Paper ID Regex
ARXIV_ID_REGEX = re.compile(
    r"(?:https?://arxiv\.org/(?:abs|pdf)/|arXiv:\s*)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

# 7. CVE Pattern
CVE_REGEX = re.compile(r"\b(CVE-\d{4}-\d{4,7})\b", re.IGNORECASE)


class AIEntityExtractor:
    """Extracts structured entities, benchmarks, and performance metrics from content."""

    @staticmethod
    def _find_context(text: str, match_start: int, match_end: int) -> str:
        """Extract surrounding sentence or clean 160-char window for context."""
        window_start = max(0, match_start - 80)
        window_end = min(len(text), match_end + 80)
        snippet = text[window_start:window_end].replace("\n", " ").strip()
        return snippet

    @classmethod
    def extract_from_text(cls, text: str, entry_id: UUID) -> list[AIEntity]:
        """Extract deduplicated entities from text string."""
        if not text:
            return []

        entities: list[AIEntity] = []
        seen_keys: set[tuple[str, str]] = set()

        # A. GitHub Repositories
        for match in GITHUB_REPO_REGEX.finditer(text):
            raw_repo = match.group(1).rstrip("/.")
            # Ignore common non-repo paths like issues, pull, releases
            parts = raw_repo.split("/")
            if len(parts) == 2 and parts[1] not in (
                "issues",
                "pull",
                "releases",
                "commit",
            ):
                norm_name = raw_repo.lower()
                key = (EntityType.REPOSITORY.value, norm_name)
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        AIEntity(
                            entry_id=entry_id,
                            entity_type=EntityType.REPOSITORY,
                            name=norm_name,
                            display_name=raw_repo,
                            context=cls._find_context(text, match.start(), match.end()),
                        )
                    )

        # B. ArXiv Preprints
        for match in ARXIV_ID_REGEX.finditer(text):
            arxiv_id = match.group(1)
            norm_name = arxiv_id.lower()
            key = (EntityType.ARXIV.value, norm_name)
            if key not in seen_keys:
                seen_keys.add(key)
                entities.append(
                    AIEntity(
                        entry_id=entry_id,
                        entity_type=EntityType.ARXIV,
                        name=norm_name,
                        display_name=f"arXiv:{arxiv_id}",
                        context=cls._find_context(text, match.start(), match.end()),
                    )
                )

        # C. AI Models
        for pat in MODEL_PATTERNS:
            for match in re.finditer(pat, text, re.IGNORECASE):
                matched_str = match.group(1)
                norm_name = matched_str.lower()
                key = (EntityType.MODEL.value, norm_name)
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        AIEntity(
                            entry_id=entry_id,
                            entity_type=EntityType.MODEL,
                            name=norm_name,
                            display_name=matched_str,
                            context=cls._find_context(text, match.start(), match.end()),
                        )
                    )

        # D. Benchmarks & Scores
        sorted_benchmarks = sorted(BENCHMARK_NAMES, key=len, reverse=True)
        bench_spans: list[tuple[int, int]] = []
        for bench in sorted_benchmarks:
            bench_escaped = re.escape(bench)
            pattern = rf"\b({bench_escaped})(?:(?=[^a-zA-Z0-9_-])|$)"
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.start(1), match.end(1)
                # Overlap check: skip if already covered by longer benchmark span (e.g. MMLU within MMLU-Pro)
                if any(s <= start and end <= e for s, e in bench_spans):
                    continue
                bench_spans.append((start, end))

                matched_str = match.group(1)
                norm_name = bench.lower().replace(" ", "-")
                key = (EntityType.BENCHMARK.value, norm_name)

                # Attempt bidirectional metric extraction
                metric_value: str | None = None

                # 1. Check after benchmark: e.g. "AIME 2024: 79.8%" or "SWE-bench (49.2%)"
                after_snippet = text[end : end + 30]
                after_match = re.search(
                    r"^\s*[:=(]?\s*(\d{1,3}(?:\.\d{1,2})?\s*%|\d{1,2}\.\d{1,2})",
                    after_snippet,
                )
                if after_match:
                    metric_value = after_match.group(1).strip()
                else:
                    # 2. Check before benchmark: e.g. "demonstrating 79.8% on AIME 2024"
                    before_snippet = text[max(0, start - 30) : start]
                    before_match = re.search(
                        r"(\d{1,3}(?:\.\d{1,2})?\s*%|\d{1,2}\.\d{1,2})\s*(?:on|in|at|for|score[ds]?\s*(?:of|in)?\s*)?\s*$",
                        before_snippet,
                        re.IGNORECASE,
                    )
                    if before_match:
                        metric_value = before_match.group(1).strip()

                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        AIEntity(
                            entry_id=entry_id,
                            entity_type=EntityType.BENCHMARK,
                            name=norm_name,
                            display_name=bench,
                            metric_value=metric_value,
                            context=cls._find_context(text, start, end),
                        )
                    )

        # E. AI Organizations / Labs
        for pat in ORGANIZATION_PATTERNS:
            for match in re.finditer(pat, text, re.IGNORECASE):
                org_str = match.group(1)
                norm_name = org_str.lower().replace(" ", "-")
                key = (EntityType.ORGANIZATION.value, norm_name)
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        AIEntity(
                            entry_id=entry_id,
                            entity_type=EntityType.ORGANIZATION,
                            name=norm_name,
                            display_name=org_str,
                            context=cls._find_context(text, match.start(), match.end()),
                        )
                    )

        # F. Hardware & Runtimes
        for pat in HARDWARE_PATTERNS:
            for match in re.finditer(pat, text, re.IGNORECASE):
                hw_str = match.group(1)
                norm_name = hw_str.lower().replace(" ", "-")
                key = (EntityType.HARDWARE.value, norm_name)
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        AIEntity(
                            entry_id=entry_id,
                            entity_type=EntityType.HARDWARE,
                            name=norm_name,
                            display_name=hw_str,
                            context=cls._find_context(text, match.start(), match.end()),
                        )
                    )

        # G. CVE IDs (if present in security/safeguards context)
        for match in CVE_REGEX.finditer(text):
            cve_str = match.group(1).upper()
            norm_name = cve_str.lower()
            key = (EntityType.CVE.value, norm_name)
            if key not in seen_keys:
                seen_keys.add(key)
                entities.append(
                    AIEntity(
                        entry_id=entry_id,
                        entity_type=EntityType.CVE,
                        name=norm_name,
                        display_name=cve_str,
                        context=cls._find_context(text, match.start(), match.end()),
                    )
                )

        return entities

    @classmethod
    def extract_entities(cls, entry: Entry) -> list[AIEntity]:
        """Extract all entities from entry title, summary, URL, and metadata."""
        corpus = f"{entry.title or ''}\n{entry.summary or ''}\n{entry.url or ''}"
        if entry.metadata:
            corpus += f"\n{str(entry.metadata)}"
        return cls.extract_from_text(corpus, entry_id=entry.id)


ai_entity_extractor = AIEntityExtractor()
