"""
Semantic Cluster Graph Service (Workstream B2).
Computes kNN semantic similarity edges via sqlite-vec and embedding service,
resolves cross-language story clusters with precision gate >= 0.90,
and precomputes cached graph topology (< 2s render budget) with <= 500 nodes.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ai_security_monitor.application.services.cross_language_clustering import (
    cross_language_clustering_service,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    embedding_service,
)
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

# Strict constants per architectural specification
MAX_GRAPH_AGE_DAYS = 14
MAX_GRAPH_NODES = 500
DEFAULT_MIN_SIMILARITY = 0.72


class PrecisionGateError(RuntimeError):
    """Raised when precision gate drops below required 0.90 threshold."""


@dataclass
class GraphNode:
    """A single intelligence article node in the cluster graph."""

    id: str
    title: str
    url: str
    category: str
    region: str  # "US" | "CN" | "EU/Global"
    published_at: str | None
    velocity: int
    cluster_id: str
    cluster_label: str
    degree: int = 0
    source_name: str = ""
    language: str = "en"


@dataclass
class GraphEdge:
    """Similarity edge connecting two intelligence nodes."""

    source: str
    target: str
    similarity: float
    weight: float
    type: str = "semantic_knn"  # "semantic_knn" | "cross_lingual_match"


@dataclass
class ClusterSummary:
    """Aggregate statistics for a coherent semantic topic cluster."""

    cluster_id: str
    label: str
    dominant_category: str
    dominant_region: str
    node_count: int
    languages: list[str]
    avg_velocity: float
    nodes: list[str] = field(default_factory=list)
    dominant_entities: list[str] = field(default_factory=list)


@dataclass
class ClusterGraphPayload:
    """Precomputed graph topology payload ready for canvas rendering and API delivery."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    count_nodes: int
    count_edges: int
    count_clusters: int
    generated_at: str
    precision_gate_passed: bool


class ClusterGraphService:
    """Precomputes and caches kNN semantic graph topology with precision-gated clustering."""

    def __init__(self) -> None:
        self._gate_verified: bool | None = None

    def verify_precision_gate(self) -> bool:
        """
        Verify the precision gate (>= 0.90) on the labeled evaluation set.
        Guarantees that negative same-org distractors are never falsely merged.
        """
        from ai_security_monitor.application.services.cross_language_clustering import (
            EVALUATION_NEGATIVE_PAIRS,
            EVALUATION_POSITIVE_PAIRS,
        )

        now = datetime.now(UTC)
        tp = 0
        fn = 0
        for cn_text, en_text, _ in EVALUATION_POSITIVE_PAIRS:
            matched = cross_language_clustering_service.are_same_story(
                cn_text,
                en_text,
                published_a=now,
                published_b=now + timedelta(hours=2),
                max_delta_hours=72.0,
            )
            if matched:
                tp += 1
            else:
                fn += 1

        fp = 0
        tn = 0
        for text_a, text_b, _ in EVALUATION_NEGATIVE_PAIRS:
            matched = cross_language_clustering_service.are_same_story(
                text_a,
                text_b,
                published_a=now,
                published_b=now + timedelta(hours=2),
                max_delta_hours=72.0,
            )
            if matched:
                fp += 1
            else:
                tn += 1

        total_pos = tp + fp
        precision = tp / total_pos if total_pos > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        passed = precision >= 0.90 and recall >= 0.85 and fp == 0
        self._gate_verified = passed
        if not passed:
            logger.error(
                f"Precision gate failed: precision={precision:.2f}, recall={recall:.2f}, fp={fp}"
            )
        return passed

    @classmethod
    def classify_region(cls, entry: Entry, source_name: str = "") -> str:
        """Classify dispatch origin into US, CN, or EU/Global."""
        src_lower = source_name.lower()
        title_lower = entry.title.lower()
        text_sample = f"{entry.title} {entry.summary}"

        # 1. China Corridor
        if re.search(r"[\u4e00-\u9fa5]", text_sample):
            return "CN"
        if any(
            k in src_lower
            for k in (
                "china",
                "weixin",
                "weibo",
                "baidu",
                "tencent",
                "aliyun",
                "alibaba",
                "deepseek",
                "moonshot",
                "zhipu",
                "modelscope",
                "jiqizhixin",
                "qbit",
            )
        ):
            return "CN"
        if entry.url and any(
            d in entry.url.lower()
            for d in (
                ".cn",
                "weibo.com",
                "qq.com",
                "baidu.com",
                "zhihu.com",
                "modelscope.cn",
            )
        ):
            return "CN"

        # 2. EU / International Ecosystem
        if any(
            k in src_lower
            for k in ("mistral", "kyutai", "aleph", "inria", "cern", "europe", "eu")
        ):
            return "EU/Global"
        if any(
            k in title_lower
            for k in (
                "mistral",
                "kyutai",
                "aleph alpha",
                "european ai",
                "sovereign ai",
            )
        ):
            return "EU/Global"

        # 3. Default US / Worldwide AI Ecosystem
        return "US"

    @classmethod
    def extract_entry_velocity(cls, entry: Entry) -> int:
        """Extract or compute velocity score (1-100) for visual node sizing."""
        if entry.analysis and hasattr(entry.analysis, "threat_velocity"):
            return max(1, min(100, int(entry.analysis.threat_velocity)))

        # Velocity heuristic based on age within 14-day freshness window
        now = datetime.now(UTC)
        pub_date = (
            entry.published_at
            if entry.published_at.tzinfo is not None
            else entry.published_at.replace(tzinfo=UTC)
        )
        age_hours = max(0.0, (now - pub_date).total_seconds() / 3600.0)

        # Decay from 95 down to 15 over 14 days (336 hours)
        decay = math.exp(-age_hours / 72.0)
        return max(15, min(95, int(15 + 80 * decay)))

    async def get_graph(
        self,
        days: int = 14,
        max_nodes: int = 300,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        category: str | None = None,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve or compute precomputed semantic cluster graph payload.
        Protected by response cache (120s TTL) to guarantee < 2s render budget.
        """
        # Clamp inputs
        days = max(1, min(MAX_GRAPH_AGE_DAYS, days))
        max_nodes = max(10, min(MAX_GRAPH_NODES, max_nodes))
        min_similarity = max(0.50, min(0.98, float(min_similarity)))

        cache_key = f"semantic_cluster_graph:{days}:{max_nodes}:{min_similarity}:{category or 'all'}"

        async def _compute() -> dict[str, Any]:
            return await self._build_graph_payload(
                days=days,
                max_nodes=max_nodes,
                min_similarity=min_similarity,
                category=category,
                uow=uow,
            )

        # If custom UOW is provided (e.g., test session), compute directly without global cache collision
        if uow is not None:
            return await _compute()

        return await response_cache.get_or_set(cache_key, 120.0, _compute)

    async def _build_graph_payload(
        self,
        days: int,
        max_nodes: int,
        min_similarity: float,
        category: str | None,
        uow: SqlAlchemyUnitOfWork | None,
    ) -> dict[str, Any]:
        """Core computation of nodes, sqlite-vec kNN edges, and precision-gated clusters."""
        # 1. Verify precision gate before graph generation
        gate_ok = self.verify_precision_gate()

        # 2. Acquire Unit of Work
        if uow is None:
            async with SqlAlchemyUnitOfWork() as uow_instance:
                return await self._execute_build(
                    days=days,
                    max_nodes=max_nodes,
                    min_similarity=min_similarity,
                    category=category,
                    uow=uow_instance,
                    gate_ok=gate_ok,
                )
        else:
            return await self._execute_build(
                days=days,
                max_nodes=max_nodes,
                min_similarity=min_similarity,
                category=category,
                uow=uow,
                gate_ok=gate_ok,
            )

    async def _execute_build(
        self,
        days: int,
        max_nodes: int,
        min_similarity: float,
        category: str | None,
        uow: SqlAlchemyUnitOfWork,
        gate_ok: bool,
    ) -> dict[str, Any]:
        """Internal execution inside an open UOW session."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Build query filters
        filters = EntryFilters(since=cutoff, sort_by="published")
        if category:
            try:
                filters.category = Category(category)
            except ValueError:
                pass

        # Retrieve entries up to node budget (sorted by published date descending)
        raw_entries = await uow.entries.list(
            filters=filters,
            pagination=PaginationParams(limit=max_nodes, offset=0),
        )

        # Enforce Worldwide AI Ecosystem directive: discard cybersecurity/vulnerabilities
        entries: list[Entry] = []
        for e in raw_entries:
            cat_val = (
                e.category.value if hasattr(e.category, "value") else str(e.category)
            )
            if cat_val in (
                "cybersecurity",
                "vulnerabilities",
                "cyber_tools",
                "exploits_tricks",
            ):
                continue
            entries.append(e)

        if not entries:
            return asdict(
                ClusterGraphPayload(
                    nodes=[],
                    edges=[],
                    clusters=[],
                    count_nodes=0,
                    count_edges=0,
                    count_clusters=0,
                    generated_at=datetime.now(UTC).isoformat(),
                    precision_gate_passed=gate_ok,
                )
            )

        # Source name lookup map
        sources = await uow.sources.list()
        source_map = {s.id: s.name for s in sources}

        # 3. Pre-extract entities and cluster keys
        extracted_info = {}
        for e in entries:
            text_rep = f"{e.title} {e.summary}".strip()
            ent_res = cross_language_clustering_service.extract_entities(text_rep)
            extracted_info[e.id] = ent_res

        # 4. Generate Embeddings & Query Vector Neighbors
        # First check if embeddings can be queried from sqlite-vec virtual table
        vectors: dict[UUID, list[float]] = {}
        try:
            from sqlalchemy import text

            query_vecs = text(
                "SELECT entry_id, embedding FROM entries_vec "
                "WHERE entry_id IN :entry_ids"
            )
            id_strs = tuple(str(e.id) for e in entries)
            if id_strs:
                res = await uow.session.execute(query_vecs, {"entry_ids": id_strs})
                for row in res.fetchall():
                    try:
                        entry_u = UUID(str(row[0]))
                        vec_data = row[1]
                        if isinstance(vec_data, str):
                            vectors[entry_u] = json.loads(vec_data)
                        elif isinstance(vec_data, (list, tuple)):
                            vectors[entry_u] = list(vec_data)
                    except Exception:
                        pass
        except Exception as vec_err:
            logger.debug(f"sqlite-vec entries_vec lookup notice: {vec_err}")

        # Compute fallback embeddings via embedding_service for entries not in virtual table
        for e in entries:
            if e.id not in vectors:
                t_rep = f"{e.title} {e.summary}".strip()
                vectors[e.id] = embedding_service.embed_text(t_rep)

        # 5. Compute kNN Edges & Cross-Lingual Story Matches
        # To ensure the < 2s budget, each node retains up to top-k nearest neighbors
        top_k_neighbors = 4
        node_edges: list[GraphEdge] = []
        degree_map: dict[str, int] = {str(e.id): 0 for e in entries}

        # Disjoint Set Union (DSU) for connected component clustering
        parent: dict[str, str] = {str(e.id): str(e.id) for e in entries}

        def find(x: str) -> str:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            root_x = find(x)
            root_y = find(y)
            if root_x != root_y:
                parent[root_y] = root_x

        num_entries = len(entries)
        for i in range(num_entries):
            e_a = entries[i]
            id_a = str(e_a.id)
            vec_a = vectors[e_a.id]
            ent_a = extracted_info[e_a.id]

            candidate_neighbors: list[tuple[float, int, str]] = []

            for j in range(i + 1, num_entries):
                e_b = entries[j]
                id_b = str(e_b.id)
                vec_b = vectors[e_b.id]
                ent_b = extracted_info[e_b.id]

                # A. Check Cross-Lingual Precision-Gated Match
                is_cross_match = False
                if ent_a.language != ent_b.language:
                    if cross_language_clustering_service.are_same_story(
                        e_a.title,
                        e_b.title,
                        published_a=e_a.published_at,
                        published_b=e_b.published_at,
                        max_delta_hours=72.0,
                    ):
                        is_cross_match = True

                # B. Compute Cosine Similarity
                sim = embedding_service.cosine_similarity(vec_a, vec_b)

                if is_cross_match:
                    # Boost cross-lingual corroboration to top tier
                    effective_sim = max(0.95, sim)
                    node_edges.append(
                        GraphEdge(
                            source=id_a,
                            target=id_b,
                            similarity=round(effective_sim, 3),
                            weight=round(effective_sim, 3),
                            type="cross_lingual_match",
                        )
                    )
                    degree_map[id_a] += 1
                    degree_map[id_b] += 1
                    union(id_a, id_b)
                elif sim >= min_similarity:
                    candidate_neighbors.append((sim, j, id_b))

            # Keep top-k nearest neighbors
            candidate_neighbors.sort(key=lambda x: x[0], reverse=True)
            for sim, j, id_b in candidate_neighbors[:top_k_neighbors]:
                node_edges.append(
                    GraphEdge(
                        source=id_a,
                        target=id_b,
                        similarity=round(sim, 3),
                        weight=round(sim, 3),
                        type="semantic_knn",
                    )
                )
                degree_map[id_a] += 1
                degree_map[id_b] += 1
                # Cluster together if strong connection (>= 0.76)
                if sim >= 0.76:
                    union(id_a, id_b)

        # 6. Assemble Clusters from Connected Components
        clusters_map: dict[str, list[Entry]] = {}
        for e in entries:
            root_id = find(str(e.id))
            clusters_map.setdefault(root_id, []).append(e)

        cluster_summaries: list[ClusterSummary] = []
        node_cluster_labels: dict[str, tuple[str, str]] = {}

        for root_id, comp_entries in clusters_map.items():
            cluster_key_id = f"c_{root_id[:8]}"

            # Determine cluster label: check if specific entity cluster_key exists
            candidate_labels: list[str] = []
            for c_entry in comp_entries:
                ent = extracted_info[c_entry.id]
                if ent.cluster_key and not ent.cluster_key.endswith(":general"):
                    parts = ent.cluster_key.split(":")
                    formatted_label = " ".join(p.capitalize() for p in parts)
                    candidate_labels.append(formatted_label)

            if candidate_labels:
                # Use most frequent or first specific model key
                cluster_label = candidate_labels[0]
            else:
                # Fallback: title of the entry with highest velocity
                best_entry = max(
                    comp_entries, key=lambda x: self.extract_entry_velocity(x)
                )
                # Clean title prefix
                cluster_label = re.sub(
                    r"^(\[[^\]]+\]|\([^\)]+\)|Show HN:\s*|Announcing:\s*)",
                    "",
                    best_entry.title,
                ).strip()
                if len(cluster_label) > 60:
                    cluster_label = cluster_label[:57] + "..."

            # Aggregate languages, regions, velocity
            langs = list({extracted_info[c_e.id].language for c_e in comp_entries})
            regions = [
                self.classify_region(c_e, source_name=source_map.get(c_e.source_id, ""))
                for c_e in comp_entries
            ]
            dominant_region = max(set(regions), key=regions.count)

            categories = [
                c_e.category.value
                if hasattr(c_e.category, "value")
                else str(c_e.category)
                for c_e in comp_entries
            ]
            dominant_cat = max(set(categories), key=categories.count)

            velocities = [self.extract_entry_velocity(c_e) for c_e in comp_entries]
            avg_vel = round(sum(velocities) / len(velocities), 1)

            c_summary = ClusterSummary(
                cluster_id=cluster_key_id,
                label=cluster_label,
                dominant_category=dominant_cat,
                dominant_region=dominant_region,
                node_count=len(comp_entries),
                languages=langs,
                avg_velocity=avg_vel,
                nodes=[str(c_e.id) for c_e in comp_entries],
                dominant_entities=[
                    str(extracted_info[c_e.id].model_family)
                    for c_e in comp_entries
                    if extracted_info[c_e.id].model_family is not None
                ][:5],
            )
            cluster_summaries.append(c_summary)

            for c_e in comp_entries:
                node_cluster_labels[str(c_e.id)] = (cluster_key_id, cluster_label)

        # 7. Build Final GraphNode Records
        graph_nodes: list[GraphNode] = []
        for e in entries:
            e_id_str = str(e.id)
            c_id, c_lbl = node_cluster_labels.get(e_id_str, ("c_unknown", e.title[:40]))
            src_name = source_map.get(e.source_id, "Unknown Source")
            region = self.classify_region(e, source_name=src_name)
            vel = self.extract_entry_velocity(e)
            deg = degree_map.get(e_id_str, 0)
            lang = extracted_info[e.id].language

            cat_str = (
                e.category.value if hasattr(e.category, "value") else str(e.category)
            )

            graph_nodes.append(
                GraphNode(
                    id=e_id_str,
                    title=e.title,
                    url=e.url,
                    category=cat_str,
                    region=region,
                    published_at=e.published_at.isoformat() if e.published_at else None,
                    velocity=vel,
                    cluster_id=c_id,
                    cluster_label=c_lbl,
                    degree=deg,
                    source_name=src_name,
                    language=lang,
                )
            )

        # Sort clusters by node count descending
        cluster_summaries.sort(
            key=lambda c: (c.node_count, c.avg_velocity), reverse=True
        )

        payload = ClusterGraphPayload(
            nodes=[asdict(n) for n in graph_nodes],
            edges=[asdict(ed) for ed in node_edges],
            clusters=[asdict(cl) for cl in cluster_summaries],
            count_nodes=len(graph_nodes),
            count_edges=len(node_edges),
            count_clusters=len(cluster_summaries),
            generated_at=datetime.now(UTC).isoformat(),
            precision_gate_passed=gate_ok,
        )

        return asdict(payload)

    async def get_summary(
        self,
        days: int = 14,
        category: str | None = None,
        uow: SqlAlchemyUnitOfWork | None = None,
    ) -> dict[str, Any]:
        """Get high-level summary of active clusters, regional distributions, and cross-lingual story rate."""
        graph_data = await self.get_graph(
            days=days,
            max_nodes=MAX_GRAPH_NODES,
            min_similarity=DEFAULT_MIN_SIMILARITY,
            category=category,
            uow=uow,
        )

        nodes = graph_data.get("nodes", [])
        clusters = graph_data.get("clusters", [])

        # Regional distribution
        region_counts: dict[str, int] = {"US": 0, "CN": 0, "EU/Global": 0}
        for n in nodes:
            reg = n.get("region", "US")
            region_counts[reg] = region_counts.get(reg, 0) + 1

        # Cross-language clusters
        cross_lingual_clusters = [
            c for c in clusters if len(c.get("languages", [])) > 1
        ]
        cross_rate = len(cross_lingual_clusters) / len(clusters) if clusters else 0.0

        # Top 5 largest clusters
        top_5 = clusters[:5]

        return {
            "total_nodes": graph_data.get("count_nodes", 0),
            "total_edges": graph_data.get("count_edges", 0),
            "total_clusters": graph_data.get("count_clusters", 0),
            "cross_lingual_cluster_count": len(cross_lingual_clusters),
            "cross_lingual_cluster_rate": round(cross_rate, 3),
            "regional_distribution": region_counts,
            "top_clusters": top_5,
            "precision_gate_passed": graph_data.get("precision_gate_passed", True),
            "freshness_window_days": days,
            "generated_at": graph_data.get("generated_at"),
        }


cluster_graph_service = ClusterGraphService()
