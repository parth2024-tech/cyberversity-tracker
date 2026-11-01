"""
China Intelligence Token Shield & Deterministic Verification Protocol.

Protects technical entities, model identifiers, CVE tags, parameter counts,
and code repository paths from corruption during machine translation,
and deterministically verifies placeholder survival.
"""

from __future__ import annotations

import re
from typing import ClassVar


class ChinaTokenShield:
    """Invariant placeholder protection and deterministic verifier for technical translation."""

    PATTERNS: ClassVar[list[tuple[str, re.Pattern[str]]]] = [
        (
            "VULN_ID",
            re.compile(
                r"(?<![a-zA-Z0-9])(?:CVE-\d{4}-\d{4,}|CNVD-\d{4}-\d{4,}|CNVD-C-\d{4}-\d{4,}|CNNVD-\d{4,}-\d{3,})(?![a-zA-Z0-9])",
                re.IGNORECASE,
            ),
        ),
        (
            "SEC_TAG",
            re.compile(
                r"(?<![a-zA-Z0-9])(?:POC|EXP|RCE|0-day|1-day|0day|1day)(?![a-zA-Z0-9])",
                re.IGNORECASE,
            ),
        ),
        (
            "REPO",
            re.compile(
                r"(?<![a-zA-Z0-9_])[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\.\-]+(?:\.git)?(?![a-zA-Z0-9_])"
            ),
        ),
        (
            "MODEL",
            re.compile(
                r"(?<![a-zA-Z0-9])(?:DeepSeek|Qwen|InternLM|InternVL|GLM|ChatGLM|CogVideo|Kimi|Baichuan|"
                r"Yi|MiniCPM|Step|Aquila|TeleChat|Skywork|Hunyuan|SenseChat|"
                r"PaddlePaddle|Paddle|MindSpore|Ascend|XiangShan|YOLOX|MMDetection|"
                r"Agibot|Unitree|FunAudioLLM|ChatTTS|FishAudio|"
                r"LMDeploy|vLLM|SGLang|ModelScope)[a-zA-Z0-9_\.\-]*(?![a-zA-Z0-9])",
                re.IGNORECASE,
            ),
        ),
        (
            "PARAM",
            re.compile(
                r"(?<![a-zA-Z0-9])\d+(?:\.\d+)?(?:B|M|K)(?![a-zA-Z0-9])", re.IGNORECASE
            ),
        ),
        (
            "VER",
            re.compile(
                r"(?<![a-zA-Z0-9])v\d+(?:\.\d+)*(?:-[a-zA-Z0-9\.]+)?(?![a-zA-Z0-9])",
                re.IGNORECASE,
            ),
        ),
    ]

    def shield(self, text: str) -> tuple[str, dict[str, str]]:
        """
        Replace sensitive technical tokens with deterministic placeholders.

        Returns:
            Tuple of (shielded_text, mapping_dict) where mapping_dict maps
            placeholder -> original_token.
        """
        if not text:
            return "", {}

        mapping: dict[str, str] = {}
        counter = 1
        shielded = text

        for tag, pattern in self.PATTERNS:
            # Find all unique matches in order of appearance
            matches = list(pattern.finditer(shielded))
            for match in matches:
                original = match.group(0)
                # Skip if already a placeholder
                if original.startswith("⟦") and original.endswith("⟧"):
                    continue

                placeholder = f"⟦{tag}_{counter:02d}⟧"
                mapping[placeholder] = original
                shielded = shielded.replace(original, placeholder, 1)
                counter += 1

        return shielded, mapping

    def unshield(self, text: str, mapping: dict[str, str]) -> str:
        """Restore deterministic placeholders back to their original values."""
        if not text or not mapping:
            return text

        restored = text
        for placeholder, original in mapping.items():
            restored = restored.replace(placeholder, original)
            tag_num = placeholder.strip("⟦⟧")
            spaced_pattern = re.compile(
                rf"⟦[^⟧]*?{re.escape(tag_num)}[^⟧]*?⟧", re.IGNORECASE
            )
            restored = spaced_pattern.sub(original, restored)
        # Clean any remaining orphaned bracket tokens
        restored = re.sub(r"⟦[^⟧]*?⟧", "", restored)
        return restored

    def verify(self, text: str, mapping: dict[str, str]) -> tuple[bool, list[str]]:
        """
        Deterministically verify that 100% of shielded placeholders survived translation.

        Returns:
            Tuple of (is_valid, missing_placeholders_list).
        """
        if not mapping:
            return True, []

        missing = [ph for ph in mapping if ph not in text]
        return len(missing) == 0, missing


# Global singleton instance
token_shield = ChinaTokenShield()
china_token_shield = token_shield
