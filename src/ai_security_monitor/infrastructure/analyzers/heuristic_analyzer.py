# Heuristic analyzer - fast, zero-cost, no LLM required.

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


class HeuristicAnalyzer(BaseAnalyzer):
    """Fast heuristic analyzer using keyword matching and rules."""

    @property
    def analyzer_type(self) -> str:
        return "heuristic"

    @property
    def model(self) -> AnalysisModel:
        return AnalysisModel.HEURISTIC

    # Keyword patterns for threat detection
    THREAT_KEYWORDS = {
        "critical": [
            r"\b(rce|remote code execution)\b",
            r"\b(zero.day|0.day|0day)\b",
            r"\b(active.exploit|exploited.in.wild)\b",
            r"\b(ransomware)\b",
            r"\b(supply.chain)\b",
            r"\b(critical)\b",
            r"(零日|0day|在野利用|远程代码执行|勒索软件|严重漏洞|高危漏洞)",
        ],
        "high": [
            r"\b(privilege.escalation)\b",
            r"\b(sql.injection|sqli)\b",
            r"\b(command.injection)\b",
            r"\b(path.traversal)\b",
            r"\b(xss|cross.site.scripting)\b",
            r"\b(authentication.bypass)\b",
            r"\b(rce|remote.code)\b",
            r"\b(buffer.overflow)\b",
            r"\b(deserialization)\b",
            r"\b(jailbreak)\b",
            r"\b(prompt.injection)\b",
            r"\b(model.inversion)\b",
            r"\b(data.poisoning)\b",
            r"(提权|权限提升|命令注入|越狱|提示注入|后门|反序列化|数据投毒|模型逆向|安全通告)",
        ],
        "medium": [
            r"\b(xxe|xml.external.entity)\b",
            r"\b(ssrf|server.side.request.forgery)\b",
            r"\b(csrf)\b",
            r"\b(idor|insecure.direct.object)\b",
            r"\b(information.disclosure)\b",
            r"\b(denial.of.service|dos)\b",
            r"\b(bypass)\b",
            r"\b(traversal)\b",
            r"(信息泄露|绕过|未授权访问|弱口令|跨站脚本|拒绝服务|安全补丁)",
        ],
        "low": [
            r"\b(xss|reflected)\b",
            r"\b(open.redirect)\b",
            r"\b(missing.auth)\b",
            r"\b(weak.crypto)\b",
            r"(重定向|低危|配置缺陷)",
        ],
    }

    AI_ECOSYSTEM_PATTERNS = {
        "DeepSeek": [r"\bdeepseek\b", r"\br1\b", r"\bv3\b", r"深度求索"],
        "Alibaba Qwen": [r"\bqwen\b", r"\btongyi\b", r"通义千问"],
        "Zhipu GLM": [r"\bglm\b", r"\bchatglm\b", r"\bzhipu\b", r"智谱"],
        "Baidu ERNIE / Paddle": [r"\bpaddle\b", r"\bernie\b", r"文心一言", r"飞桨"],
        "Shanghai AI Lab (InternLM)": [r"\binternlm\b", r"书生·浦语", r"\bopenmmlab\b"],
        "Moonshot Kimi": [r"\bmoonshot\b", r"\bkimi\b"],
        "Huawei MindSpore / Ascend": [r"\bmindspore\b", r"\bascend\b", r"昇腾"],
        "PyTorch": [
            r"\bpytorch\b",
            r"\btorch\b",
            r"\btorchvision\b",
            r"\btorchaudio\b",
        ],
        "TensorFlow": [r"\btensorflow\b", r"\bkeras\b", r"\btflite\b"],
        "HuggingFace": [
            r"\bhuggingface\b",
            r"\btransformers\b",
            r"\btokenizers\b",
            r"\bpeft\b",
        ],
        "LangChain": [r"\blangchain\b", r"\blanggraph\b"],
        "LlamaIndex": [r"\bllamaindex\b"],
        "Ollama": [r"\bollama\b"],
        "vLLM": [r"\bvllm\b"],
        "ONNX": [r"\bonnx\b"],
        "CUDA": [r"\bcuda\b", r"\bcudnn\b"],
        "JAX": [r"\bjax\b", r"\bflax\b"],
        "SGLang": [r"\bsglang\b"],
        "llama.cpp": [r"\bllama\.cpp\b", r"\bllama-cpp\b"],
        "Mistral AI": [r"\bmistral\b", r"\bpixtral\b"],
        "Anthropic Claude": [r"\bclaude\b", r"\bsonnet\b", r"\bhaiku\b", r"\bopus\b"],
        "xAI Grok": [r"\bgrok\b"],
        "OpenAI o-series": [r"\bo1\b", r"\bo3\b", r"\bgpt-4\b", r"\bgpt-5\b"],
        "Google Gemini": [r"\bgemini\b", r"\bgemma\b"],
        "Meta Llama": [r"\bllama\b", r"\bllama3\b"],
        "Stability AI": [r"\bstable diffusion\b", r"\bsdxl\b", r"\bflux\b"],
        "FlashAttention": [r"\bflashattention\b", r"\bflash-attn\b"],
        "Apple MLX": [r"\bmlx\b"],
        "NVIDIA TensorRT": [r"\btensorrt\b", r"\btensorrt-llm\b", r"\bnim\b"],
        "AMD ROCm": [r"\brocm\b", r"\bmi300\b"],
        "CrewAI": [r"\bcrewai\b"],
        "AutoGen": [r"\bautogen\b"],
        "unsloth": [r"\bunsloth\b"],
        "Axolotl": [r"\baxolotl\b"],
        "ChromaDB": [r"\bchroma\b", r"\bchromadb\b"],
        "Qdrant": [r"\bqdrant\b"],
        "Weaviate": [r"\bweaviate\b"],
        "LiteLLM": [r"\blitellm\b"],
        "ComfyUI": [r"\bcomfyui\b"],
        "BitNet 1-Bit LLM": [
            r"\bbitnet\b",
            r"\b1-bit\b",
            r"\bternary\b",
            r"\bbitnet-b1\.58\b",
        ],
        "Model Context Protocol": [
            r"\bmcp\b",
            r"\bmodel context protocol\b",
            r"\bmodelcontextprotocol\b",
        ],
        "Autonomous Coding Agents": [
            r"\bclaude code\b",
            r"\bdevin\b",
            r"\bswe-agent\b",
            r"\baider\b",
            r"\bcursor\b",
        ],
        "Video & World Models": [
            r"\bwan\s*2\.1\b",
            r"\bwan-2\.1\b",
            r"\bhunyuanvideo\b",
            r"\bhunyuan\b",
            r"\bsora\b",
            r"\bworld model\b",
        ],
        "Compact Frontier Models": [r"\bminicpm\b", r"\bsmollm\b", r"\bk1\.5\b"],
    }

    ATTACK_ARCHETYPE_PATTERNS = {
        AttackArchetype.JAILBREAK: [
            r"\bjailbreak\b",
            r"\bbypass.*guard\b",
            r"\bunaligned\b",
            r"越狱",
            r"绕过安全对齐",
        ],
        AttackArchetype.RAG_POISONING: [
            r"\brag.*poison\b",
            r"\bpoison.*retrieval\b",
            r"\bcorrupt.*knowledge\b",
            r"检索污染",
            r"知识库投毒",
        ],
        AttackArchetype.MODEL_INVERSION: [
            r"\bmodel.inversion\b",
            r"\binvert.*model\b",
            r"\bextract.*weights\b",
            r"模型逆向",
            r"权重提取",
        ],
        AttackArchetype.PROMPT_INJECTION: [
            r"\bprompt.injection\b",
            r"\binject.*prompt\b",
            r"\bsystem.prompt\b",
            r"提示注入",
            r"提示词注入",
        ],
        AttackArchetype.DATA_POISONING: [
            r"\bdata.poison\b",
            r"\bpoison.*training\b",
            r"\bbackdoor.*model\b",
            r"数据投毒",
            r"模型后门",
        ],
        AttackArchetype.MODEL_EXTRACTION: [
            r"\bmodel.extraction\b",
            r"\bsteal.*model\b",
            r"\bextract.*architecture\b",
            r"模型窃取",
        ],
        AttackArchetype.SUPPLY_CHAIN: [
            r"\bsupply.chain\b",
            r"\bdependency.confusion\b",
            r"\btyposquat\b",
            r"供应链攻击",
            r"依赖混淆",
        ],
        AttackArchetype.RCE: [
            r"\brce\b",
            r"\bremote.code.execution\b",
            r"\barbitrary.code\b",
            r"远程代码执行",
            r"任意代码执行",
        ],
        AttackArchetype.PRIVILEGE_ESCALATION: [
            r"\bprivilege.escalation\b",
            r"\bescalate.*privilege\b",
            r"提权",
            r"权限提升",
        ],
    }

    def _calculate_empirical_ai_newsworthiness(
        self, text: str, category: Category, metadata: dict | None = None
    ) -> tuple[int, int]:
        """
        Calculate empirical AI Newsworthiness and Technical Depth.
        Strips legacy CVE/vulnerability weights in favor of:
        1. Engagement & community momentum (stars, forks, HN points)
        2. Repo & implementation velocity (Triton, kernels, vLLM/SGLang runtimes)
        3. Citation indicators, empirical benchmarks (SWE-bench, Chatbot Arena, Math-500)
        4. Foundation model family & open weights scale (DeepSeek, Qwen, Mistral, Claude, Llama)
        5. Epistemic slop & prompt-wrapper penalization
        """
        text_lower = text.lower()
        meta = metadata or {}

        # 1. Base Score calibrated by category
        if category == Category.AI_MODELS:
            base_vel = 42
            base_impact = 45
        elif category == Category.AI_RESEARCH:
            base_vel = 38
            base_impact = 44
        elif category == Category.GITHUB_TRENDING:
            base_vel = 36
            base_impact = 40
        elif category in (Category.CYBER_TOOLS, Category.AI_TECH):
            base_vel = 32
            base_impact = 38
        else:
            base_vel = 25
            base_impact = 30

        vel_score = base_vel
        impact_score = base_impact

        # 2. Frontier Model & Open Weights Signals (+15 to +30)
        tier1_labs = (
            "deepseek",
            "qwen",
            "mistral",
            "anthropic",
            "claude",
            "openai",
            "google deepmind",
            "meta ai",
            "llama-3",
            "llama3",
            "gemini",
            "grok",
            "glm-4",
            "internlm",
            "kimi",
            "moonshot",
            "zhipu",
            "cohere",
        )
        if any(k in text_lower for k in tier1_labs):
            vel_score += 22
            impact_score += 18

        if any(
            k in text_lower
            for k in (
                "open weights",
                "open-weights",
                "weights released",
                "safetensors",
                "checkpoints",
                "checkpoint",
            )
        ) or (
            "weights" in text_lower
            and any(
                w in text_lower for w in ("open", "released", "public", "available")
            )
        ):
            vel_score += 14
            impact_score += 12

        # 3. Reasoning & Architecture Breakthroughs (+14 to +25)
        if any(
            k in text_lower
            for k in (
                "reasoning",
                "chain of thought",
                "cot",
                "test-time compute",
                "extended thinking",
                "inference-time scaling",
                "prm",
                "mcts",
                "process reward model",
                "r1",
                "o1",
                "o3",
                "deepseek-r1",
                "reinforcement learning",
                "rlhf",
                "grpo",
                "dpo",
            )
        ):
            vel_score += 20
            impact_score += 22

        if any(
            k in text_lower
            for k in (
                "mixture-of-experts",
                "moe",
                "sparse attention",
                "multi-head latent attention",
                "mla",
                "state space model",
                "mamba",
                "speculative decoding",
                "bitnet",
                "1-bit",
            )
        ):
            vel_score += 16
            impact_score += 18

        # 4. Repo Velocity & Infrastructure Runtime Innovations (+12 to +20)
        if any(
            k in text_lower
            for k in (
                "vllm",
                "sglang",
                "ollama",
                "llama.cpp",
                "tensorrt",
                "flashinfer",
                "triton kernel",
                "cuda kernel",
                "kernel fusion",
                "chunked prefill",
                "radixattention",
                "unsloth",
                "axolotl",
                "mlx",
                "torch.compile",
            )
        ):
            vel_score += 16
            impact_score += 16

        # 5. Citation & Empirical Benchmark Rigor (+10 to +20)
        if any(
            k in text_lower
            for k in (
                "swe-bench",
                "livecodebench",
                "math-500",
                "gpqa",
                "chatbot arena",
                "lmsys",
                "arena-hard",
                "humaneval",
                "mmlu-pro",
                "eval harness",
                "benchmark",
                "benchmarks",
            )
        ):
            vel_score += 15
            impact_score += 18

        if any(
            k in text_lower
            for k in (
                "arxiv:",
                "doi:",
                "preprint",
                "ablation study",
                "empirical evaluation",
                "scaling law",
                "pareto frontier",
                "state-of-the-art",
                "sota",
                "outperform",
            )
        ):
            vel_score += 12
            impact_score += 14

        # 6. Engagement Metrics from Metadata (+5 to +20)
        stars = meta.get("stars") or meta.get("stargazers_count") or 0
        if isinstance(stars, (int, float)):
            if stars >= 5000:
                vel_score += 18
            elif stars >= 1000:
                vel_score += 12
            elif stars >= 200:
                vel_score += 6

        score_val = meta.get("score") or meta.get("points") or 0
        comments_val = meta.get("comments") or meta.get("num_comments") or 0
        if isinstance(score_val, (int, float)):
            if score_val >= 300 or (
                isinstance(comments_val, (int, float)) and comments_val >= 100
            ):
                vel_score += 16
            elif score_val >= 100 or (
                isinstance(comments_val, (int, float)) and comments_val >= 40
            ):
                vel_score += 10

        if any(
            k in text_lower
            for k in (
                "viral",
                "trending repo",
                "10x faster",
                "2x speedup",
                "breakout",
                "record throughput",
                "day-0",
            )
        ):
            vel_score += 10

        # 7. Epistemic Slop & Wrapper Penalty (-35)
        slop_indicators = (
            "awesome-",
            "1000+ prompt",
            "collection of prompt",
            "curated list of",
            "chatgpt-wrapper",
            "wrapper for chatgpt",
            "wrapper for claude",
            "simple ui for openai",
            "telegram bot for openai",
            "cheatsheet",
            "cheat sheet",
            "prompt engineering cheatsheet",
            "memecoin",
            "airdrop",
            "solana bot",
            "pump.fun",
            "trading bot",
            "make money with ai",
            "earn $",
            "10x your productivity",
        )
        if any(sp in text_lower for sp in slop_indicators):
            vel_score -= 35
            impact_score -= 30

        # 8. Granular Distribution Smoothing (eliminates clumping at round numbers)
        variance = (len(text) % 7) - 3
        vel_score += variance
        impact_score += ((len(text) // 7) % 5) - 2

        final_vel = min(99, max(10, vel_score))
        final_impact = min(98, max(15, impact_score))

        return final_vel, final_impact

    def _calculate_threat_velocity(self, text: str) -> int:
        """Calculate empirical newsworthiness or fallback threat velocity (1-100)."""
        text_lower = text.lower()
        if not re.search(r"\bcve-\d{4}-\d{4,}\b", text_lower) and not any(
            k in text_lower
            for k in ("0day", "zero-day", "exploit poc", "rce", "ransomware")
        ):
            vel, _ = self._calculate_empirical_ai_newsworthiness(text, Category.AI_TECH)
            return vel

        score = 10  # base for legacy security dispatches
        for pattern in self.THREAT_KEYWORDS["critical"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 30
        for pattern in self.THREAT_KEYWORDS["high"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 20
        for pattern in self.THREAT_KEYWORDS["medium"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 10
        for pattern in self.THREAT_KEYWORDS["low"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 5
        if re.search(r"\bcve-\d{4}-\d{4,}\b", text_lower):
            score += 15
        if re.search(r"\b(exploited|active|weaponized|poc)\b", text_lower):
            score += 20
        return min(100, max(1, score))

    def _calculate_severity(self, text: str, velocity: int) -> int:
        """Calculate technical depth or fallback severity index (1-100)."""
        text_lower = text.lower()
        if not re.search(r"\bcve-\d{4}-\d{4,}\b", text_lower) and not any(
            k in text_lower
            for k in ("0day", "zero-day", "exploit poc", "rce", "ransomware")
        ):
            _, impact = self._calculate_empirical_ai_newsworthiness(
                text, Category.AI_TECH
            )
            return impact

        score = velocity // 2
        if re.search(r"\b(critical|9\.[0-9]|10\.0)\b", text_lower):
            score += 30
        elif re.search(r"\b(high|7\.[0-9]|8\.[0-9])\b", text_lower):
            score += 20
        elif re.search(r"\b(medium|4\.[0-9]|5\.[0-9]|6\.[0-9])\b", text_lower):
            score += 10
        if re.search(r"\b(exploited|active|in.the.wild)\b", text_lower):
            score += 25
        return min(100, max(1, score))

    def _calculate_blast_radius(
        self, text: str, category: Category
    ) -> tuple[int, list[str]]:
        """Calculate blast radius score and affected ecosystem."""
        score = 10
        ecosystems = []
        text_lower = text.lower()

        # Check AI ecosystem patterns
        for ecosystem, patterns in self.AI_ECOSYSTEM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    ecosystems.append(ecosystem)
                    score += 15
                    break

        # Category-based scoring
        if category == Category.VULNERABILITIES:
            score += 20
            ecosystems.append("Enterprise Infrastructure")
        elif category == Category.AI_TECH:
            score += 15
            ecosystems.append("General AI Stack")
        elif category == Category.AI_RESEARCH:
            score += 10
            ecosystems.append("Research Infrastructure")

        # Widely used indicators
        if re.search(
            r"\b(widely.used|popular|millions|billions|enterprise)\b", text_lower
        ):
            score += 15

        return min(100, max(1, score)), list(set(ecosystems))

    def _detect_attack_archetype(self, text: str) -> str:
        """Detect attack archetype from text."""
        text_lower = text.lower()
        for archetype, patterns in self.ATTACK_ARCHETYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return archetype.value
        return AttackArchetype.STANDARD_VULN.value

    def _detect_pre_cve(self, text: str, category: Category) -> bool:
        """Detect if this is a pre-CVE academic warning."""
        text_lower = text.lower()
        if category != Category.AI_RESEARCH:
            return False

        # Academic paper indicators
        academic_indicators = [
            r"\barxiv\b",
            r"\bpreprint\b",
            r"\bproceeding\b",
            r"\bconference\b",
            r"\bwe.propose\b",
            r"\bwe.present\b",
            r"\bnovel\b",
            r"\bnew.attack\b",
            r"\battack.vector\b",
            r"\bthreat.model\b",
            r"\bvulnerability\b",
        ]

        for pattern in academic_indicators:
            if re.search(pattern, text_lower):
                return True

        return False

    MITRE_ATTACK_MAPPINGS = {
        AttackArchetype.JAILBREAK.value: (
            "AML.T0054",
            "LLM Jailbreak / Safety Filter Bypass",
        ),
        AttackArchetype.PROMPT_INJECTION.value: (
            "AML.T0051",
            "LLM Direct Prompt Injection",
        ),
        AttackArchetype.RAG_POISONING.value: (
            "AML.T0043",
            "RAG Knowledge Base & Context Poisoning",
        ),
        AttackArchetype.DATA_POISONING.value: (
            "AML.T0018",
            "Adversarial Data Poisoning",
        ),
        AttackArchetype.MODEL_INVERSION.value: (
            "AML.T0024",
            "Model Inversion & Weight Reconstruction",
        ),
        AttackArchetype.MODEL_EXTRACTION.value: (
            "AML.T0044",
            "Model Theft & Parameter Extraction",
        ),
        AttackArchetype.SUPPLY_CHAIN.value: (
            "T1195",
            "Supply Chain Compromise (PyPI/HuggingFace)",
        ),
        AttackArchetype.RCE.value: ("T1190", "Exploit Public-Facing Application (RCE)"),
        AttackArchetype.PRIVILEGE_ESCALATION.value: (
            "T1068",
            "Exploitation for Privilege Escalation",
        ),
    }

    def _map_mitre_attack(
        self, text: str, archetype: str, category: Category
    ) -> tuple[str, str]:
        """Map detected indicators to MITRE ATT&CK / ATLAS techniques."""
        if archetype in self.MITRE_ATTACK_MAPPINGS:
            return self.MITRE_ATTACK_MAPPINGS[archetype]

        text_lower = text.lower()
        if (
            "phish" in text_lower
            or "credential" in text_lower
            or "harvest" in text_lower
        ):
            return ("T1566", "Phishing / Credential Harvesting")
        if (
            "brute" in text_lower
            or "spray" in text_lower
            or "sniff" in text_lower
            or "wpa" in text_lower
        ):
            return ("T1110", "Brute Force / Password Sniffing")
        if (
            "command injection" in text_lower
            or "powershell" in text_lower
            or "script" in text_lower
        ):
            return ("T1059", "Command and Scripting Interpreter")
        if "traversal" in text_lower or "lfi" in text_lower or "rfi" in text_lower:
            return ("T1083", "File and Directory Discovery / Path Traversal")
        if (
            "ssrf" in text_lower
            or "deserial" in text_lower
            or "sqli" in text_lower
            or "sql injection" in text_lower
        ):
            return ("T1190", "Exploit Public-Facing Application")
        if (
            "dos" in text_lower
            or "denial of service" in text_lower
            or "exhaust" in text_lower
        ):
            return ("T1499", "Endpoint Denial of Service")
        if category in (Category.AI_TECH, Category.AI_MODELS):
            return ("AML.T0015", "Evade ML Model / AI Manipulation")
        if category == Category.EXPLOITS_TRICKS:
            return ("T1190", "Exploitation of Vulnerability (PoC)")
        if category == Category.CYBER_TOOLS:
            return ("T1588", "Obtain Capabilities / Security Tools")

        return ("T1190", "Exploit Public-Facing Application")

    def _detect_weaponization(self, text: str, category: Category | None = None) -> str:
        """Detect weaponization potential."""
        text_lower = text.lower()

        if re.search(
            r"\b(active|in.the.wild|exploited|ransomware|zero.day.active|actively.exploited)\b",
            text_lower,
        ):
            return WeaponizationLevel.ACTIVE_WEAPONIZATION.value
        elif (
            re.search(
                r"\b(poc|proof.of.concept|exploit.code|weaponized|metasploit|exploit.db|packetstorm|github.com/.*/exploit)\b",
                text_lower,
            )
            or "exploit-db" in text_lower
            or "metasploit" in text_lower
            or category == Category.EXPLOITS_TRICKS
        ):
            return WeaponizationLevel.POC_VERIFIED.value
        return WeaponizationLevel.THEORETICAL.value

    def _generate_attack_vector(self, text: str, archetype: str) -> str:
        """Generate attack vector description."""
        base = f"Attack archetype: {archetype}"
        text_lower = text.lower()

        if "injection" in text_lower:
            base += " - Input validation bypass leading to code execution"
        elif "overflow" in text_lower:
            base += " - Memory corruption via buffer overflow"
        elif "traversal" in text_lower:
            base += " - Path traversal accessing unauthorized files"
        elif "bypass" in text_lower:
            base += " - Authentication/authorization bypass"
        elif "poison" in text_lower:
            base += " - Data/model poisoning attack"
        else:
            base += " - Standard vulnerability exploitation"

        return base

    def _generate_risk_assessment(
        self, text: str, velocity: int, severity: int, category: Category
    ) -> str:
        """Generate risk assessment."""
        risk_level = (
            "Critical"
            if velocity >= 80
            else "High"
            if velocity >= 60
            else "Medium"
            if velocity >= 40
            else "Low"
        )
        return f"{risk_level} risk: Threat affecting {category.value.replace('_', ' ')}; potential service disruption or unauthorized access."

    def _generate_mitigation(self, text: str, archetype: str) -> str:
        """Generate mitigation advice."""
        mitigations = [
            "Apply official vendor patches immediately",
            "Restrict network ingress and isolate affected components",
            "Monitor execution logs for anomalous behavior",
            "Implement input validation and output encoding",
        ]

        if "injection" in text.lower():
            mitigations.insert(
                0, "Implement parameterized queries and input sanitization"
            )
        elif "jailbreak" in text.lower() or "prompt injection" in text.lower():
            mitigations.insert(
                0, "Deploy prompt injection defenses and output filtering"
            )
        elif "supply chain" in text.lower():
            mitigations.insert(0, "Verify dependency integrity and use SBOM")

        return "; ".join(mitigations[:3])

    AI_INNOVATION_CATEGORIES = {
        Category.AI_TECH,
        Category.AI_RESEARCH,
        Category.GITHUB_TRENDING,
        Category.AI_MODELS,
        Category.CYBER_TOOLS,
    }

    def _is_pure_ai_innovation(self, entry: Entry, text: str) -> bool:
        """Determine if entry is pure AI innovation/tool/paper rather than an active security threat."""
        text_lower = text.lower()
        if re.search(r"\bcve-\d{4}-\d{4,}\b", text_lower):
            return False
        threat_patterns = [
            r"\brce\b",
            r"\bremote code execution\b",
            r"\bzero[- ]day\b",
            r"\b0[- ]day\b",
            r"\bexploit\w*\b",
            r"\bransomware\b",
            r"\bjailbreak\b",
            r"\bprompt injection\b",
            r"\badversarial attack\b",
            r"\bbackdoor\b",
            r"\btrojan\b",
            r"\bprivilege escalation\b",
            r"\bdata poisoning\b",
            r"\bmodel inversion\b",
        ]
        if any(re.search(p, text_lower) for p in threat_patterns):
            return False
        if entry.category in self.AI_INNOVATION_CATEGORIES:
            return True
        # Treat general news and non-CVE, non-exploit dispatches as AI/technology innovation
        return True

    def _generate_ai_architecture(self, text: str, category: Category) -> str:
        text_lower = text.lower()
        if any(
            k in text_lower
            for k in (
                "reasoning",
                "r1",
                "o1",
                "cot",
                "chain of thought",
                "mcts",
                "math",
                "aime",
            )
        ):
            return "Architecture: Reasoning LLM & Multi-Step Chain-of-Thought"
        if any(
            k in text_lower
            for k in (
                "agent",
                "workflow",
                "swarm",
                "autonomous",
                "tool use",
                "function call",
            )
        ):
            return "Framework: Autonomous Multi-Agent Execution & Tool Calling"
        if any(
            k in text_lower
            for k in (
                "vision",
                "multimodal",
                "vlm",
                "diffusion",
                "audio",
                "video",
                "image",
                "tts",
                "speech",
            )
        ):
            return "Domain: Multimodal Generative AI (Vision / Audio / Video)"
        if any(
            k in text_lower
            for k in (
                "chip",
                "hardware",
                "semiconductor",
                "silicon",
                "blackwell",
                "b200",
                "gb200",
                "h100",
                "h200",
                "npu",
                "asic",
                "tpu",
                "amd mi",
                "nvidia h",
                "gaudi",
                "cerebras",
                "ascend",
            )
        ):
            return "Hardware: Next-Generation AI Accelerator & Silicon Architecture"
        if any(
            k in text_lower
            for k in (
                "vllm",
                "ollama",
                "inference",
                "quant",
                "gguf",
                "serving",
                "engine",
                "cuda",
                "triton",
            )
        ):
            return "Infrastructure: High-Throughput Inference & GPU Acceleration"
        if any(
            k in text_lower for k in ("rag", "vector", "embedding", "retriev", "chunk")
        ):
            return "Stack: Enterprise Retrieval-Augmented Generation (RAG)"
        if any(
            k in text_lower
            for k in ("fine-tun", "lora", "qlora", "sft", "rlhf", "dpo", "grpo")
        ):
            return "Methodology: Post-Training Alignment & Efficient Fine-Tuning"
        if any(
            k in text_lower
            for k in (
                "sovereign",
                "national ai",
                "regulation",
                "policy",
                "governance",
                "safety research",
                "alignment research",
            )
        ):
            return "Policy: AI Governance, Safety Research & Sovereign AI Ecosystem"
        if any(
            k in text_lower
            for k in (
                "robot",
                "robotics",
                "embodied",
                "manipulation",
                "locomotion",
                "drone",
                "humanoid",
            )
        ):
            return "Domain: Physical AI & Embodied Robotics Systems"
        if category == Category.GITHUB_TRENDING:
            return "Tool: Trending Open-Source Developer Repository"
        if category == Category.AI_RESEARCH:
            return "Research: ArXiv Breakthrough & Novel Algorithmic Paradigm"
        if category == Category.AI_MODELS:
            return "Model: Frontier Foundation Weights & Open Checkpoint"
        return ""

    def _generate_ai_highlight(self, text: str, category: Category) -> str:
        text_lower = text.lower()
        if any(
            k in text_lower
            for k in (
                "state-of-the-art",
                "sota",
                "outperform",
                "record",
                "surpass",
                "human-level",
                "beats",
            )
        ):
            return (
                "Breakthrough: Outperforms baselines on complex reasoning benchmarks."
            )
        if any(
            k in text_lower
            for k in (
                "open weights",
                "open-weights",
                "weights released",
                "open-source",
                "hugging face",
                "checkpoint",
                "publicly available",
            )
        ):
            return "Capability: Open weights checkpoint available for fine-tuning and inference."
        if any(
            k in text_lower
            for k in (
                "reasoning",
                "chain of thought",
                "cot",
                "test-time compute",
                "extended thinking",
                "inference-time",
                "o1",
                "o3",
                "r1",
                "long thinking",
            )
        ):
            return "Architecture: Advanced reasoning with multi-step chain-of-thought capabilities."
        if any(
            k in text_lower
            for k in (
                "efficiency",
                "throughput",
                "low latency",
                "quant",
                "memory",
                "faster",
                "speed",
                "optimized",
                "tokens/s",
            )
        ):
            return (
                "Efficiency: Significant latency reduction and compute optimizations."
            )
        if any(
            k in text_lower
            for k in (
                "multimodal",
                "vision",
                "audio",
                "video",
                "vlm",
                "text-to-image",
                "speech",
            )
        ):
            return "Capability: Multimodal understanding across vision, audio, and text modalities."
        if any(
            k in text_lower
            for k in (
                "agent",
                "autonomous",
                "tool use",
                "function calling",
                "workflow",
                "agentic",
            )
        ):
            return "Capability: Autonomous agent execution with tool-calling and multi-step planning."
        if any(
            k in text_lower
            for k in (
                "fine-tun",
                "lora",
                "qlora",
                "sft",
                "rlhf",
                "dpo",
                "grpo",
                "alignment",
            )
        ):
            return "Training: Post-training alignment and efficient fine-tuning methodology."
        if category == Category.GITHUB_TRENDING:
            return "Ecosystem: High adoption velocity across developer communities worldwide."
        if category == Category.AI_RESEARCH:
            return "Research: Theoretical framework with empirical validation on key benchmarks."
        if category == Category.AI_MODELS:
            return "Release: New foundation model weights available for production deployment."
        return ""

    def _generate_ai_quickstart(
        self, text: str, category: Category, metadata: dict
    ) -> str:
        lang = metadata.get("language") if metadata else None
        repo = metadata.get("repo_name") if metadata else None
        if repo:
            return f"Quick Start: Clone via https://github.com/{repo}; supports {lang or 'Python'}. Run locally with standard runtimes."
        if category == Category.AI_RESEARCH:
            return "Open Access: Preprint available on arXiv; reference implementation included."
        if category == Category.AI_MODELS:
            return "Deployment: Checkpoints accessible on Hugging Face; compatible with standard runtimes."
        return ""

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry using heuristics with dual-mode support for AI innovation vs cyber threats."""
        full_text = (
            f"{entry.title} {entry.summary} {entry.metadata.get('description', '')}"
        )

        if self._is_pure_ai_innovation(entry, full_text):
            # AI Innovation Mode
            arch = self._generate_ai_architecture(full_text, entry.category)
            highlight = self._generate_ai_highlight(full_text, entry.category)
            quickstart = self._generate_ai_quickstart(
                full_text, entry.category, entry.metadata
            )
            _, ecosystems = self._calculate_blast_radius(full_text, entry.category)

            # Compute empirical AI newsworthiness (velocity and impact)
            velocity, impact = self._calculate_empirical_ai_newsworthiness(
                full_text, entry.category, entry.metadata
            )

            archetype = (
                "AI Model Release"
                if entry.category == Category.AI_MODELS
                else "Trending Repository"
                if entry.category == Category.GITHUB_TRENDING
                else "Academic Research Paper"
                if entry.category == Category.AI_RESEARCH
                else "Developer AI Tool"
                if entry.category == Category.CYBER_TOOLS
                else "AI Technology Launch"
            )

            weaponization = (
                "Open Weights Available"
                if entry.category == Category.AI_MODELS
                else "Production Ready"
                if entry.category in (Category.GITHUB_TRENDING, Category.CYBER_TOOLS)
                else "Research Preprint"
                if entry.category == Category.AI_RESEARCH
                else "Production Ready"
            )

            return AnalysisResult(
                entry_id=entry.id,
                attack_vector=arch,
                risk_assessment=highlight,
                mitigation=quickstart,
                threat_velocity=velocity,
                severity_index=impact,
                blast_radius_score=0,
                affected_ecosystem=ecosystems,
                is_pre_cve_warning=False,
                attack_archetype=archetype,
                weaponization_potential=weaponization,
                mitre_attack_id=None,
                mitre_technique=None,
                model=AnalysisModel.HEURISTIC,
                confidence=0.90,
            )

        # Cyber Threat / Security Mode
        velocity = self._calculate_threat_velocity(full_text)
        severity = self._calculate_severity(full_text, velocity)
        blast_radius, ecosystems = self._calculate_blast_radius(
            full_text, entry.category
        )
        archetype = self._detect_attack_archetype(full_text)
        is_pre_cve = self._detect_pre_cve(full_text, entry.category)
        weaponization = self._detect_weaponization(full_text, entry.category)
        mitre_id, mitre_technique = self._map_mitre_attack(
            full_text, archetype, entry.category
        )

        return AnalysisResult(
            entry_id=entry.id,
            attack_vector=self._generate_attack_vector(full_text, archetype),
            risk_assessment=self._generate_risk_assessment(
                full_text, velocity, severity, entry.category
            ),
            mitigation=self._generate_mitigation(full_text, archetype),
            threat_velocity=velocity,
            severity_index=severity,
            blast_radius_score=blast_radius,
            affected_ecosystem=ecosystems,
            is_pre_cve_warning=is_pre_cve,
            attack_archetype=archetype,
            weaponization_potential=weaponization,
            mitre_attack_id=mitre_id,
            mitre_technique=mitre_technique,
            model=AnalysisModel.HEURISTIC,
            confidence=0.85,
        )


analyzer_registry.register("heuristic", HeuristicAnalyzer)
