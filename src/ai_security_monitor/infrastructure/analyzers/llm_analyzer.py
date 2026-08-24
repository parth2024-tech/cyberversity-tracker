# LLM-based analyzer with Ollama and Groq support.

import json
import os
from typing import Optional
from uuid import UUID

from ai_security_monitor.domain.entities import Entry, AnalysisModel
from ai_security_monitor.domain.value_objects import ThreatScore, WeaponizationLevel, AttackArchetype
from ai_security_monitor.infrastructure.analyzers.base import BaseAnalyzer, AnalysisResult, analyzer_registry
from ai_security_monitor.config.settings import settings


class LLMAnalyzer(BaseAnalyzer):
    """LLM-based analyzer supporting Ollama and Groq."""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self.provider = config.get("provider", "ollama") if config else "ollama"
        self.model_name = config.get("model", settings.analyzer.ollama_model) if config else settings.analyzer.ollama_model
        self.max_tokens = config.get("max_tokens", settings.analyzer.max_tokens) if config else settings.analyzer.max_tokens
        self.temperature = config.get("temperature", settings.analyzer.temperature) if config else settings.analyzer.temperature

        # Initialize client based on provider
        if self.provider == "groq":
            self._init_groq()
        else:
            self._init_ollama()

    def _init_ollama(self):
        """Initialize Ollama client."""
        self.ollama_host = settings.analyzer.ollama_host
        self.ollama_model = self.model_name

    def _init_groq(self):
        """Initialize Groq client."""
        try:
            from groq import Groq
            api_key = settings.analyzer.groq_api_key or os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Groq API key not configured")
            self.client = Groq(api_key=api_key)
            self.model_name = settings.analyzer.groq_model
        except ImportError:
            raise ValueError("Groq package not installed. Install with: pip install groq")

    @property
    def analyzer_type(self) -> str:
        return f"llm_{self.provider}"

    @property
    def model(self) -> AnalysisModel:
        return AnalysisModel.OLLAMA if self.provider == "ollama" else AnalysisModel.GROQ

    def _build_prompt(self, entry: Entry) -> str:
        """Build analysis prompt for LLM."""
        return f"""Analyze this security/AI intelligence entry and provide structured output.

Title: {entry.title}
Summary: {entry.summary}
Category: {entry.category.value}
Tags: {', '.join(entry.tags)}
URL: {entry.url}

Provide JSON output with these fields:
- attack_vector: Brief description of the exploitation vector
- risk_assessment: Risk level and impact description
- mitigation: Specific mitigation steps (max 3)
- threat_velocity: 1-100 (how fast this threat is moving)
- severity_index: 1-100 (potential impact severity)
- blast_radius_score: 1-100 (ecosystem impact)
- affected_ecosystem: List of affected frameworks/platforms
- is_pre_cve_warning: true/false (academic pre-CVE research)
- attack_archetype: One of [Jailbreak, RAG Poisoning, Model Inversion, Prompt Injection, Data Poisoning, Model Extraction, Supply Chain Compromise, RCE, Privilege Escalation, Novel Academic Threat Vector, Standard Vulnerability, Unknown]
- weaponization_potential: One of [Theoretical, PoC Verified, Active Weaponization]

JSON only, no extra text."""

    async def _call_ollama(self, prompt: str) -> dict:
        """Call Ollama API."""
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return json.loads(data["response"])

    async def _call_groq(self, prompt: str) -> dict:
        """Call Groq API."""
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry using LLM."""
        prompt = self._build_prompt(entry)

        try:
            if self.provider == "groq":
                result = await self._call_groq(prompt)
            else:
                result = await self._call_ollama(prompt)

            # Validate and normalize
            return AnalysisResult(
                entry_id=entry.id,
                attack_vector=result.get("attack_vector", "Analysis unavailable"),
                risk_assessment=result.get("risk_assessment", "Risk assessment unavailable"),
                mitigation=result.get("mitigation", "No mitigation provided"),
                threat_velocity=max(1, min(100, result.get("threat_velocity", 50))),
                severity_index=max(1, min(100, result.get("severity_index", 50))),
                blast_radius_score=max(0, min(100, result.get("blast_radius_score", 0))),
                affected_ecosystem=result.get("affected_ecosystem", []),
                is_pre_cve_warning=result.get("is_pre_cve_warning", False),
                attack_archetype=result.get("attack_archetype", "Unknown"),
                weaponization_potential=result.get("weaponization_potential", "Theoretical"),
                model=self.model,
                confidence=0.9,
            )
        except Exception as e:
            # Fallback to heuristic on LLM failure
            print(f"LLM analysis failed, falling back to heuristic: {e}")
            from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import HeuristicAnalyzer
            fallback = HeuristicAnalyzer()
            return await fallback.analyze(entry)


analyzer_registry.register("ollama", LLMAnalyzer)
analyzer_registry.register("groq", LLMAnalyzer)
