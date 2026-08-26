# LLM-based analyzer with Ollama, Groq, and local gateway support.

import json
import os

from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import AnalysisModel, Entry
from ai_security_monitor.infrastructure.analyzers.base import (
    AnalysisResult,
    BaseAnalyzer,
    analyzer_registry,
)


class LLMAnalyzer(BaseAnalyzer):
    """LLM-based analyzer supporting Ollama, Groq, and local gateway (auto/offline)."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self.provider = cfg.get("provider") or ("groq" if (settings.analyzer.groq_api_key and cfg.get("provider") == "groq") else "ollama")
        self.max_tokens = cfg.get("max_tokens", 250)
        self.temperature = cfg.get("temperature", settings.analyzer.temperature)

        # Route to Groq if explicitly requested, otherwise use local Ollama
        if self.provider == "groq":
            self._init_groq()
        else:
            self._init_ollama()

    def _init_ollama(self):
        """Initialize Ollama client."""
        cfg = self.config or {}
        self.ollama_host = cfg.get("ollama_host", settings.analyzer.ollama_host)
        # Use qwen2:0.5b (138 tokens/sec on RTX 3050 GPU) or specified model
        self.ollama_model = cfg.get("ollama_model") or "qwen2:0.5b"
        self._use_gateway = False

    def _init_groq(self):
        """Initialize Groq client."""
        try:
            from groq import Groq
            api_key = settings.analyzer.groq_api_key or os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Groq API key not configured")
            self.client = Groq(api_key=api_key)
            self.groq_model = settings.analyzer.groq_model
            self._use_gateway = False
        except ImportError:
            raise ValueError("Groq package not installed. Install with: pip install groq")

    def _init_gateway(self):
        """Initialize local gateway (Hermes omniroute) client."""
        self.gateway_host = "http://localhost:20128/v1"
        self.gateway_model = settings.analyzer.local_model
        self._use_gateway = True

    @property
    def analyzer_type(self) -> str:
        if self.provider in ("ollama", "heuristic"):
            return f"llm_{self.provider}"
        elif self.provider == "groq":
            return "llm_groq"
        else:
            return "llm_local"

    @property
    def model(self) -> AnalysisModel:
        if self.provider == "groq":
            return AnalysisModel.GROQ
        elif self.provider == "ollama":
            return AnalysisModel.OLLAMA
        else:
            return AnalysisModel.LOCAL

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
        """Call Ollama API with guaranteed JSON format."""
        import httpx
        import re

        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post(f"{self.ollama_host}/api/generate", json=payload)
                response.raise_for_status()
            except Exception as first_err:
                # If primary model fails or times out, fallback to ultra-fast qwen2:0.5b
                try:
                    payload["model"] = "qwen2:0.5b"
                    response = await client.post(f"{self.ollama_host}/api/generate", json=payload)
                    response.raise_for_status()
                except Exception:
                    raise first_err

            data = response.json()
            raw_content = data.get("response", "{}")
            try:
                return json.loads(raw_content)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                raise

    async def _call_groq(self, prompt: str) -> dict:
        """Call Groq API."""
        response = await self.client.chat.completions.create(
            model=self.groq_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    async def _call_gateway(self, prompt: str) -> dict:
        """Call local gateway (Hermes omniroute) API."""
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.gateway_host}/chat/completions",
                json={
                    "model": self.gateway_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            # Extract JSON from response (may have reasoning content)
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Try to find JSON in the response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                raise

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry using LLM."""
        prompt = self._build_prompt(entry)

        try:
            if self.provider == "groq":
                result = await self._call_groq(prompt)
            elif self.provider in ("ollama", "heuristic"):
                result = await self._call_ollama(prompt)
            else:
                result = await self._call_gateway(prompt)

            # Validate and normalize string fields
            raw_risk = result.get("risk_assessment")
            if isinstance(raw_risk, dict):
                risk_str = f"{raw_risk.get('risk_level', 'High')} risk: {raw_risk.get('impact_description', '')}"
            elif isinstance(raw_risk, list):
                risk_str = "; ".join(str(x) for x in raw_risk)
            else:
                risk_str = str(raw_risk or "Risk assessment unavailable")

            raw_mit = result.get("mitigation")
            if isinstance(raw_mit, list):
                mit_str = "; ".join(str(m) for m in raw_mit)
            elif isinstance(raw_mit, dict):
                mit_str = "; ".join(f"{k}: {v}" for k, v in raw_mit.items())
            else:
                mit_str = str(raw_mit or "No mitigation provided")

            raw_vector = result.get("attack_vector")
            if isinstance(raw_vector, (dict, list)):
                vector_str = str(raw_vector)
            else:
                vector_str = str(raw_vector or "Analysis unavailable")

            raw_eco = result.get("affected_ecosystem", [])
            if isinstance(raw_eco, str):
                raw_eco = [raw_eco]

            return AnalysisResult(
                entry_id=entry.id,
                attack_vector=vector_str,
                risk_assessment=risk_str,
                mitigation=mit_str,
                threat_velocity=max(1, min(100, int(result.get("threat_velocity", 50)))),
                severity_index=max(1, min(100, int(result.get("severity_index", 50)))),
                blast_radius_score=max(0, min(100, int(result.get("blast_radius_score", 0)))),
                affected_ecosystem=raw_eco if isinstance(raw_eco, list) else [],
                is_pre_cve_warning=bool(result.get("is_pre_cve_warning", False)),
                attack_archetype=str(result.get("attack_archetype", "Unknown")),
                weaponization_potential=str(result.get("weaponization_potential", "Theoretical")),
                model=self.model,
                confidence=0.95,
            )
        except Exception as e:
            # Fallback to heuristic on LLM failure
            print(f"LLM analysis failed ({self.provider}), falling back to heuristic: {e}")
            from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
                HeuristicAnalyzer,
            )
            fallback = HeuristicAnalyzer()
            return await fallback.analyze(entry)


analyzer_registry.register("ollama", LLMAnalyzer)
analyzer_registry.register("groq", LLMAnalyzer)
analyzer_registry.register("local", LLMAnalyzer)
analyzer_registry.register("local_llm", LLMAnalyzer)
analyzer_registry.register("gateway", LLMAnalyzer)
analyzer_registry.register("auto/offline", LLMAnalyzer)
