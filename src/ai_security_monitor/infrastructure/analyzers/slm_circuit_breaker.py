"""
Fast-Fail Circuit Breaker for Local SLM (Ollama / Local Gateway).
Ensures zero-latency failure when local SLM daemon is offline,
implements configurable cooldowns (default 5 min), and provides safe fallback triggers.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum

import httpx

from ai_security_monitor.config.settings import settings
from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"  # Healthy, requests flow to local SLM
    OPEN = "open"  # Tripped/offline, requests fail fast to fallback
    HALF_OPEN = "half_open"  # Cooldown elapsed, testing single probe


class SLMCircuitBreaker:
    """Lightweight in-process circuit breaker guarding local SLM inference."""

    def __init__(
        self,
        cooldown_seconds: float | None = None,
        connect_timeout: float | None = None,
    ):
        self._cooldown_seconds = (
            cooldown_seconds
            if cooldown_seconds is not None
            else settings.analyzer.slm_cooldown_seconds
        )
        self._connect_timeout = (
            connect_timeout
            if connect_timeout is not None
            else settings.analyzer.slm_timeout_seconds
        )
        self._state = CircuitState.CLOSED
        self._last_failure_time: float = 0.0
        self._failure_count: int = 0
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state, updating to HALF_OPEN if cooldown expired."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def is_tripped(self) -> bool:
        """True if the breaker is open and actively shedding requests."""
        return self.state == CircuitState.OPEN

    @property
    def cooldown_remaining(self) -> float:
        """Seconds remaining before half-open probe is permitted."""
        if self._state != CircuitState.OPEN:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self._cooldown_seconds - elapsed)

    def record_failure(self, error: str | Exception) -> None:
        """Trip circuit breaker to OPEN state and begin cooldown period."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        self._state = CircuitState.OPEN
        self._last_error = str(error)
        logger.warning(
            f"⚡ Local SLM Circuit Breaker TRIPPED to OPEN ({self._last_error}). "
            f"Cooldown active for {self._cooldown_seconds:.1f}s. Routing tasks to cloud/heuristic fallback."
        )

    def record_success(self) -> None:
        """Reset circuit breaker to CLOSED healthy state."""
        if self._state != CircuitState.CLOSED:
            logger.info(
                "Local SLM Circuit Breaker recovered: state reset to CLOSED (healthy)."
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_error = None

    def reset(self) -> None:
        """Force manual reset to CLOSED state (primarily for test suites)."""
        self._state = CircuitState.CLOSED
        self._last_failure_time = 0.0
        self._failure_count = 0
        self._last_error = None

    async def check_availability(
        self,
        endpoint: str | None = None,
        timeout: float | None = None,
        force_probe: bool = False,
    ) -> bool:
        """Fast-fail check of local SLM availability.

        Returns:
            True if local SLM is responsive and ready.
            False if disabled, circuit is OPEN, or health check times out (<= 500ms).
        """
        if not getattr(settings.analyzer, "slm_enabled", True):
            return False

        current_state = self.state
        if current_state == CircuitState.OPEN and not force_probe:
            return False

        host = (endpoint or settings.analyzer.slm_endpoint).rstrip("/")
        to = timeout or self._connect_timeout

        async with self._lock:
            # Re-check under lock
            if self.state == CircuitState.OPEN and not force_probe:
                return False

            try:
                # Fast connection check against Ollama tags or OpenAI models endpoint
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(to, connect=to)
                ) as client:
                    # Try native Ollama /api/tags first
                    try:
                        resp = await client.get(f"{host}/api/tags")
                        if resp.status_code == 200:
                            self.record_success()
                            return True
                    except (httpx.ConnectError, httpx.TimeoutException):
                        raise
                    except Exception:
                        pass

                    # Fallback probe: OpenAI-compatible /v1/models
                    resp = await client.get(f"{host}/v1/models")
                    if resp.status_code in (200, 401, 403):
                        # 401/403 means server is running and reachable
                        self.record_success()
                        return True

                    self.record_failure(f"HTTP {resp.status_code}")
                    return False

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as err:
                self.record_failure(err)
                return False
            except Exception as err:
                self.record_failure(err)
                return False


# Global singleton instance
slm_circuit_breaker = SLMCircuitBreaker()
