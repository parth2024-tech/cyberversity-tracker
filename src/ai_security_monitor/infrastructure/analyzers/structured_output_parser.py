"""
Resilient JSON and Structured Output Parser for Small Language Models (SLMs).
Handles markdown code blocks, conversational commentary, balanced bracket extraction,
trailing commas, and Pydantic/dataclass normalization for local 3B-8B models.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


def clean_markdown_fences(text: str) -> str:
    """Strip markdown code fence blocks like ```json ... ``` or ``` ... ```."""
    if not text:
        return ""
    # Strip backticks surrounding json
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


def remove_trailing_commas(json_str: str) -> str:
    """Remove invalid trailing commas before closing braces/brackets (common SLM bug)."""
    # Remove commas immediately preceding } or ]
    return re.sub(r",\s*([\]}])", r"\1", json_str)


def extract_balanced_json_object(text: str) -> str | None:
    """Scan string for the outermost balanced curly braces {...}."""
    start_idx = text.find("{")
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start_idx, len(text)):
        char = text[i]

        if char == '"' and not escape:
            in_string = not in_string
        elif char == "\\" and not escape:
            escape = True
            continue

        escape = False

        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start_idx : i + 1]

    return None


def parse_slm_json(raw_text: str) -> dict[str, Any] | None:
    """Multi-stage resilient JSON extraction for small language model outputs.

    Stages:
    1. Direct json.loads (clean output).
    2. Markdown codeblock stripping.
    3. Balanced curly brace extraction.
    4. Trailing comma cleanup.
    5. Single-quote replacement.
    """
    if not raw_text or not raw_text.strip():
        return None

    cleaned = raw_text.strip()

    # Stage 1: Direct JSON load
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Stage 2: Clean codeblocks
    fenceless = clean_markdown_fences(cleaned)
    try:
        data = json.loads(fenceless)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Stage 3: Balanced curly brace search
    extracted = extract_balanced_json_object(fenceless) or extract_balanced_json_object(
        cleaned
    )
    if extracted:
        # Try direct
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # Stage 4: Trailing comma repair
        repaired = remove_trailing_commas(extracted)
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # Stage 5: Single-quote repair for keys/values
        try:
            # Replace single quotes around word-like tokens with double quotes
            sq_repaired = re.sub(
                r"(?<=[{\s,])'([a-zA-Z0-9_]+)'(?=\s*:)", r'"\1"', repaired
            )
            sq_repaired = re.sub(r":\s*'([^']*)'", r': "\1"', sq_repaired)
            data = json.loads(sq_repaired)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def normalize_slm_analysis_payload(
    payload: dict[str, Any] | None,
    default_title: str = "",
) -> dict[str, Any]:
    """Validate, sanitize, and bound analysis fields from local models."""
    if not payload or not isinstance(payload, dict):
        return {
            "attack_vector": "Ecosystem Innovation",
            "risk_assessment": f"Advancement noted in {default_title[:60]}",
            "mitigation": "Assess integration and runtime suitability",
            "threat_velocity": 70,
            "severity_index": 70,
            "blast_radius_score": 60,
            "affected_ecosystem": ["AI Ecosystem"],
            "attack_archetype": "Ecosystem Library",
            "weaponization_potential": "Production Ready",
            "is_pre_cve_warning": False,
        }

    # Bounded numerical scores
    def _clamp_score(
        val: Any, default: int, min_val: int = 1, max_val: int = 100
    ) -> int:
        try:
            num = int(float(val))
            return max(min_val, min(max_val, num))
        except (ValueError, TypeError):
            return default

    threat_velocity = _clamp_score(payload.get("threat_velocity"), 70)
    severity_index = _clamp_score(payload.get("severity_index"), 70)
    blast_radius_score = _clamp_score(payload.get("blast_radius_score"), 60, min_val=0)

    # String sanitization
    attack_vector = str(payload.get("attack_vector") or "Ecosystem Innovation").strip()
    risk_assessment = str(
        payload.get("risk_assessment") or f"Advancement in {default_title[:60]}"
    ).strip()
    mitigation = str(
        payload.get("mitigation") or "Assess integration with local runtime"
    ).strip()

    # Ecosystem list
    eco = payload.get("affected_ecosystem", ["AI Ecosystem"])
    if isinstance(eco, str):
        eco = [e.strip() for e in eco.split(",") if e.strip()]
    elif not isinstance(eco, list):
        eco = ["AI Ecosystem"]

    archetype = str(
        payload.get("attack_archetype") or "Frontier Foundation Model"
    ).strip()
    weaponization = str(
        payload.get("weaponization_potential") or "Production Ready"
    ).strip()

    return {
        "attack_vector": attack_vector,
        "risk_assessment": risk_assessment,
        "mitigation": mitigation,
        "threat_velocity": threat_velocity,
        "severity_index": severity_index,
        "blast_radius_score": blast_radius_score,
        "affected_ecosystem": eco,
        "attack_archetype": archetype,
        "weaponization_potential": weaponization,
        "is_pre_cve_warning": bool(payload.get("is_pre_cve_warning", False)),
    }
