# LLM-based analyzer with Tiered SLM routing, Fast-Fail Circuit Breaker,
# Ephemeral Prompt Caching, and Resilient Small-Model Output Parsing.

from __future__ import annotations

import json
import os
from typing import Any

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.core.sanitizer import sanitizer
from ai_security_monitor.domain.entities import AnalysisModel, Entry
from ai_security_monitor.infrastructure.analyzers.base import (
    AnalysisResult,
    BaseAnalyzer,
    analyzer_registry,
)
from ai_security_monitor.infrastructure.analyzers.prompt_cache import (
    STATIC_ANALYZER_SYSTEM_PROMPT,
    build_cached_prompt_messages,
)
from ai_security_monitor.infrastructure.analyzers.slm_circuit_breaker import (
    slm_circuit_breaker,
)
from ai_security_monitor.infrastructure.analyzers.structured_output_parser import (
    normalize_slm_analysis_payload,
    parse_slm_json,
)

logger = get_logger(__name__)


class LLMAnalyzer(BaseAnalyzer):
    """Tiered LLM/SLM analyzer with prompt caching, circuit breaker, and receipts."""

    def __init__(
        self,
        config: dict | None = None,
        receipt_service: Any | None = None,
        enable_receipts: bool = True,
    ):
        super().__init__(config)
        cfg = config or {}
        self.provider = cfg.get("provider") or (
            "groq"
            if (settings.analyzer.groq_api_key and cfg.get("provider") == "groq")
            else (
                settings.analyzer.default_model
                if settings.analyzer.default_model != "heuristic"
                else "tiered"
            )
        )
        self.tier = cfg.get("tier", "tiered")  # "tiered", "local_slm", "cloud_frontier"
        self.max_tokens = cfg.get("max_tokens", 400)
        self.temperature = cfg.get("temperature", settings.analyzer.temperature)
        self.enable_receipts = enable_receipts
        self._last_cache_read_tokens: int = 0
        self._last_cache_creation_tokens: int = 0

        if receipt_service is not None:
            self.receipt_service = receipt_service
        elif self.enable_receipts:
            try:
                from ai_security_monitor.application.services.llm_receipt_service import (
                    LLMReceiptService,
                )

                self.receipt_service = LLMReceiptService()
            except Exception:
                self.receipt_service = None
        else:
            self.receipt_service = None

        self._init_ollama()
        if settings.analyzer.groq_api_key or cfg.get("provider") == "groq":
            try:
                self._init_groq()
            except Exception as e:
                logger.debug(f"Groq initialization notice: {e}")

    def _init_ollama(self) -> None:
        """Initialize Ollama / Local SLM configuration."""
        cfg = self.config or {}
        self.ollama_host = cfg.get(
            "ollama_host",
            settings.analyzer.slm_endpoint or settings.analyzer.ollama_host,
        )
        self.ollama_model = cfg.get(
            "ollama_model",
            settings.analyzer.slm_model or settings.analyzer.ollama_model,
        )
        self._use_gateway = False

    def _init_groq(self) -> None:
        """Initialize Groq client."""
        try:
            from groq import AsyncGroq

            api_key = settings.analyzer.groq_api_key or os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Groq API key not configured")
            self.client = AsyncGroq(api_key=api_key)
        except ImportError:
            from groq import Groq

            api_key = settings.analyzer.groq_api_key or os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Groq API key not configured")
            self.client = Groq(api_key=api_key)  # type: ignore[assignment]
        self.groq_model = (
            settings.analyzer.cloud_fast_model or settings.analyzer.groq_model
        )
        self._use_gateway = False

    def _init_gateway(self) -> None:
        """Initialize local gateway (Hermes omniroute) client."""
        self.gateway_host = "http://localhost:20128/v1"
        self.gateway_model = settings.analyzer.local_model
        self._use_gateway = True

    @property
    def analyzer_type(self) -> str:
        if self.provider in ("ollama", "heuristic", "local_slm", "tiered"):
            return f"llm_{self.provider}"
        elif self.provider == "groq":
            return "llm_groq"
        else:
            return "llm_local"

    @property
    def model(self) -> AnalysisModel:
        if self.provider == "groq":
            return AnalysisModel.GROQ
        elif self.provider in ("ollama", "local_slm", "tiered"):
            return AnalysisModel.OLLAMA
        else:
            return AnalysisModel.LOCAL

    def _build_user_prompt(self, entry: Entry) -> str:
        """Build dynamic entry payload isolated from static rubric and schema."""
        safe_title = sanitizer.sanitize_text(entry.title)
        safe_summary = sanitizer.sanitize_text(entry.summary)
        safe_tags = [sanitizer.sanitize_text(t) for t in (entry.tags or [])]
        cat_str = (
            entry.category.value
            if hasattr(entry.category, "value")
            else str(entry.category)
        )

        return (
            f"Title: {safe_title}\n"
            f"Summary: {safe_summary}\n"
            f"Category: {cat_str}\n"
            f"Tags: {', '.join(safe_tags)}\n"
            f"URL: {entry.url}"
        )

    def _build_prompt(self, entry: Entry) -> str:
        """Legacy combined prompt for backward compatibility."""
        user_part = self._build_user_prompt(entry)
        return f"{STATIC_ANALYZER_SYSTEM_PROMPT}\n\n{user_part}"

    async def _call_ollama(
        self, prompt: str, user_prompt: str | None = None
    ) -> dict[str, Any]:
        """Call Ollama / Local SLM with circuit breaker and resilient parsing."""
        if slm_circuit_breaker.is_tripped:
            raise RuntimeError(
                f"Local SLM circuit breaker is OPEN (cooldown active {slm_circuit_breaker.cooldown_remaining:.1f}s)"
            )

        import httpx

        endpoint = getattr(self, "ollama_host", settings.analyzer.slm_endpoint).rstrip(
            "/"
        )
        model = getattr(self, "ollama_model", settings.analyzer.slm_model)

        timeout = httpx.Timeout(
            connect=settings.analyzer.slm_timeout_seconds,
            read=20.0,
            write=10.0,
            pool=5.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    # 1. Try generate API endpoint
                    resp = await client.post(
                        f"{endpoint}/api/generate",
                        json={
                            "model": model,
                            "system": STATIC_ANALYZER_SYSTEM_PROMPT,
                            "prompt": user_prompt or prompt,
                            "stream": False,
                            "format": "json",
                            "options": {
                                "temperature": self.temperature,
                                "num_predict": self.max_tokens,
                            },
                        },
                    )
                    resp.raise_for_status()
                except Exception as first_err:
                    # Fallback to fast qwen2:0.5b on primary failure
                    try:
                        resp = await client.post(
                            f"{endpoint}/api/generate",
                            json={
                                "model": "qwen2:0.5b",
                                "prompt": user_prompt or prompt,
                                "stream": False,
                                "format": "json",
                                "options": {
                                    "temperature": self.temperature,
                                    "num_predict": self.max_tokens,
                                },
                            },
                        )
                        resp.raise_for_status()
                    except Exception:
                        raise first_err

                data = resp.json()
                content = data.get("response", "") or (
                    data.get("message", {}).get("content", "")
                    if isinstance(data.get("message"), dict)
                    else ""
                )

                parsed = parse_slm_json(content)
                if parsed:
                    slm_circuit_breaker.record_success()
                    return parsed
                raise ValueError("Could not parse structured JSON from SLM response")

        except (httpx.ConnectError, httpx.ConnectTimeout) as net_err:
            slm_circuit_breaker.record_failure(net_err)
            raise net_err

    async def _call_groq(
        self, prompt: str, user_prompt: str | None = None
    ) -> dict[str, Any]:
        """Call Groq API with prompt caching support."""
        import inspect

        messages = build_cached_prompt_messages(
            STATIC_ANALYZER_SYSTEM_PROMPT,
            user_prompt or prompt,
            provider="groq",
            enable_caching=settings.analyzer.enable_prompt_caching,
        )

        create_res = self.client.chat.completions.create(  # type: ignore[call-overload]
            model=self.groq_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        if inspect.isawaitable(create_res):
            response = await create_res
        else:
            response = create_res

        content = response.choices[0].message.content
        data = parse_slm_json(content) or json.loads(content)

        usage = getattr(response, "usage", None)
        cache_read = 0
        cache_create = 0
        if usage:
            details = getattr(usage, "prompt_tokens_details", None)
            if details:
                cache_read = getattr(details, "cached_tokens", 0) or 0

        self._last_cache_read_tokens = cache_read
        self._last_cache_creation_tokens = cache_create
        return data

    async def _call_gateway(self, prompt: str) -> dict[str, Any]:
        """Call local gateway (Hermes omniroute) API."""
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.gateway_host}/chat/completions",
                json={
                    "model": getattr(self, "gateway_model", "auto/offline"),
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = parse_slm_json(content)
            if parsed:
                return parsed
            return json.loads(content)

    def _get_active_model_name(self) -> str:
        if self.provider == "groq":
            return getattr(self, "groq_model", "groq")
        elif self.provider in ("ollama", "local_slm", "tiered"):
            return getattr(self, "ollama_model", settings.analyzer.slm_model)
        else:
            return getattr(self, "gateway_model", "local")

    def _build_analysis_result(
        self,
        entry: Entry,
        result: dict[str, Any],
        active_model: AnalysisModel,
        reused_receipt: bool = False,
    ) -> AnalysisResult:
        normalized = normalize_slm_analysis_payload(result, default_title=entry.title)

        risk_str = sanitizer.strip_introductory_phrases(normalized["risk_assessment"])
        mit_str = sanitizer.strip_introductory_phrases(normalized["mitigation"])
        vector_str = sanitizer.strip_introductory_phrases(normalized["attack_vector"])

        return AnalysisResult(
            entry_id=entry.id,
            attack_vector=vector_str,
            risk_assessment=risk_str,
            mitigation=mit_str,
            threat_velocity=normalized["threat_velocity"],
            severity_index=normalized["severity_index"],
            blast_radius_score=normalized["blast_radius_score"],
            affected_ecosystem=normalized["affected_ecosystem"],
            is_pre_cve_warning=False,
            attack_archetype=normalized["attack_archetype"],
            weaponization_potential=normalized["weaponization_potential"],
            model=active_model,
            confidence=0.95,
        )

    async def analyze(self, entry: Entry) -> AnalysisResult:
        """Analyze entry using Tiered SLM routing with prompt caching and circuit breaker."""
        model_name = self._get_active_model_name()
        logical_key: str | None = None

        # Check idempotent receipts and poison entry retry cap
        if self.receipt_service:
            try:
                (
                    logical_key,
                    receipt,
                    should_call,
                ) = await self.receipt_service.check_or_record_attempt(
                    entry=entry,
                    provider=self.provider,
                    model=model_name,
                )
                if receipt.status == "succeeded" and receipt.response_json:
                    logger.info(
                        f"⚡ Idempotent receipt hit ({logical_key[:10]}...): reusing cached analysis for {entry.title[:45]}"
                    )
                    return self._build_analysis_result(
                        entry, receipt.response_json, self.model, reused_receipt=True
                    )
                if not should_call:
                    logger.warning(
                        f"🛑 Poison entry {entry.id} ({entry.title[:40]}) halted by receipt retry cap ({receipt.attempts}/{receipt.max_attempts})"
                    )
                    from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
                        HeuristicAnalyzer,
                    )

                    return await HeuristicAnalyzer().analyze(entry)
            except Exception as rc_err:
                logger.debug(f"Receipt attempt check non-blocking error: {rc_err}")

        user_prompt = self._build_user_prompt(entry)
        combined_prompt = self._build_prompt(entry)

        result: dict[str, Any] | None = None
        active_model = self.model
        execution_tier = "local_slm"
        cache_read_tokens = 0
        cache_creation_tokens = 0

        # High-signal check: items with high velocity, user-vaulted status, or explicit frontier override
        is_high_signal = bool(
            (entry.metadata or {}).get("force_frontier")
            or (entry.metadata or {}).get("is_high_priority")
            or self.tier == "cloud_frontier"
        )

        def _extract_groq_res(raw_res: Any) -> tuple[dict[str, Any], int, int]:
            if isinstance(raw_res, tuple) and len(raw_res) == 3:
                return raw_res[0], int(raw_res[1]), int(raw_res[2])
            return (
                raw_res,
                int(getattr(self, "_last_cache_read_tokens", 0)),
                int(getattr(self, "_last_cache_creation_tokens", 0)),
            )

        try:
            # 1. Tier 2 Cloud Frontier (for high-signal items or when provider is groq)
            if (is_high_signal or self.provider == "groq") and hasattr(self, "client"):
                raw_res = await self._call_groq(combined_prompt, user_prompt=user_prompt)
                result, cache_read_tokens, cache_creation_tokens = _extract_groq_res(raw_res)
                active_model = AnalysisModel.GROQ
                execution_tier = (
                    "cloud_cached" if cache_read_tokens > 0 else "cloud_uncached"
                )

            # 2. Tier 1 Local SLM (Ollama / Qwen2.5 / Llama3.2)
            elif not slm_circuit_breaker.is_tripped and getattr(
                settings.analyzer, "slm_enabled", True
            ):
                try:
                    result = await self._call_ollama(
                        combined_prompt, user_prompt=user_prompt
                    )
                    active_model = AnalysisModel.OLLAMA
                    execution_tier = "local_slm"
                except Exception as slm_err:
                    logger.info(
                        f"Local SLM unavailable ({slm_err}); degrading to cloud/heuristic fallback"
                    )
                    # Circuit breaker tripped or errored: try cloud fast model if client available
                    if hasattr(self, "client"):
                        raw_res = await self._call_groq(
                            combined_prompt, user_prompt=user_prompt
                        )
                        result, cache_read_tokens, cache_creation_tokens = _extract_groq_res(raw_res)
                        active_model = AnalysisModel.GROQ
                        execution_tier = (
                            "cloud_cached"
                            if cache_read_tokens > 0
                            else "cloud_uncached"
                        )
                    else:
                        raise slm_err

            # 3. Circuit breaker OPEN or SLM disabled: route directly to cloud fast model if available
            elif hasattr(self, "client"):
                raw_res = await self._call_groq(combined_prompt, user_prompt=user_prompt)
                result, cache_read_tokens, cache_creation_tokens = _extract_groq_res(raw_res)
                active_model = AnalysisModel.GROQ
                execution_tier = (
                    "cloud_cached" if cache_read_tokens > 0 else "cloud_uncached"
                )

            else:
                raise RuntimeError(
                    "No LLM/SLM transport available; circuit breaker is OPEN"
                )

        except Exception as llm_err:
            if self.receipt_service and logical_key:
                try:
                    await self.receipt_service.record_failure(logical_key, str(llm_err))
                except Exception as rf_err:
                    logger.debug(f"Failed to record receipt failure: {rf_err}")

            logger.info(
                f"LLM primary route unavailable ({llm_err}), activating neural heuristic synthesis"
            )
            from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
                HeuristicAnalyzer,
            )

            fallback = HeuristicAnalyzer()
            return await fallback.analyze(entry)

        if not result or not isinstance(result, dict):
            if self.receipt_service and logical_key:
                try:
                    await self.receipt_service.record_failure(
                        logical_key, "Malformed or empty JSON returned by model"
                    )
                except Exception as rf_err:
                    logger.debug(f"Failed to record receipt failure: {rf_err}")

            from ai_security_monitor.infrastructure.analyzers.heuristic_analyzer import (
                HeuristicAnalyzer,
            )

            fallback = HeuristicAnalyzer()
            return await fallback.analyze(entry)

        # Successful call: record receipt with execution tier and prompt cache savings
        if self.receipt_service and logical_key:
            try:
                await self.receipt_service.record_success(
                    logical_key=logical_key,
                    response_json=result,
                    execution_tier=execution_tier,
                    cache_read_input_tokens=cache_read_tokens,
                    cache_creation_input_tokens=cache_creation_tokens,
                )
            except Exception as rs_err:
                logger.debug(f"Failed to record receipt success: {rs_err}")

        return self._build_analysis_result(entry, result, active_model)


analyzer_registry.register("ollama", LLMAnalyzer)
analyzer_registry.register("groq", LLMAnalyzer)
analyzer_registry.register("local", LLMAnalyzer)
analyzer_registry.register("local_llm", LLMAnalyzer)
analyzer_registry.register("local_slm", LLMAnalyzer)
analyzer_registry.register("tiered", LLMAnalyzer)
analyzer_registry.register("slm", LLMAnalyzer)
analyzer_registry.register("gateway", LLMAnalyzer)
analyzer_registry.register("auto/offline", LLMAnalyzer)
