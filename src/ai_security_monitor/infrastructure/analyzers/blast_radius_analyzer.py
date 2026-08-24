# Blast Radius Engine - Feature 1: AI x CVE Correlation.

import re

from ai_security_monitor.domain.entities import AnalysisModel, Category, Entry
from ai_security_monitor.domain.value_objects import (
    AttackArchetype,
    WeaponizationLevel,
)
from ai_security_monitor.infrastructure.analyzers.base import (
    AnalysisResult,
    BaseAnalyzer,
    analyzer_registry,
)


class BlastRadiusAnalyzer(BaseAnalyzer):
    """
    Feature 1: Autonomous AI Correlation & Blast Radius Engine.
    Computes cross-correlation between security disclosures and AI stacks/frameworks.
    """

    @property
    def analyzer_type(self) -> str:
        return "blast_radius"

    @property
    def model(self) -> AnalysisModel:
        return AnalysisModel.BLAST_RADIUS

    # Comprehensive AI ecosystem mapping
    AI_ECOSYSTEM_MAP = {
        # Core ML Frameworks
        "PyTorch": [
            "pytorch", "torch", "torchvision", "torchaudio", "torchtext",
            "libtorch", "torchserve", "torchelastic", "torchx", "captum"
        ],
        "TensorFlow": [
            "tensorflow", "tf", "keras", "tflite", "tensorboard",
            "tensorflowjs", "tfx", "tf_agents", "tf_probability"
        ],
        "JAX": ["jax", "flax", "optax", "chex", "gymnax"],
        "ONNX": ["onnx", "onnxruntime", "onnxsim"],

        # Model Hubs & Ecosystems
        "HuggingFace": [
            "huggingface", "hf_", "transformers", "tokenizers", "datasets",
            "accelerate", "peft", "trl", "optimum", "text-generation-inference",
            "inference-endpoints", "hub", "safetensors"
        ],
        "ModelScope": ["modelscope", "model_scope"],

        # LLM Frameworks & Tools
        "LangChain": ["langchain", "langgraph", "langsmith", "langserve"],
        "LlamaIndex": ["llamaindex", "llama_index"],
        "Semantic Kernel": ["semantic-kernel", "semantic_kernel"],
        "AutoGen": ["autogen", "microsoft.autogen"],
        "CrewAI": ["crewai"],
        "Haystack": ["haystack", "deepset"],

        # Local LLM Runtime
        "Ollama": ["ollama"],
        "vLLM": ["vllm", "vllm-engine"],
        "llama.cpp": ["llama.cpp", "llamacpp", "gguf", "ggml"],
        "LM Studio": ["lm studio", "lmstudio"],
        "Text Generation Inference": ["tgi", "text-generation-inference"],

        # RAG & Vector DBs
        "Chroma": ["chromadb", "chroma"],
        "Pinecone": ["pinecone"],
        "Weaviate": ["weaviate"],
        "Qdrant": ["qdrant"],
        "Milvus": ["milvus", "zilliz"],
        "Redis": ["redis", "redisvl"],
        "Elasticsearch": ["elasticsearch", "opensearch"],

        # ML Platforms
        "MLflow": ["mlflow"],
        "Weights & Biases": ["wandb", "weights & biases", "weights and biases"],
        "ClearML": ["clearml", "clearml"],
        "Kubeflow": ["kubeflow"],
        "Ray": ["ray", "ray.io", "ray[train]", "ray[tune]", "ray[serve]"],
        "Flyte": ["flyte"],
        "Prefect": ["prefect"],

        # Training & Optimization
        "DeepSpeed": ["deepspeed"],
        "FSDP": ["fsdp", "fully sharded data parallel"],
        "LoRA/QLoRA": ["lora", "qlora", "peft"],
        "FlashAttention": ["flashattention", "flash attention"],
        "BitsAndBytes": ["bitsandbytes", "bnb"],

        # Hardware/Accelerators
        "CUDA": ["cuda", "cudnn", "nccl"],
        "ROCm": ["rocm", "hip"],
        "TPU": ["tpu", "google tpu", "cloud tpu"],
        "Neuron": ["neuron", "aws neuron", "inferentia", "trainium"],

        # Data & Feature Engineering
        "Polars": ["polars"],
        "DuckDB": ["duckdb"],
        "Dagster": ["dagster"],
        "Airflow": ["airflow"],
        "dbt": ["dbt"],

        # Security-Specific
        "Adversarial Robustness": ["adversarial", "robustness", "certified defense", "randomized smoothing"],
        "Model Watermarking": ["watermark", "model watermark", "fingerprinting"],
        "Differential Privacy": ["differential privacy", "dp-sgd", "opacus"],
        "Federated Learning": ["federated learning", "fl", "flower", "pytorch federated"],
    }

    # CVE-to-AI mapping for known vulnerability patterns
    CVE_AI_PATTERNS = {
        "pickle": {
            "ecosystems": ["PyTorch", "TensorFlow", "HuggingFace", "scikit-learn", "XGBoost", "LightGBM"],
            "description": "Pickle deserialization vulnerability in model artifacts",
            "archetype": AttackArchetype.SUPPLY_CHAIN,
        },
        "yaml": {
            "ecosystems": ["Kubernetes", "Airflow", "MLflow", "Kubeflow", "LangChain", "Hydra"],
            "description": "YAML deserialization leading to RCE",
            "archetype": AttackArchetype.RCE,
        },
        "path_traversal": {
            "ecosystems": ["General AI Stack", "Model Hubs", "Vector DBs"],
            "description": "Path traversal in model/data loading",
            "archetype": AttackArchetype.STANDARD_VULN,
        },
        "ssrf": {
            "ecosystems": ["RAG Systems", "LangChain", "LlamaIndex", "HuggingFace", "Ollama"],
            "description": "SSRF via malicious model URLs or webhooks",
            "archetype": AttackArchetype.STANDARD_VULN,
        },
        "prompt_injection": {
            "ecosystems": ["LangChain", "LlamaIndex", "Semantic Kernel", "AutoGen", "CrewAI", "OpenAI", "Anthropic"],
            "description": "Prompt injection in LLM applications",
            "archetype": AttackArchetype.PROMPT_INJECTION,
        },
        "rag_poisoning": {
            "ecosystems": ["RAG Systems", "Chroma", "Pinecone", "Weaviate", "Qdrant", "LangChain", "LlamaIndex"],
            "description": "RAG poisoning via malicious document injection",
            "archetype": AttackArchetype.RAG_POISONING,
        },
        "model_inversion": {
            "ecosystems": ["ML Platforms", "Model Hubs", "Inference APIs"],
            "description": "Model inversion/extraction attacks",
            "archetype": AttackArchetype.MODEL_INVERSION,
        },
        "data_poisoning": {
            "ecosystems": ["Training Pipelines", "MLflow", "ClearML", "Weights & Biases", "HuggingFace Datasets"],
            "description": "Training data poisoning",
            "archetype": AttackArchetype.DATA_POISONING,
        },
        "supply_chain": {
            "ecosystems": ["PyPI", "npm", "Docker Hub", "HuggingFace Hub", "ModelScope", "GitHub Actions"],
            "description": "Supply chain compromise in ML dependencies",
            "archetype": AttackArchetype.SUPPLY_CHAIN,
        },
    }

    def _detect_ai_ecosystems(self, text: str) -> list[str]:
        """Detect AI ecosystems mentioned in text."""
        text_lower = text.lower()
        detected = []

        for ecosystem, keywords in self.AI_ECOSYSTEM_MAP.items():
            for keyword in keywords:
                if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                    detected.append(ecosystem)
                    break

        return list(set(detected))

    def _correlate_cve_with_ai(self, text: str) -> tuple[list[str], str, str]:
        """Correlate CVE patterns with AI ecosystems."""
        text_lower = text.lower()
        ecosystems = set()
        archetype = AttackArchetype.STANDARD_VULN.value
        description = ""

        for pattern, info in self.CVE_AI_PATTERNS.items():
            if re.search(pattern, text_lower):
                ecosystems.update(info["ecosystems"])
                if not description:
                    description = info["description"]
                archetype = info["archetype"].value

        return list(ecosystems), archetype, description

    def _calculate_blast_radius(self, ecosystems: list[str], category: Category, text: str) -> int:
        """Calculate blast radius score based on ecosystem impact."""
        if not ecosystems:
            return 10

        # Base score from number of ecosystems
        score = min(50, len(ecosystems) * 8)

        # Critical ecosystems get higher scores
        critical_ecosystems = {
            "PyTorch", "TensorFlow", "HuggingFace", "LangChain", "Ollama", "vLLM",
            "HuggingFace Hub", "PyPI", "Docker Hub", "GitHub Actions"
        }

        critical_count = sum(1 for e in ecosystems if e in critical_ecosystems)
        score += critical_count * 10

        # Category multiplier
        if category == Category.VULNERABILITIES:
            score += 20
        elif category == Category.AI_TECH:
            score += 15

        # Widely deployed indicators
        if re.search(r"\b(widely|popular|millions|billions|enterprise|production|critical)\b", text.lower()):
            score += 15

        return min(100, max(1, score))

    def _detect_pre_cve_research(self, text: str, category: Category, ecosystems: list[str]) -> bool:
        """Detect pre-CVE academic research with AI implications."""
        if category != Category.AI_RESEARCH:
            return False

        text_lower = text.lower()

        # Strong academic indicators
        academic_strong = [
            r"\b(arxiv|preprint)\b",
            r"\b(we propose|we present|we introduce|novel attack|new vulnerability)\b",
            r"\b(proceeding|conference|symposium|workshop)\b",
        ]

        # AI-specific research indicators
        ai_research = [
            r"\b(jailbreak|prompt injection|rag poison|model inversion|data poison)\b",
            r"\b(adversarial|backdoor|trojan|watermark|extraction)\b",
            r"\b(fine.tuning|alignment|safety|guardrail)\b",
        ]

        academic_score = 0
        for pattern in academic_strong:
            if re.search(pattern, text_lower):
                academic_score += 2

        for pattern in ai_research:
            if re.search(pattern, text_lower):
                academic_score += 3

        # Boost if AI ecosystems mentioned
        if ecosystems:
            academic_score += len(ecosystems) * 2

        return academic_score >= 6

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry for blast radius."""
        full_text = f"{entry.title} {entry.summary} {entry.metadata.get('description', '')}"

        # Detect AI ecosystems
        ai_ecosystems = self._detect_ai_ecosystems(full_text)

        # Correlate with CVE patterns
        cve_ecosystems, archetype, cve_description = self._correlate_cve_with_ai(full_text)

        # Combine ecosystems
        all_ecosystems = list(set(ai_ecosystems + cve_ecosystems))

        # Calculate blast radius
        blast_radius = self._calculate_blast_radius(all_ecosystems, entry.category, full_text)

        # Pre-CVE detection
        is_pre_cve = self._detect_pre_cve_research(full_text, entry.category, all_ecosystems)

        # Weaponization (conservative for blast radius engine)
        weaponization = WeaponizationLevel.THEORETICAL.value
        if re.search(r"\b(poc|proof.of.concept|exploit|weaponized|active)\b", full_text.lower()):
            weaponization = WeaponizationLevel.POC_VERIFIED.value

        # Threat velocity based on blast radius and category
        velocity = min(100, blast_radius + 10)
        if entry.category == Category.VULNERABILITIES:
            velocity += 15

        # Severity
        severity = min(100, blast_radius + 5)

        # Generate descriptions
        attack_vector = cve_description or f"Blast radius analysis: {', '.join(all_ecosystems[:3])} potentially affected"
        if not cve_description:
            attack_vector = f"Cross-correlation analysis: Security disclosure impacts {', '.join(all_ecosystems[:3]) or 'General AI Stack'}"

        risk_assessment = f"Blast radius impact: {len(all_ecosystems)} AI ecosystems potentially affected. " \
                         f"Immediate assessment required for: {', '.join(all_ecosystems[:5])}"

        mitigation = (
            "1. Inventory affected AI/ML dependencies in your environment\n"
            "2. Apply vendor patches for identified frameworks\n"
            "3. Monitor model artifact integrity (SBOM, signatures)\n"
            "4. Implement runtime protection for LLM applications"
        )

        return AnalysisResult(
            entry_id=entry.id,
            attack_vector=attack_vector,
            risk_assessment=risk_assessment,
            mitigation=mitigation,
            threat_velocity=velocity,
            severity_index=severity,
            blast_radius_score=blast_radius,
            affected_ecosystem=all_ecosystems,
            is_pre_cve_warning=is_pre_cve,
            attack_archetype=archetype,
            weaponization_potential=weaponization,
            model=AnalysisModel.BLAST_RADIUS,
            confidence=0.8,
        )


analyzer_registry.register("blast_radius", BlastRadiusAnalyzer)
