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
        ],
        "low": [
            r"\b(xss|reflected)\b",
            r"\b(open.redirect)\b",
            r"\b(missing.auth)\b",
            r"\b(weak.crypto)\b",
        ],
    }

    AI_ECOSYSTEM_PATTERNS = {
        "PyTorch": [r"\bpytorch\b", r"\btorch\b", r"\btorchvision\b", r"\btorchaudio\b"],
        "TensorFlow": [r"\btensorflow\b", r"\bkeras\b", r"\btflite\b"],
        "HuggingFace": [r"\bhuggingface\b", r"\btransformers\b", r"\btokenizers\b", r"\bpeft\b"],
        "LangChain": [r"\blangchain\b", r"\blanggraph\b"],
        "LlamaIndex": [r"\bllamaindex\b"],
        "Ollama": [r"\bollama\b"],
        "vLLM": [r"\bvllm\b"],
        "ONNX": [r"\bonnx\b"],
        "CUDA": [r"\bcuda\b", r"\bcudnn\b"],
        "JAX": [r"\bjax\b", r"\bflax\b"],
    }

    ATTACK_ARCHETYPE_PATTERNS = {
        AttackArchetype.JAILBREAK: [r"\bjailbreak\b", r"\bbypass.*guard\b", r"\bunaligned\b"],
        AttackArchetype.RAG_POISONING: [r"\brag.*poison\b", r"\bpoison.*retrieval\b", r"\bcorrupt.*knowledge\b"],
        AttackArchetype.MODEL_INVERSION: [r"\bmodel.inversion\b", r"\binvert.*model\b", r"\bextract.*weights\b"],
        AttackArchetype.PROMPT_INJECTION: [r"\bprompt.injection\b", r"\binject.*prompt\b", r"\bsystem.prompt\b"],
        AttackArchetype.DATA_POISONING: [r"\bdata.poison\b", r"\bpoison.*training\b", r"\bbackdoor.*model\b"],
        AttackArchetype.MODEL_EXTRACTION: [r"\bmodel.extraction\b", r"\bsteal.*model\b", r"\bextract.*architecture\b"],
        AttackArchetype.SUPPLY_CHAIN: [r"\bsupply.chain\b", r"\bdependency.confusion\b", r"\btyposquat\b"],
        AttackArchetype.RCE: [r"\brce\b", r"\bremote.code.execution\b", r"\barbitrary.code\b"],
        AttackArchetype.PRIVILEGE_ESCALATION: [r"\bprivilege.escalation\b", r"\bescalate.*privilege\b"],
    }

    def _calculate_threat_velocity(self, text: str) -> int:
        """Calculate threat velocity score (1-100)."""
        score = 10  # base
        text_lower = text.lower()

        # Check critical patterns
        for pattern in self.THREAT_KEYWORDS["critical"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 30

        # Check high patterns
        for pattern in self.THREAT_KEYWORDS["high"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 20

        # Check medium patterns
        for pattern in self.THREAT_KEYWORDS["medium"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 10

        # Check low patterns
        for pattern in self.THREAT_KEYWORDS["low"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 5

        # Boost for CVE mentions
        if re.search(r"\bcve-\d{4}-\d{4,}\b", text_lower):
            score += 15

        # Boost for "exploited" or "active"
        if re.search(r"\b(exploited|active|weaponized|poc)\b", text_lower):
            score += 20

        return min(100, max(1, score))

    def _calculate_severity(self, text: str, velocity: int) -> int:
        """Calculate severity index (1-100)."""
        score = velocity // 2  # base from velocity
        text_lower = text.lower()

        # CVSS-like keywords
        if re.search(r"\b(critical|9\.[0-9]|10\.0)\b", text_lower):
            score += 30
        elif re.search(r"\b(high|7\.[0-9]|8\.[0-9])\b", text_lower):
            score += 20
        elif re.search(r"\b(medium|4\.[0-9]|5\.[0-9]|6\.[0-9])\b", text_lower):
            score += 10

        # Exploited in wild
        if re.search(r"\b(exploited|active|in.the.wild)\b", text_lower):
            score += 25

        return min(100, max(1, score))

    def _calculate_blast_radius(self, text: str, category: Category) -> tuple[int, list[str]]:
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
        if re.search(r"\b(widely.used|popular|millions|billions|enterprise)\b", text_lower):
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
            r"\barxiv\b", r"\bpreprint\b", r"\bproceeding\b", r"\bconference\b",
            r"\bwe.propose\b", r"\bwe.present\b", r"\bnovel\b", r"\bnew.attack\b",
            r"\battack.vector\b", r"\bthreat.model\b", r"\bvulnerability\b",
        ]

        for pattern in academic_indicators:
            if re.search(pattern, text_lower):
                return True

        return False

    def _detect_weaponization(self, text: str) -> str:
        """Detect weaponization potential."""
        text_lower = text.lower()

        if re.search(r"\b(poc|proof.of.concept|exploit.code|weaponized)\b", text_lower):
            return WeaponizationLevel.POC_VERIFIED.value
        elif re.search(r"\b(active|in.the.wild|exploited|ransomware)\b", text_lower):
            return WeaponizationLevel.ACTIVE_WEAPONIZATION.value
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

    def _generate_risk_assessment(self, text: str, velocity: int, severity: int, category: Category) -> str:
        """Generate risk assessment."""
        risk_level = "Critical" if velocity >= 80 else "High" if velocity >= 60 else "Medium" if velocity >= 40 else "Low"
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
            mitigations.insert(0, "Implement parameterized queries and input sanitization")
        elif "jailbreak" in text.lower() or "prompt injection" in text.lower():
            mitigations.insert(0, "Deploy prompt injection defenses and output filtering")
        elif "supply chain" in text.lower():
            mitigations.insert(0, "Verify dependency integrity and use SBOM")

        return "; ".join(mitigations[:3])

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry using heuristics."""
        full_text = f"{entry.title} {entry.summary} {entry.metadata.get('description', '')}"

        velocity = self._calculate_threat_velocity(full_text)
        severity = self._calculate_severity(full_text, velocity)
        blast_radius, ecosystems = self._calculate_blast_radius(full_text, entry.category)
        archetype = self._detect_attack_archetype(full_text)
        is_pre_cve = self._detect_pre_cve(full_text, entry.category)
        weaponization = self._detect_weaponization(full_text)

        return AnalysisResult(
            entry_id=entry.id,
            attack_vector=self._generate_attack_vector(full_text, archetype),
            risk_assessment=self._generate_risk_assessment(full_text, velocity, severity, entry.category),
            mitigation=self._generate_mitigation(full_text, archetype),
            threat_velocity=velocity,
            severity_index=severity,
            blast_radius_score=blast_radius,
            affected_ecosystem=ecosystems,
            is_pre_cve_warning=is_pre_cve,
            attack_archetype=archetype,
            weaponization_potential=weaponization,
            model=AnalysisModel.HEURISTIC,
            confidence=0.85,
        )


analyzer_registry.register("heuristic", HeuristicAnalyzer)
