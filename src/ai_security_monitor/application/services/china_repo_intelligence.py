"""
China Open-Source Repository Intelligence & Epistemic Profiler.

Extracts researcher-grade architectural facts from Chinese & bilingual open-source
AI projects: archetype classification (Foundations, Inference Runtimes, Agents, RAG,
Multimodal), lab authority, parameters, context windows, VRAM hardware requirements,
and serving integration.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ChinaRepoArchetype(str, Enum):
    """Categorical classification of open-source AI repositories."""

    FOUNDATION_MODEL = "foundation_model"
    INFERENCE_RUNTIME = "inference_runtime"
    AGENTIC_SYSTEM = "agentic_system"
    RAG_KNOWLEDGE_BASE = "rag_knowledge_base"
    MULTIMODAL_VOICE = "multimodal_voice"
    EVAL_AND_BENCHMARK = "eval_and_benchmark"
    DEV_TOOL = "dev_tool"
    EMBODIED_AI_ROBOTICS = "embodied_ai_robotics"
    COMPUTER_VISION_EDGE = "computer_vision_edge"
    SEMICONDUCTOR_RISCV = "semiconductor_riscv"
    OFFENSIVE_SECURITY_VULN = "offensive_security_vuln"


ARCHETYPE_LABELS = {
    ChinaRepoArchetype.FOUNDATION_MODEL: "Foundation Model (基座大模型)",
    ChinaRepoArchetype.INFERENCE_RUNTIME: "Inference Runtime (推理加速与部署)",
    ChinaRepoArchetype.AGENTIC_SYSTEM: "Agentic System (智能体与工作流)",
    ChinaRepoArchetype.RAG_KNOWLEDGE_BASE: "RAG & Knowledge Base (检索增强知识库)",
    ChinaRepoArchetype.MULTIMODAL_VOICE: "Multimodal & Audio (多模态与语音)",
    ChinaRepoArchetype.EVAL_AND_BENCHMARK: "Evaluation & Benchmarks (评测基准)",
    ChinaRepoArchetype.DEV_TOOL: "Developer Tooling (开发工具与生态)",
    ChinaRepoArchetype.EMBODIED_AI_ROBOTICS: "Embodied AI & Robotics (具身智能与机器人)",
    ChinaRepoArchetype.COMPUTER_VISION_EDGE: "Computer Vision & Edge AI (计算机视觉与边缘AI)",
    ChinaRepoArchetype.SEMICONDUCTOR_RISCV: "Semiconductor & RISC-V Chips (半导体与RISC-V芯片)",
    ChinaRepoArchetype.OFFENSIVE_SECURITY_VULN: "Offensive Security & Vulnerabilities (漏洞分析与实战攻防)",
}

# Known Chinese AI Laboratories & Open-Source Organizations
LAB_ORGANIZATION_MAP: dict[str, tuple[str, bool]] = {
    "deepseek": ("DeepSeek AI (深度求索)", True),
    "deepseek-ai": ("DeepSeek AI (深度求索)", True),
    "qwen": ("Alibaba Qwen (通义千问)", True),
    "qwenlm": ("Alibaba Qwen (通义千问)", True),
    "internlm": ("Shanghai AI Lab (上海人工智能实验室)", True),
    "opendatalab": ("Shanghai AI Lab (上海人工智能实验室)", True),
    "opengvlab": ("Shanghai AI Lab (上海人工智能实验室 / OpenGVLab)", True),
    "shlab": ("Shanghai AI Lab (上海人工智能实验室)", True),
    "thudm": ("Zhipu AI / Tsinghua KEG (智谱AI / 清华大学)", True),
    "zhipu": ("Zhipu AI (智谱AI)", True),
    "moonshot": ("Moonshot AI (月之暗面 Kimi)", True),
    "moonshotai": ("Moonshot AI (月之暗面 Kimi)", True),
    "baichuan": ("Baichuan AI (百川智能)", True),
    "01-ai": ("01.AI (零一万物 Yi)", True),
    "infiniflow": ("InfiniFlow (RAGFlow)", True),
    "labring": ("LabRing (FastGPT)", True),
    "langgenius": ("LangGenius (Dify)", True),
    "datawhale": ("Datawhale Open Source Community", True),
    "datawhalechina": ("Datawhale Open Source Community", True),
    "funaudiollm": ("Alibaba Speech Lab (FunAudioLLM)", True),
    "fishaudio": ("Fish Audio", False),
    "tencent": ("Tencent (腾讯优图 / ARC)", True),
    "tencentarc": ("Tencent ARC (腾讯优图)", True),
    "youtu": ("Tencent YouTu Lab (腾讯优图实验室)", True),
    "xuanwu": ("Tencent Xuanwu Lab (腾讯安全玄武实验室)", True),
    "bytedance": ("ByteDance Seed / Tech (字节跳动)", True),
    "bytetech": ("ByteDance Tech (字节跳动技术团队)", True),
    "paddlepaddle": ("Baidu PaddlePaddle (百度飞桨)", True),
    "baidu": ("Baidu Research & Apollo (百度研究院)", True),
    "apollo": ("Baidu Apollo (百度Apollo自动驾驶)", True),
    "pku-alignment": ("Peking University (北京大学对齐实验室)", True),
    "fudan": ("Fudan University CodeWisdom (复旦大学)", True),
    "openi": ("Peng Cheng Laboratory (鹏城实验室 / OpenI启智)", True),
    "pengcheng": ("Peng Cheng Laboratory (鹏城实验室)", True),
    "mindspore": ("Huawei MindSpore (华为昇思开源社区)", True),
    "ascend": ("Huawei Ascend (华为昇腾芯片算力)", True),
    "huawei": ("Huawei AI Research (华为中央研究院)", True),
    "meituan": ("Meituan Tech Team (美团技术团队)", True),
    "damo": ("Alibaba DAMO Academy (阿里巴巴达摩院)", True),
    "megvii": ("Megvii Research (旷视研究院)", True),
    "megvii-basedetection": ("Megvii Research (旷视研究院)", True),
    "openmmlab": ("SenseTime OpenMMLab (商汤科技)", True),
    "open-mmlab": ("SenseTime OpenMMLab (商汤科技)", True),
    "sensetime": ("SenseTime (商汤科技研究院)", True),
    "dji": ("DJI Developer (大疆创新机器人研发)", True),
    "dji-sdk": ("DJI Developer (大疆创新机器人研发)", True),
    "unitree": ("Unitree Robotics (宇树科技具身智能机器人)", True),
    "unitreerobotics": ("Unitree Robotics (宇树科技具身智能机器人)", True),
    "agibot": ("Agibot (智元机器人具身世界模型)", True),
    "casia": ("CASIA (中科院自动化所紫东太初)", True),
    "xiangshan": ("ICT CAS (中科院计算所香山RISC-V处理器)", True),
    "openxiangshan": ("ICT CAS (中科院计算所香山RISC-V处理器)", True),
    "tsinghua-air": ("Tsinghua AIR (清华大学智能产业研究院)", True),
    "baai": ("BAAI (北京智源人工智能研究院 / FlagOpen)", True),
    "flagopen": ("BAAI (北京智源人工智能研究院 / FlagOpen)", True),
    "flagembedding": ("BAAI (北京智源人工智能研究院 / FlagOpen)", True),
    "seebug": ("Knownsec Seebug (知道创宇漏洞实验室)", True),
    "knownsec": ("Knownsec (知道创宇安全团队)", True),
    "qianxin": ("QiAnXin (奇安信攻防社区 / XLab)", True),
    "butian": ("QiAnXin Butian (奇安信补天漏洞响应平台)", True),
    "360cert": ("360 CERT (360网络安全应急响应中心)", True),
    "netlab": ("360 Netlab (360网络安全研究实验室)", True),
}


@dataclass
class RepoIntelligenceProfile:
    """Researcher-grade structured profile of an open-source repository."""

    archetype: str
    archetype_label: str
    lab_name: str | None = None
    is_official_lab: bool = False
    parameter_scale: str | None = None
    context_window: str | None = None
    vram_hardware: str | None = None
    quantization_formats: list[str] = field(default_factory=list)
    serving_frameworks: list[str] = field(default_factory=list)
    license_type: str | None = None
    researcher_quality_score: float = 0.50
    key_highlights: list[str] = field(default_factory=list)
    star_velocity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChinaRepoIntelligenceExtractor:
    """Epistemic technical profiler for Chinese AI & developer repositories."""

    # 1. Regex patterns for parameter counts
    PARAM_REGEX = re.compile(
        r"(?<![a-zA-Z0-9])(\d+(?:\.\d+)?(?:B|M|K)(?:-(?:MoE|A\d+B))?|\bMoE\s*\d+B|\b\d+x\d+B)(?![a-zA-Z0-9])",
        re.IGNORECASE,
    )

    # 2. Context window patterns
    CONTEXT_REGEX = re.compile(
        r"(?<![a-zA-Z0-9])(\d+K|\d+M)\s*(?:context|tokens?|上下文|窗口|token)",
        re.IGNORECASE,
    )

    # 3. Hardware / VRAM requirements
    VRAM_REGEX = re.compile(
        r"(\d+\s*GB\s*(?:VRAM|显存|GPU))|(RTX\s*(?:4090|3090|4080))|"
        r"([1-8]x\s*(?:A100|H100|H800|H20))|(Apple\s*Silicon|MPS)|(CPU\s*(?:only|推理|部署))",
        re.IGNORECASE,
    )

    # Acronym patterns requiring word boundaries to avoid substring false positives
    SEC_ACRONYMS = re.compile(r"\b(poc|exp|rce|cve|0day|zero-day)\b", re.IGNORECASE)
    CV_ACRONYMS = re.compile(r"\b(cv|ocr)\b", re.IGNORECASE)
    TTS_ACRONYMS = re.compile(r"\b(tts)\b", re.IGNORECASE)

    # 4. Quantization formats
    QUANT_PATTERNS = {
        "AWQ": re.compile(r"\bAWQ\b", re.IGNORECASE),
        "GGUF": re.compile(r"\bGGUF\b", re.IGNORECASE),
        "GPTQ": re.compile(r"\bGPTQ\b", re.IGNORECASE),
        "FP8": re.compile(r"\bFP8\b", re.IGNORECASE),
        "BF16": re.compile(r"\bBF16|bfloat16\b", re.IGNORECASE),
        "INT4": re.compile(r"\bINT4|4-bit|4bit\b", re.IGNORECASE),
        "INT8": re.compile(r"\bINT8|8-bit|8bit\b", re.IGNORECASE),
        "EXL2": re.compile(r"\bEXL2\b", re.IGNORECASE),
    }

    # 5. Serving and runtime compatibility
    SERVING_PATTERNS = {
        "vLLM": re.compile(r"\bvllm\b", re.IGNORECASE),
        "LMDeploy": re.compile(r"\blmdeploy\b", re.IGNORECASE),
        "SGLang": re.compile(r"\bsglang\b", re.IGNORECASE),
        "Ollama": re.compile(r"\bollama\b", re.IGNORECASE),
        "llama.cpp": re.compile(r"\bllama\.cpp|llamacpp\b", re.IGNORECASE),
        "TensorRT-LLM": re.compile(r"\btensorrt-llm|trt-llm\b", re.IGNORECASE),
        "Triton": re.compile(r"\btriton\b", re.IGNORECASE),
        "Transformers": re.compile(r"\btransformers|huggingface\b", re.IGNORECASE),
    }

    # 6. Open source licenses
    LICENSE_PATTERNS = [
        ("Apache-2.0", re.compile(r"Apache[- ]2(?:\.0)?", re.IGNORECASE)),
        ("MIT", re.compile(r"\bMIT(?:\s+License)?\b", re.IGNORECASE)),
        ("GPL-3.0", re.compile(r"GPL[- ]?3(?:\.0)?", re.IGNORECASE)),
        ("DeepSeek License", re.compile(r"DeepSeek[- ]License", re.IGNORECASE)),
        (
            "Tongyi Qianwen License",
            re.compile(r"Tongyi|Qwen[- ]License", re.IGNORECASE),
        ),
        ("OpenRAIL", re.compile(r"OpenRAIL", re.IGNORECASE)),
    ]

    def extract_profile(
        self,
        title: str,
        description: str = "",
        url: str = "",
        tags: list[str] | None = None,
        stars: int | str = 0,
    ) -> RepoIntelligenceProfile:
        """Deterministically extract a comprehensive researcher profile from repository text."""
        combined = f"{title} {description} {' '.join(tags or [])}".strip()
        lower_combined = combined.lower()

        # A. Determine Laboratory / Org
        lab_name: str | None = None
        is_official = False
        repo_owner = ""
        if "github.com/" in url:
            parts = url.split("github.com/")[-1].strip("/").split("/")
            if len(parts) >= 1:
                repo_owner = parts[0].lower()

        for key, (name, official) in LAB_ORGANIZATION_MAP.items():
            if (
                key == repo_owner
                or f"{key}/" in lower_combined
                or f"@{key}" in lower_combined
            ):
                lab_name = name
                is_official = official
                break
            if key in lower_combined:
                lab_name = name
                is_official = official

        # B. Archetype Classification
        archetype = self._classify_archetype(lower_combined)
        archetype_label = ARCHETYPE_LABELS[archetype]

        # C. Extract Parameter Scale
        param_match = self.PARAM_REGEX.search(combined)
        parameter_scale = param_match.group(1).upper() if param_match else None

        # D. Extract Context Window
        ctx_match = self.CONTEXT_REGEX.search(combined)
        context_window = ctx_match.group(1).upper() if ctx_match else None

        # E. Extract Hardware / VRAM
        vram_match = self.VRAM_REGEX.search(combined)
        vram_hardware = vram_match.group(0).strip() if vram_match else None

        # F. Quantization Formats
        quants = [q for q, p in self.QUANT_PATTERNS.items() if p.search(combined)]

        # G. Serving Frameworks
        servings = [s for s, p in self.SERVING_PATTERNS.items() if p.search(combined)]

        # H. License Detection
        detected_license: str | None = None
        for lic_name, lic_pat in self.LICENSE_PATTERNS:
            if lic_pat.search(combined):
                detected_license = lic_name
                break

        # I. Calculate Quality Score
        score = 0.50
        highlights: list[str] = []

        if is_official:
            score += 0.25
            highlights.append(f"Official release from {lab_name}")
        elif lab_name:
            score += 0.15
            highlights.append(f"Affiliated with {lab_name}")

        if parameter_scale:
            score += 0.10
            highlights.append(f"Parameter scale: {parameter_scale}")

        if context_window:
            score += 0.05
            highlights.append(f"Context length: {context_window}")

        if servings:
            score += 0.05
            highlights.append(f"Serving: {', '.join(servings[:3])}")

        if detected_license:
            score += 0.05
            highlights.append(f"License: {detected_license}")

        # Check for link-farm / curated list
        if (
            "awesome" in lower_combined
            or "收藏" in lower_combined
            or "大全" in lower_combined
        ):
            if archetype != ChinaRepoArchetype.EVAL_AND_BENCHMARK:
                score -= 0.15

        # Normalize score between 0.10 and 1.00
        quality_score = max(0.10, min(1.00, round(score, 2)))

        return RepoIntelligenceProfile(
            archetype=archetype.value,
            archetype_label=archetype_label,
            lab_name=lab_name,
            is_official_lab=is_official,
            parameter_scale=parameter_scale,
            context_window=context_window,
            vram_hardware=vram_hardware,
            quantization_formats=quants,
            serving_frameworks=servings,
            license_type=detected_license,
            researcher_quality_score=quality_score,
            key_highlights=highlights,
        )

    def _classify_archetype(self, text: str) -> ChinaRepoArchetype:
        """Classify repository archetype by semantic signals."""
        # Offensive Security & Vulnerability Analysis
        if self.SEC_ACRONYMS.search(text) or any(
            w in text
            for w in (
                "vulnerability",
                "vuln",
                "exploit",
                "cnvd",
                "cnnvd",
                "reverse engineering",
                "binary exploitation",
                "kernel exploit",
                "seebug",
                "freebuf",
                "anquanke",
                "kanxue",
                "tttang",
                "secpulse",
                "4hou",
                "xuanwu",
                "butian",
                "xianzhi",
                "oscs",
                "漏洞",
                "利用代码",
                "利用链",
                "提权",
                "攻防",
                "逆向工程",
                "免杀",
                "供应链投毒",
                "越权",
                "任意代码执行",
            )
        ):
            return ChinaRepoArchetype.OFFENSIVE_SECURITY_VULN

        # Embodied AI & Robotics
        if any(
            w in text
            for w in (
                "robot",
                "robotics",
                "slam",
                "quadruped",
                "humanoid",
                "locomotion",
                "flight control",
                "point cloud",
                "lidar",
                "unitree",
                "agibot",
                "dji",
                "shenlan",
                "具身智能",
                "机器人",
                "人形机器人",
                "四足机器人",
                "四足",
                "激光雷达",
                "点云",
                "飞控",
                "飞行控制",
                "运动控制",
                "视觉里程计",
                "无人机",
            )
        ):
            return ChinaRepoArchetype.EMBODIED_AI_ROBOTICS

        # Semiconductor & RISC-V Chips
        if any(
            w in text
            for w in (
                "risc-v",
                "riscv",
                "xiangshan",
                "fpga",
                "chip",
                "chips",
                "semiconductor",
                "eda",
                "npu",
                "ascend",
                "icbank",
                "elecfans",
                "半导体",
                "芯片",
                "香山",
                "昇腾",
                "开源芯片",
                "处理器核",
                "处理器芯片",
                "流片",
                "光刻",
            )
        ):
            return ChinaRepoArchetype.SEMICONDUCTOR_RISCV

        # Computer Vision & Edge AI
        if self.CV_ACRONYMS.search(text) or any(
            w in text
            for w in (
                "computer vision",
                "openmmlab",
                "mmdetection",
                "youtu",
                "megvii",
                "yolox",
                "cvmart",
                "extreme mart",
                "目标检测",
                "图像分割",
                "边缘计算",
                "边缘ai",
                "文字识别",
            )
        ):
            return ChinaRepoArchetype.COMPUTER_VISION_EDGE

        # Multimodal & Voice
        if self.TTS_ACRONYMS.search(text) or any(
            w in text
            for w in (
                "speech",
                "voice",
                "audio",
                "cosyvoice",
                "chattts",
                "fish-speech",
                "video",
                "cogvideo",
                "hunyuanvideo",
                "mineru",
                "pdfmathtranslate",
                "vision",
                "qwen-vl",
                "多模态",
                "语音",
                "视觉",
            )
        ):
            return ChinaRepoArchetype.MULTIMODAL_VOICE

        # Inference Runtime & Deployment
        if any(
            w in text
            for w in (
                "inference",
                "runtime",
                "serving",
                "lmdeploy",
                "vllm",
                "sglang",
                "llamacpp",
                "llama.cpp",
                "quantization",
                "量化",
                "推理框架",
                "加速",
                "吞吐量",
                "gguf",
                "tensorrt",
            )
        ):
            return ChinaRepoArchetype.INFERENCE_RUNTIME

        # RAG & Knowledge Base
        if any(
            w in text
            for w in (
                "rag",
                "ragflow",
                "retrieval",
                "knowledge base",
                "知识库",
                "检索增强",
                "chatchat",
                "huixiangdou",
                "fastgpt",
                "maxkb",
                "db-gpt",
                "向量库",
            )
        ):
            return ChinaRepoArchetype.RAG_KNOWLEDGE_BASE

        # Agent Systems & Workflows
        if any(
            w in text
            for w in (
                "agent",
                "agents",
                "agentic",
                "智能体",
                "mindsearch",
                "appagent",
                "dify",
                "qwencode",
                "agentscope",
                "metagpt",
                "chatdev",
                "workflow",
                "工作流",
                "编排",
            )
        ):
            return ChinaRepoArchetype.AGENTIC_SYSTEM

        # Evaluation & Benchmark
        if any(
            w in text
            for w in (
                "benchmark",
                "eval",
                "evaluation",
                "评测",
                "基准",
                "c-eval",
                "cmmlu",
                "alignbench",
                "self-llm",
                "dataset",
                "数据集",
            )
        ):
            return ChinaRepoArchetype.EVAL_AND_BENCHMARK

        # Foundation Model
        if any(
            w in text
            for w in (
                "foundation model",
                "deepseek",
                "qwen",
                "internlm",
                "glm-4",
                "kimi",
                "baichuan",
                "minicpm",
                "基座模型",
                "大语言模型",
                "大模型",
                "weights",
                "开源权重",
            )
        ):
            return ChinaRepoArchetype.FOUNDATION_MODEL

        return ChinaRepoArchetype.DEV_TOOL


# Global singleton instance
china_repo_intelligence = ChinaRepoIntelligenceExtractor()
