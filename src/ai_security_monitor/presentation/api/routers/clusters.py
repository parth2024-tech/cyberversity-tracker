"""
FastAPI router for Semantic Cluster Graph & Summary (Workstream B2).
Provides endpoints for high-performance canvas visualizer, kNN topology,
and cross-language topic exploration.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ai_security_monitor.application.services.cluster_graph_service import (
    cluster_graph_service,
)

router = APIRouter(prefix="/clusters", tags=["Semantic Clusters"])


@router.get("/graph", response_model=dict[str, Any])
async def get_cluster_graph(
    days: int = Query(14, ge=1, le=14, description="Freshness window in days (max 14)"),
    max_nodes: int = Query(300, ge=10, le=500, description="Node budget (max 500)"),
    min_similarity: float = Query(
        0.72, ge=0.50, le=0.98, description="Minimum cosine similarity threshold"
    ),
    category: str | None = Query(None, description="Optional AI category filter"),
) -> dict[str, Any]:
    """Retrieve precomputed semantic cluster graph topology with kNN edges and clusters."""
    return await cluster_graph_service.get_graph(
        days=days,
        max_nodes=max_nodes,
        min_similarity=min_similarity,
        category=category,
    )


@router.get("/summary", response_model=dict[str, Any])
async def get_cluster_summary(
    days: int = Query(14, ge=1, le=14, description="Freshness window in days (max 14)"),
    category: str | None = Query(None, description="Optional AI category filter"),
) -> dict[str, Any]:
    """Retrieve high-level summary of active clusters, regional balance, and cross-lingual story rate."""
    return await cluster_graph_service.get_summary(
        days=days,
        category=category,
    )
