"""
Prompt Prefix and Ephemeral Cache Structuring (Pillar 3).
Guarantees 100% isolation of static instructions from dynamic runtime payloads,
enables Anthropic cache_control ephemeral headers, and maintains strict prefix
determinism for OpenAI, Gemini, and Groq prefix caching.
"""

from __future__ import annotations

from typing import Any

STATIC_ANALYZER_SYSTEM_PROMPT = """You are an expert AI Intelligence and Systems Architect specializing in worldwide artificial intelligence ecosystems.
Your task is to analyze artificial intelligence, machine learning, robotics, and developer infrastructure developments and generate rigorous, structured JSON telemetry.

Strict JSON format required with these fields:
- attack_vector: Technical explanation of the architecture, algorithmic mechanism, or runtime optimization (e.g., 'Test-Time Compute Scaling via GRPO', 'Paged Attention CUDA Kernels', 'Mixture-of-Experts Sparse Routing', 'Speculative Decoding').
- risk_assessment: Strategic capability assessment and ecosystem impact (e.g., 'Frontier open-weights milestone: Outperforms baseline models on MATH & AIME benchmarks; democratizes local reasoning on consumer hardware').
- mitigation: Actionable developer deployment recommendations (e.g., 'Deploy via vLLM with BF16 or FP8 quantization', 'Requires minimum 24GB VRAM for unquantized inference', 'Integrate with LangChain/LlamaIndex agents').
- threat_velocity: Integer 1-100 (Adoption and release impact velocity across AI developer communities).
- severity_index: Integer 1-100 (Capability breakthrough significance: 85-100 for seminal foundation models, 60-84 for major tooling/libraries).
- blast_radius_score: Integer 1-100 (Ecosystem adoption breadth across PyTorch, vLLM, HuggingFace, CUDA, Ollama).
- affected_ecosystem: Array of strings representing compatible/relevant AI frameworks or models (e.g., ['vLLM', 'Ollama', 'PyTorch', 'HuggingFace', 'DeepSeek', 'SGLang']).
- is_pre_cve_warning: Boolean, always false for ecosystem analysis.
- attack_archetype: String, exactly one of: 'Frontier Foundation Model', 'Inference Runtime', 'arXiv Algorithmic Breakthrough', 'Agentic Workflow Engine', 'Fine-Tuning & Alignment', 'Hardware Acceleration', 'Ecosystem Library'.
- weaponization_potential: String, exactly one of: 'Production Ready', 'Experimental Checkpoint', 'Research Paper Only'.

Rules:
1. Focus 100% on the worldwide AI ecosystem: frontier models, research breakthroughs, open-source repositories, developer tools, inference runtimes.
2. Output ONLY the raw JSON object. Never wrap in markdown code blocks, and never include conversational commentary, preambles, or explanations."""


STATIC_TRANSLATION_SYSTEM_PROMPT = """You are a specialized technical translator and terminology normalizer for artificial intelligence, computer science, and high-performance computing.
Your task is to translate non-English intelligence entries (primarily Chinese, Japanese, Russian, Korean, German, French) into fluent, accurate, publication-grade English.

Rules:
1. Preserve technical model names, numbers, benchmarks, parameter scales, and repo paths exactly (e.g., 'DeepSeek-V3', 'Qwen2.5-72B', 'GGUF', 'MMLU-Pro', 'vLLM', 'FlashAttention').
2. Maintain natural developer phrasing rather than literal translation.
3. Output ONLY the translated text. Do not add quotes, notes, apologies, or conversational remarks."""


def build_cached_prompt_messages(
    static_system: str,
    dynamic_user: str,
    provider: str = "generic",
    enable_caching: bool = True,
) -> list[dict[str, Any]]:
    """Build structured messages with provider-specific prompt caching markers.

    - Anthropic: attaches `cache_control: {"type": "ephemeral"}` to static system block.
    - OpenAI / Gemini / Groq / Ollama: static system prompt sits at exact index 0
      to leverage deterministic KV cache / prefix caching.
    """
    clean_system = static_system.strip()
    clean_user = dynamic_user.strip()

    if provider.lower() in ("anthropic", "claude") and enable_caching:
        return [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": clean_system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": clean_user},
        ]

    # Standard OpenAI / Groq / Ollama / Gemini format
    return [
        {"role": "system", "content": clean_system},
        {"role": "user", "content": clean_user},
    ]
