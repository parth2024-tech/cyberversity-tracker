"""
Deduplication and Normalization Service.
Provides cross-source URL canonicalization, title tokenization,
fingerprinting, and Story/Cluster aggregation over a rolling 14-day window.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import UUID

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, Story

logger = get_logger(__name__)

# Query parameters commonly used for tracking that should be stripped
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "fbclid",
    "gclid",
    "feature",
    "s",
    "t",
}

# Prefix patterns to strip from titles
TITLE_PREFIX_REGEX = re.compile(
    r"^(\[[^\]]+\]|\([^\)]+\)|show\s+hn:\s*|ask\s+hn:\s*|tell\s+hn:\s*|announcing:\s*|release:\s*)",
    re.IGNORECASE,
)

# Common filler words to ignore in similarity matching
STOP_WORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "for", "with", "by", "of",
    "to", "from", "is", "are", "was", "were", "new", "released", "announces",
    "announcing", "introduces", "introducing", "update", "v1", "v2", "v3",
}


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL to collapse cross-source variations into a single canonical target.

    Examples:
    - https://arxiv.org/pdf/2401.12345.pdf -> https://arxiv.org/abs/2401.12345
    - https://github.com/vllm-project/vllm/releases/tag/v0.6.0 -> https://github.com/vllm-project/vllm
    - https://example.com/post?utm_source=twitter&id=1 -> https://example.com/post?id=1
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        # 1. Normalize arXiv URLs to standard abstract view
        if "arxiv.org" in netloc:
            match = re.search(r"/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:\.pdf)?", path)
            if match:
                arxiv_id = match.group(1)
                return f"https://arxiv.org/abs/{arxiv_id}"

        # 2. Normalize GitHub repo URLs to root project slug
        if "github.com" in netloc:
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
                # Strip .git suffix if present
                if repo.endswith(".git"):
                    repo = repo[:-4]
                return f"https://github.com/{owner}/{repo}"

        # 3. Strip tracking parameters from query string
        filtered_query = []
        if parsed.query:
            query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
            filtered_query = [
                (k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS
            ]

        new_query = urlencode(filtered_query)
        # Reconstruct without anchor fragments or tracking query
        canonical = urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path or "/",
            "",
            new_query,
            "",
        ))
        return canonical
    except Exception as e:
        logger.debug(f"Error canonicalizing URL '{url}': {e}")
        return url.strip()


def normalize_title(title: str) -> str:
    """Normalize title for semantic token matching and near-duplicate detection."""
    if not title:
        return ""

    # Remove prefixes like [R], [D], Show HN:, Announcing:
    t = TITLE_PREFIX_REGEX.sub("", title.strip())
    # Lowercase and replace non-alphanumeric with spaces
    t = re.sub(r"[^\w\s-]", " ", t.lower())
    # Collapse multiple whitespaces
    return " ".join(t.split())


def extract_title_tokens(title: str) -> set[str]:
    """Extract significant lowercase tokens from a title, filtering stop words."""
    norm = normalize_title(title)
    tokens = set()
    for word in norm.split():
        clean = word.strip("-")
        if len(clean) > 1 and clean not in STOP_WORDS:
            tokens.add(clean)
    return tokens


def compute_title_similarity(title_a: str, title_b: str) -> float:
    """Compute token Jaccard similarity between two titles (0.0 to 1.0)."""
    tokens_a = extract_title_tokens(title_a)
    tokens_b = extract_title_tokens(title_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def compute_fingerprint(canonical_url: str, title: str) -> str:
    """Compute deterministic SHA-256 fingerprint from canonical URL and normalized title tokens."""
    tokens = sorted(extract_title_tokens(title))
    token_str = " ".join(tokens)
    payload = f"{canonical_url}|{token_str}".encode()
    return hashlib.sha256(payload).hexdigest()


class DeduplicationService:
    """Cross-source deduplication, fingerprinting, and Story clustering engine.
    Maintains a rolling window of recent stories (up to 14 days) to cluster
    corroborating entries arriving from different feeds.
    """

    def __init__(self, max_window_days: int = 14, similarity_threshold: float = 0.60):
        self.max_window_days = max_window_days
        self.similarity_threshold = similarity_threshold
        # In-memory index of active stories: story_id -> Story
        self._stories: dict[UUID, Story] = {}
        # Fast lookup indices
        self._fingerprint_to_story: dict[str, UUID] = {}
        self._canonical_url_to_story: dict[str, UUID] = {}

    def _evict_stale_stories(self) -> None:
        """Evict stories older than max_window_days (14-day freshness guard)."""
        cutoff = datetime.now(UTC) - timedelta(days=self.max_window_days)
        stale_ids = [
            sid
            for sid, s in self._stories.items()
            if s.last_seen_at < cutoff
        ]
        for sid in stale_ids:
            story = self._stories.pop(sid, None)
            if story:
                self._fingerprint_to_story.pop(story.fingerprint, None)
                if story.canonical_url:
                    self._canonical_url_to_story.pop(story.canonical_url, None)

    def find_matching_story(self, entry: Entry) -> Story | None:
        """Find an existing Story matching the candidate entry within the active window."""
        self._evict_stale_stories()

        canon_url = canonicalize_url(entry.url)
        # 1. Exact canonical URL match (e.g. same GitHub repo or arXiv paper across sources)
        if canon_url and canon_url in self._canonical_url_to_story:
            story_id = self._canonical_url_to_story[canon_url]
            if story_id in self._stories:
                return self._stories[story_id]

        # 2. Exact fingerprint match
        fp = compute_fingerprint(canon_url, entry.title)
        if fp in self._fingerprint_to_story:
            story_id = self._fingerprint_to_story[fp]
            if story_id in self._stories:
                return self._stories[story_id]

        # 3. Near-duplicate fuzzy title match within the same or complementary category
        for story in self._stories.values():
            # Only compare within 14-day window
            similarity = compute_title_similarity(entry.title, story.title)
            if similarity >= self.similarity_threshold:
                return story

        return None

    def process_candidate(
        self, entry: Entry, source_name: str | None = None
    ) -> tuple[Entry, Story, bool]:
        """Process an ingested entry through the deduplication & clustering engine.

        Returns:
            tuple[Entry, Story, bool]:
                - entry: with normalized url and story_id assigned
                - story: the Story aggregate (existing or newly created)
                - is_new_story: True if a new cluster was created, False if merged
        """
        canon_url = canonicalize_url(entry.url)
        entry.url = canon_url
        fp = compute_fingerprint(canon_url, entry.title)

        existing_story = self.find_matching_story(entry)
        if existing_story:
            # Corroborate existing story
            existing_story.add_entry(entry, source_name=source_name)
            entry.story_id = existing_story.id
            logger.info(
                f"Merged entry '{entry.title[:40]}...' into Story '{existing_story.title[:40]}...' "
                f"(sources: {existing_story.source_count}, confidence: {existing_story.confidence_score:.2f})"
            )
            return entry, existing_story, False

        # Create new story aggregate
        new_story = Story(
            title=entry.title,
            canonical_url=canon_url,
            fingerprint=fp,
            category=entry.category,
            summary=entry.summary,
            source_count=1,
            confidence_score=0.60,
            entry_ids=[entry.id],
            sources=[source_name] if source_name else [],
            tags=list(entry.tags),
            metadata={"initial_category": entry.category.value if hasattr(entry.category, "value") else str(entry.category)},
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        entry.story_id = new_story.id

        # Index new story
        self._stories[new_story.id] = new_story
        self._fingerprint_to_story[fp] = new_story.id
        if canon_url:
            self._canonical_url_to_story[canon_url] = new_story.id

        return entry, new_story, True

    def get_story(self, story_id: UUID) -> Story | None:
        """Retrieve story by ID."""
        return self._stories.get(story_id)

    def list_active_stories(self, min_sources: int = 1) -> list[Story]:
        """List active stories within the 14-day window, sorted by confidence then last seen."""
        self._evict_stale_stories()
        stories = [s for s in self._stories.values() if s.source_count >= min_sources]
        stories.sort(key=lambda s: (s.confidence_score, s.last_seen_at), reverse=True)
        return stories


# Global singleton deduplicator
deduplication_service = DeduplicationService()
