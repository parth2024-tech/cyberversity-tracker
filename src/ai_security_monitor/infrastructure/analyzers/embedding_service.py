"""
Local Embedding Service for Vector Memory and Deduplication.
Uses FastEmbed (ONNX Runtime) with 'BAAI/bge-small-en-v1.5' (384-d)
with lazy initialization and robust fallback for test/offline environments.
Zero-daemon, purely in-process execution.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"
VECTOR_DIMENSION = 384


class EmbeddingService:
    """Zero-daemon in-process text embedding generator."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        dimension: int = VECTOR_DIMENSION,
        use_fallback_only: bool = False,
    ):
        self.model_name = model_name
        self.dimension = dimension
        self.use_fallback_only = use_fallback_only
        self._model: Any = None
        self._initialized = False

    def _get_model(self) -> Any:
        if self.use_fallback_only:
            return None
        if not self._initialized:
            self._initialized = True
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model_name)
                logger.info(f"Loaded local FastEmbed model: {self.model_name}")
            except Exception as e:
                logger.warning(
                    f"FastEmbed model '{self.model_name}' could not be loaded: {e}. "
                    "Operating with deterministic pseudo-vector fallback."
                )
                self._model = None
        return self._model

    def _pseudo_vector(self, text: str) -> list[float]:
        """Deterministic 384-d pseudo-vector fallback from text tokens.
        Preserves cosine similarity properties for identical or near-identical texts
        without requiring internet or heavy runtime in unit tests.
        """
        if not text:
            return [0.0] * self.dimension

        words = re.findall(r"\b\w+\b", text.lower())
        vec = [0.0] * self.dimension
        if not words:
            return vec

        for word in words:
            # Deterministic hash seed
            h = hashlib.sha256(word.encode()).digest()
            # Distribute weights across dimension bins
            for i in range(min(16, len(h))):
                idx = (h[i] + i * 23) % self.dimension
                val = (h[(i + 1) % len(h)] - 128) / 128.0
                vec[idx] += val

        # Normalize to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            return [x / norm for x in vec]
        return vec

    def embed_text(self, text: str) -> list[float]:
        """Generate normalized embedding vector for a single string."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        model = self._get_model()
        if model is not None:
            try:
                embeddings = list(model.embed([text]))
                if embeddings:
                    raw_vec = embeddings[0]
                    # Convert to standard Python float list
                    vec = [float(x) for x in raw_vec]
                    # Ensure unit normalization
                    norm = math.sqrt(sum(x * x for x in vec))
                    if norm > 1e-9:
                        return [x / norm for x in vec]
                    return vec
            except Exception as e:
                logger.debug(
                    f"FastEmbed embedding error: {e}, falling back to pseudo-vector"
                )

        return self._pseudo_vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized embedding vectors for a batch of strings."""
        if not texts:
            return []

        model = self._get_model()
        if model is not None:
            try:
                embeddings = list(model.embed(texts))
                results: list[list[float]] = []
                for raw_vec in embeddings:
                    vec = [float(x) for x in raw_vec]
                    norm = math.sqrt(sum(x * x for x in vec))
                    results.append([x / norm for x in vec] if norm > 1e-9 else vec)
                return results
            except Exception as e:
                logger.debug(f"FastEmbed batch error: {e}, falling back")

        return [self._pseudo_vector(t) for t in texts]

    @staticmethod
    def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a < 1e-9 or norm_b < 1e-9:
            return 0.0

        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


# Global singleton instance
embedding_service = EmbeddingService()
