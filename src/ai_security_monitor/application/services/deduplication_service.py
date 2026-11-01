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
from ai_security_monitor.domain.entities import Entry, Story
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service,
)

logger = get_logger(__name__)

# Query parameters commonly used for tracking that should be stripped
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "fbclid",
    "gclid",
    "mc_eid",
    "msclkid",
    "twclid",
    "igshid",
    "yclid",
    "spm",
    "_ga",
    "_gl",
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
    "a",
    "an",
    "the",
    "and",
    "or",
    "in",
    "on",
    "at",
    "for",
    "with",
    "by",
    "of",
    "to",
    "from",
    "is",
    "are",
    "was",
    "were",
    "new",
    "released",
    "announces",
    "announcing",
    "introduces",
    "introducing",
    "update",
    "v1",
    "v2",
    "v3",
}


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL to collapse cross-source variations into a single canonical target.

    Features:
    - Normalizes schemeless URLs (e.g. example.com/path -> https://example.com/path)
    - Strips embedded basic auth credentials (user:pass@) to prevent credential leakage
    - Strips marketing/tracking query parameters (utm_*, fbclid, gclid, mc_eid, spm, _ga, etc.)
    - Removes default ports (:80, :443) and lowercases domain names
    - Strips anchor fragments and redundant trailing slashes
    - Normalizes arXiv URLs (pdf/abs) to standard abstract landing page
    - Normalizes GitHub repository URLs to root project slug
    """
    if not url:
        return ""

    try:
        raw = url.strip()
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw.lstrip("/")

        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        port_suffix = (
            f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        )
        netloc = hostname + port_suffix

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
                (k, v)
                for k, v in query_pairs
                if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
            ]
            filtered_query.sort()

        new_query = urlencode(filtered_query)
        # Reconstruct without anchor fragments, credentials, or tracking query
        canonical = urlunparse(
            (
                parsed.scheme.lower() or "https",
                netloc,
                path or "/",
                "",
                new_query,
                "",
            )
        )
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
    """Extract significant lowercase tokens from a title, filtering stop words.
    Integrates Chinese bi-gram segmentation when Chinese ideograms are present.
    """
    if not title:
        return set()
    if re.search(r"[\u4e00-\u9fa5]", title):
        from ai_security_monitor.application.services.china_dedup_service import (
            ChinaDeduplicationService,
        )

        return ChinaDeduplicationService.extract_fingerprint(title)

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


# ── Dual-Tier Deduplication: SimHash (64-bit) & MinHash (64-Permutation) ─────────

MERSENNE_PRIME = (1 << 61) - 1
# Deterministic constants for 64 linear congruential hash permutations
_MINHASH_A = [((i * 1000003 + 3) % (MERSENNE_PRIME - 1)) + 1 for i in range(64)]
_MINHASH_B = [((i * 2000003 + 7) % (MERSENNE_PRIME - 1)) + 1 for i in range(64)]


def compute_simhash64(text: str) -> int:
    """Compute deterministic 64-bit SimHash for full-text / summary near-duplicate comparison.

    Tokenizes text into words, computes MD5-based 64-bit hashes, accumulates sign weights,
    and returns a 64-bit bitmask integer. Integrates Chinese SimHash when ideograms are present.
    """
    if not text:
        return 0
    if re.search(r"[\u4e00-\u9fa5]", text):
        from ai_security_monitor.application.services.china_dedup_service import (
            ChinaDeduplicationService,
        )

        return ChinaDeduplicationService.compute_simhash(text)

    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return 0
    v = [0] * 64
    for w in words:
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:8], "big")
        for i in range(64):
            if (h >> i) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def simhash_hamming_distance(h1: int, h2: int) -> int:
    """Calculate bitwise Hamming distance between two 64-bit SimHash values."""
    return bin(h1 ^ h2).count("1")


def compute_minhash64(tokens: set[str]) -> list[int]:
    """Compute 64-permutation MinHash signature for a token set using Carter-Wegman hashing."""
    if not tokens:
        return [0] * 64
    token_hashes = [
        int.from_bytes(hashlib.md5(t.encode()).digest()[:8], "big") for t in tokens
    ]
    signature: list[int] = []
    for a, b in zip(_MINHASH_A, _MINHASH_B, strict=True):
        min_val = min((a * th + b) % MERSENNE_PRIME for th in token_hashes)
        signature.append(min_val)
    return signature


def minhash_jaccard_similarity(sig1: list[int], sig2: list[int]) -> float:
    """Estimate Jaccard similarity between two 64-permutation MinHash signatures."""
    if not sig1 or not sig2 or len(sig1) != len(sig2):
        return 0.0
    if not any(sig1) or not any(sig2):
        return 0.0
    matches = sum(1 for x, y in zip(sig1, sig2, strict=True) if x == y)
    return matches / len(sig1)


class DeduplicationService:
    """Cross-source deduplication, fingerprinting, and Story clustering engine.
    Maintains a rolling window of recent stories (up to 14 days) to cluster
    corroborating entries arriving from different feeds.
    Incorporates 64-bit SimHash and 64-permutation MinHash dual-tier indexing.
    """

    def __init__(
        self,
        max_window_days: int = 14,
        similarity_threshold: float = 0.60,
        minhash_threshold: float = 0.35,
        simhash_hamming_threshold: int = 4,
        semantic_threshold: float = 0.82,
        max_stories: int = 1000,
    ):
        self.max_window_days = max_window_days
        self.similarity_threshold = similarity_threshold
        self.minhash_threshold = minhash_threshold
        self.simhash_hamming_threshold = simhash_hamming_threshold
        self.semantic_threshold = semantic_threshold
        self.max_stories = max_stories

        # In-memory index of active stories: story_id -> Story
        self._stories: dict[UUID, Story] = {}
        # Fast lookup indices
        self._fingerprint_to_story: dict[str, UUID] = {}
        self._canonical_url_to_story: dict[str, UUID] = {}
        # Dual-tier signatures
        self._story_simhashes: dict[UUID, int] = {}
        self._story_minhashes: dict[UUID, list[int]] = {}
        # Semantic vector memory (Pillar 1)
        self._story_embeddings: dict[UUID, list[float]] = {}

    def _evict_stale_stories(self) -> None:
        """Evict stories older than max_window_days or exceeding max_stories memory capacity."""
        cutoff = datetime.now(UTC) - timedelta(days=self.max_window_days)
        stale_ids = [sid for sid, s in self._stories.items() if s.last_seen_at < cutoff]
        for sid in stale_ids:
            story = self._stories.pop(sid, None)
            if story:
                self._fingerprint_to_story.pop(story.fingerprint, None)
                if story.canonical_url:
                    self._canonical_url_to_story.pop(story.canonical_url, None)
                self._story_simhashes.pop(sid, None)
                self._story_minhashes.pop(sid, None)
                self._story_embeddings.pop(sid, None)

        # Capacity guard: prune oldest stories if exceeding max_stories budget
        if len(self._stories) > self.max_stories:
            excess = len(self._stories) - self.max_stories
            sorted_by_age = sorted(
                self._stories.items(), key=lambda item: item[1].last_seen_at
            )
            for sid, story in sorted_by_age[:excess]:
                self._stories.pop(sid, None)
                self._fingerprint_to_story.pop(story.fingerprint, None)
                if story.canonical_url:
                    self._canonical_url_to_story.pop(story.canonical_url, None)
                self._story_simhashes.pop(sid, None)
                self._story_minhashes.pop(sid, None)
                self._story_embeddings.pop(sid, None)

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

        # 3. Dual-Tier Deduplication:
        # Tier 1: 64-bit SimHash Hamming distance on substantive full-text / summary
        entry_text = f"{entry.title} {entry.summary}".strip()
        entry_words = entry_text.split()
        entry_simhash = compute_simhash64(entry_text) if len(entry_words) >= 8 else 0

        # Tier 2: 64-Permutation MinHash on title tokens
        entry_tokens = extract_title_tokens(entry.title)
        entry_minhash = compute_minhash64(entry_tokens) if entry_tokens else []

        for story_id, story in self._stories.items():
            # Check SimHash Hamming distance (<= 4 bits indicates near-duplicate full-text)
            if entry_simhash:
                story_sh = self._story_simhashes.get(story_id, 0)
                if (
                    story_sh
                    and simhash_hamming_distance(entry_simhash, story_sh)
                    <= self.simhash_hamming_threshold
                ):
                    return story

            # Check 64-Permutation MinHash Jaccard (>= 0.35 flags syndicated wire rewrites)
            if entry_minhash:
                story_mh = self._story_minhashes.get(story_id)
                if story_mh:
                    est_jaccard = minhash_jaccard_similarity(entry_minhash, story_mh)
                    if est_jaccard >= self.minhash_threshold:
                        return story

            # Baseline token Jaccard fallback
            similarity = compute_title_similarity(entry.title, story.title)
            if similarity >= self.similarity_threshold:
                return story

        # 4. Semantic Vector Memory (Pillar 1):
        # Cross-platform concept deduplication (e.g. arXiv paper + HN discussion + Reddit release)
        entry_text = f"{entry.title} {entry.summary}".strip()
        if entry_text and self._story_embeddings:
            entry_vec = embedding_service.embed_text(entry_text)
            for story_id, story_vec in self._story_embeddings.items():
                sim = embedding_service.cosine_similarity(entry_vec, story_vec)
                if sim >= self.semantic_threshold:
                    matched = self._stories.get(story_id)
                    if matched:
                        logger.info(
                            f"Semantic vector deduplication match (cosine sim: {sim:.3f} >= {self.semantic_threshold}): "
                            f"'{entry.title[:35]}...' -> '{matched.title[:35]}...'"
                        )
                        return matched

        return None

    def find_semantic_duplicate(
        self, entry: Entry, threshold: float | None = None
    ) -> Story | None:
        """Find an existing Story matching entry purely via semantic vector similarity."""
        cutoff_thresh = threshold if threshold is not None else self.semantic_threshold
        entry_text = f"{entry.title} {entry.summary}".strip()
        if not entry_text or not self._story_embeddings:
            return None
        entry_vec = embedding_service.embed_text(entry_text)
        for story_id, story_vec in self._story_embeddings.items():
            sim = embedding_service.cosine_similarity(entry_vec, story_vec)
            if sim >= cutoff_thresh:
                return self._stories.get(story_id)
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
            entry.metadata = dict(entry.metadata or {})
            entry.metadata["heat_score"] = existing_story.heat_score
            entry.metadata["heat_badge"] = existing_story.heat_badge
            logger.info(
                f"Merged entry '{entry.title[:40]}...' into Story '{existing_story.title[:40]}...' "
                f"(sources: {existing_story.source_count}, confidence: {existing_story.confidence_score:.2f}, heat: {existing_story.heat_score}, badge: {existing_story.heat_badge})"
            )
            return entry, existing_story, False

        # Create new story aggregate
        entry_ts = entry.published_at or entry.created_at or datetime.now(UTC)
        new_story = Story(
            title=entry.title,
            canonical_url=canon_url,
            fingerprint=fp,
            category=entry.category,
            summary=entry.summary,
            source_count=1,
            confidence_score=0.50,
            entry_ids=[entry.id],
            sources=[source_name] if source_name else [],
            tags=list(entry.tags),
            participant_timestamps=[entry_ts],
            metadata={
                "initial_category": entry.category.value
                if hasattr(entry.category, "value")
                else str(entry.category)
            },
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        new_story.calculate_heat()
        new_story.update_badge()
        entry.story_id = new_story.id
        entry.metadata = dict(entry.metadata or {})
        entry.metadata["heat_score"] = new_story.heat_score
        entry.metadata["heat_badge"] = new_story.heat_badge

        # Index new story
        self._stories[new_story.id] = new_story
        self._fingerprint_to_story[fp] = new_story.id
        if canon_url:
            self._canonical_url_to_story[canon_url] = new_story.id

        # Register Dual-Tier Signatures
        story_text = f"{new_story.title} {new_story.summary}".strip()
        self._story_simhashes[new_story.id] = compute_simhash64(story_text)
        self._story_minhashes[new_story.id] = compute_minhash64(
            extract_title_tokens(new_story.title)
        )
        # Register Semantic Vector Memory (Pillar 1)
        self._story_embeddings[new_story.id] = embedding_service.embed_text(story_text)

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
