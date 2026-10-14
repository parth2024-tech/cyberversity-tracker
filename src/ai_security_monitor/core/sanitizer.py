"""
AI prompt, text, and privacy sanitizer inspired by Scrapling's anti-injection engine and privacy standards.

Neutralizes prompt injection payloads, invisible unicode characters,
control characters, hidden HTML elements, tracking pixels, and conversational AI slop
before passing data to LLM analysis pipelines, publication feeds, or UI clients.
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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

# Tracking query parameters to strip from incoming feed URLs and links
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "twclid",
    "igshid",
    "srsltid",
    "si",
    "ref",
    "referrer",
    "source",
    "campaign_id",
    "campaign",
    "affiliate_id",
    "affiliate",
    "click_id",
    "clickid",
    "irclickid",
    "_ga",
    "_gid",
    "mc_cid",
    "mc_eid",
    "ncid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
}

# Conversational AI introductory patterns to strip (Anti-AI-Slop Law)
_INTRO_PATTERNS = [
    re.compile(
        r"(?i)^here'?s?\s+(a\s+)?(?:20-?word\s+)?(?:concise\s+)?(?:(?:technical|business|casual|detailed|brief)\s+)?summary[:\s]*"
    ),
    re.compile(
        r"(?i)^this\s+(?:is\s+)?(?:a\s+)?(?:20-?word\s+)?(?:concise\s+)?(?:(?:technical|business|casual|detailed|brief)\s+)?summary[:\s]*"
    ),
    re.compile(
        r"(?i)^here\s+is\s+(?:a\s+)?(?:20-?word\s+)?(?:concise\s+)?(?:(?:technical|business|casual|detailed|brief)\s+)?summary[:\s]*"
    ),
    re.compile(
        r"(?i)^(?:concise\s+)?(?:(?:technical|business|casual|detailed|brief)\s+)?summary[:\s]*"
    ),
    re.compile(
        r"(?i)^in\s+(?:exactly\s+)?(?:20\s+words\s+or\s+less[:\s]*|summary[:\s]*)"
    ),
    re.compile(
        r"(?i)^this\s+(?:article|paper|repository|release)\s+(?:provides|offers|presents|discusses|explains|describes|covers)[:\s]*"
    ),
    re.compile(
        r"(?i)^the\s+(?:article|paper|repository|release)\s+(?:discusses|explains|describes|presents|covers)[:\s]*"
    ),
    re.compile(r"(?i)^sure,?\s+(?:here\s+is|here's)(?:\s+a|\s+the)?[:\s]*"),
    re.compile(r"(?i)^certainly,?\s+(?:here\s+is|here's)(?:\s+a|\s+the)?[:\s]*"),
    re.compile(r"(?i)^in\s+(?:this\s+)?summary[:\s,]*"),
    re.compile(r"(?i)^the\s+summary\s+(?:below|above|follows)[:\s]*"),
]


class AIPromptSanitizer:
    """Sanitizes text, HTML, and URLs scraped from external feeds before LLM processing and display."""

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
    def strip_introductory_phrases(cls, text: str | None) -> str:
        """Strip chatty conversational AI introductions, slop preambles, and surrounding quotes."""
        if not text:
            return ""

        cleaned = str(text).strip()

        # Run multi-pass loop to clean nested or chained preambles
        changed = True
        iterations = 0
        while changed and iterations < 5:
            changed = False
            iterations += 1
            for pattern in _INTRO_PATTERNS:
                new_text = pattern.sub("", cleaned).strip()
                if new_text != cleaned:
                    cleaned = new_text
                    changed = True

            # Remove continuation punctuation
            new_text = re.sub(r"^[:,\s]+", "", cleaned).strip()
            if new_text != cleaned:
                cleaned = new_text
                changed = True

        # Remove enclosing quotes if the entire summary is wrapped
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (
            cleaned.startswith("'") and cleaned.endswith("'")
        ):
            cleaned = cleaned[1:-1].strip()

        return cleaned

    @classmethod
    def strip_tracking_parameters(cls, url: str | None) -> str:
        """Strip marketing telemetry and analytics tracking query parameters from URLs."""
        if not url:
            return ""

        url_str = str(url).strip()
        try:
            parsed = urlparse(url_str)
            if not parsed.scheme or not parsed.netloc:
                return url_str

            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            filtered_query = [
                (k, v) for k, v in query_items if k.lower() not in _TRACKING_PARAMS
            ]

            new_query = urlencode(filtered_query)
            return urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )
        except Exception:
            return url_str

    @classmethod
    def convert_youtube_nocookie(cls, url: str | None) -> str:
        """Convert standard YouTube watch/short URLs to privacy-friendly youtube-nocookie.com embed format."""
        if not url:
            return ""

        url_str = str(url).strip()
        try:
            parsed = urlparse(url_str)
            netloc = parsed.netloc.lower()

            video_id: str | None = None
            if "youtube.com" in netloc:
                if parsed.path == "/watch":
                    q = dict(parse_qsl(parsed.query))
                    video_id = q.get("v")
                elif parsed.path.startswith("/shorts/"):
                    video_id = parsed.path.split("/")[2]
                elif parsed.path.startswith("/embed/"):
                    video_id = parsed.path.split("/")[2]
            elif "youtu.be" in netloc:
                video_id = parsed.path.lstrip("/").split("?")[0]

            if video_id:
                return f"https://www.youtube-nocookie.com/embed/{video_id}"
            return url_str
        except Exception:
            return url_str

    @classmethod
    def clean_url(cls, url: str | None) -> str:
        """Combined URL sanitation: removes tracking parameters and privacy-hardens video links."""
        if not url:
            return ""
        cleaned = cls.strip_tracking_parameters(url)
        if "youtube.com" in cleaned or "youtu.be" in cleaned:
            return cls.convert_youtube_nocookie(cleaned)
        return cleaned

    @classmethod
    def sanitize_html(cls, html_content: str | None, max_length: int = 15000) -> str:
        """Parse HTML, eliminate noise tags, tracking pixels, hidden CSS elements, comments, and convert to clean text."""
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

            # 3. Remove tracking pixels and beacon images
            for img in soup.find_all("img"):
                raw_src = img.get("src")
                src = (
                    str(raw_src[0])
                    if isinstance(raw_src, list)
                    else str(raw_src or "")
                ).lower()
                width = str(img.get("width") or "")
                height = str(img.get("height") or "")

                is_tracking_pixel = (
                    (width in ("1", "0") and height in ("1", "0"))
                    or (
                        width.isdigit()
                        and int(width) <= 3
                        and height.isdigit()
                        and int(height) <= 3
                    )
                    or any(
                        p in src
                        for p in (
                            "tracking",
                            "analytics",
                            "doubleclick",
                            "beacon",
                            "facebook.com/tr",
                            "/px",
                        )
                    )
                    or (src.startswith("data:") and len(src) < 100)
                )
                if is_tracking_pixel:
                    img.decompose()

            # 4. Remove CSS-hidden elements and aria-hidden elements
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

            # 5. Extract visible text
            extracted = soup.get_text(separator=" ", strip=True)
            return cls.sanitize_text(extracted, max_length=max_length)

        except Exception:
            # Fallback to pure text sanitization if HTML parsing fails
            return cls.sanitize_text(html_content, max_length=max_length)


# Global singleton instance
sanitizer = AIPromptSanitizer()
