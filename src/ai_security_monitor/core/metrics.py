# Prometheus metrics and middleware.

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# HTTP metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

# Business metrics
entries_total = Gauge(
    "entries_total",
    "Total intelligence entries in database",
    ["category"],
)

high_velocity_entries = Gauge(
    "high_velocity_entries_total",
    "High velocity entries (velocity >= 70)",
)

pre_cve_warnings = Gauge(
    "pre_cve_warnings_total",
    "Pre-CVE warnings detected",
)

fetch_operations = Counter(
    "fetch_operations_total",
    "Total fetch operations",
    ["source", "status"],
)

analysis_operations = Counter(
    "analysis_operations_total",
    "Total analysis operations",
    ["model", "status"],
)

delivery_operations = Counter(
    "delivery_operations_total",
    "Total delivery operations",
    ["channel", "status"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting HTTP metrics."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Get endpoint name from route
        endpoint = request.url.path
        if hasattr(request, "scope") and request.scope.get("route"):
            endpoint = request.scope["route"].path

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            duration = time.time() - start_time
            http_requests_total.labels(
                method=request.method,
                endpoint=endpoint,
                status=status,
            ).inc()
            http_request_duration.labels(
                method=request.method,
                endpoint=endpoint,
            ).observe(duration)

        return response


async def metrics_middleware(request: Request, call_next):
    """Function-based middleware for metrics."""
    start_time = time.time()

    endpoint = request.url.path
    if hasattr(request, "scope") and request.scope.get("route"):
        endpoint = request.scope["route"].path

    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        duration = time.time() - start_time
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status=status,
        ).inc()
        http_request_duration.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

    return response


def update_business_metrics(
    entries_by_category: dict[str, int] = None,
    high_vel_count: int = None,
    pre_cve_count: int = None,
):
    """Update business metrics from database stats."""
    if entries_by_category:
        for category, count in entries_by_category.items():
            entries_total.labels(category=category).set(count)

    if high_vel_count is not None:
        high_velocity_entries.set(high_vel_count)

    if pre_cve_count is not None:
        pre_cve_warnings.set(pre_cve_count)


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
