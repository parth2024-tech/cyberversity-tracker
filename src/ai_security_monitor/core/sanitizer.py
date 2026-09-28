"""
AI prompt and text sanitizer inspired by Scrapling's anti-injection engine.

Neutralizes prompt injection payloads, invisible unicode characters,
control characters, and hidden HTML elements from scraped web content
before passing data to LLM analysis pipelines.
"""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup, Comment

# Regex for zero-width characters and bi-directional text overrides
# commonly used to conceal prompt injection instructions from human inspection
_ZWC_PATTERN = re.compile(
    r"[\u200b\u200c\u200d\ufeff\u2060\u180e\u200e\u200f\u202a-\u202e]"
)

# Control characters (excluding \t, \n, \r)
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Consecutive whitespace pattern
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_NEWLINES_PATTERN = re.compile(r"\n{3,}")

# Obvious adversarial prompt override prefixes
_INJECTION_TRIGGERS = [
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(all\s+)?(previous|prior|above)\s+instructions\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+in\s+developer\s+mode\b"),
    re.compile(r"(?i)\bsystem\s+prompt\s*:\s*"),
]

# Hidden CSS patterns
_HIDDEN_STYLE_PATTERN = re.compile(
    r"(?i)(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0|font-size\s*:\s*0|height\s*:\s*0px|width\s*:\s*0px)"
)


class AIPromptSanitizer:
    """Sanitizes text and HTML scraped from external feeds before LLM processing."""

    @classmethod
    def sanitize_text(cls, text: str | None, max_length: int = 8000) -> str:
        """Strip invisible characters, control chars, and defuse injection payloads in plain text."""
        if not text:
            return ""

        # Decode HTML entities if present
        cleaned = html.unescape(str(text))

        # Strip zero-width unicode characters
        cleaned = _ZWC_PATTERN.sub("", cleaned)

        # Strip low ASCII control characters
        cleaned = _CONTROL_CHARS_PATTERN.sub("", cleaned)

        # Defuse known adversarial override phrases by neutralizing them with brackets
        for trigger in _INJECTION_TRIGGERS:
            cleaned = trigger.sub(r"[DEFUSED_INJECTION_PROMPT]", cleaned)

        # Clean consecutive spaces and normalize newlines
        cleaned = _WHITESPACE_PATTERN.sub(" ", cleaned)
        cleaned = _NEWLINES_PATTERN.sub("\n\n", cleaned)
        cleaned = cleaned.strip()

        # Enforce maximum text length bounds
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "… [truncated]"

        return cleaned

    @classmethod
    def sanitize_html(cls, html_content: str | None, max_length: int = 15000) -> str:
        """Parse HTML, eliminate noise tags, hidden CSS elements, comments, and convert to clean text."""
        if not html_content:
            return ""

        try:
            soup = BeautifulSoup(str(html_content), "html.parser")

            # 1. Remove noise tags completely
            for tag in soup(
                ["script", "style", "noscript", "svg", "iframe", "template"]
            ):
                tag.decompose()

            # 2. Remove HTML comments
            for comment in soup.find_all(text=lambda t: isinstance(t, Comment)):
                comment.extract()

            # 3. Remove CSS-hidden elements and aria-hidden elements
            for tag in soup.find_all(True):
                # Check aria-hidden
                if tag.get("aria-hidden") == "true":
                    tag.decompose()
                    continue

                # Check inline style
                style_val = tag.get("style", "")
                style_str = (
                    " ".join(style_val)
                    if isinstance(style_val, list)
                    else str(style_val)
                )
                if style_str and _HIDDEN_STYLE_PATTERN.search(style_str):
                    tag.decompose()
                    continue

            # 4. Extract visible text
            extracted = soup.get_text(separator=" ", strip=True)
            return cls.sanitize_text(extracted, max_length=max_length)

        except Exception:
            # Fallback to pure text sanitization if HTML parsing fails
            return cls.sanitize_text(html_content, max_length=max_length)


# Global singleton instance
sanitizer = AIPromptSanitizer()
