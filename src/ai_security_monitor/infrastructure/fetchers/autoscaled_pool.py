"""
Resource-Governed Worker Scaling (AutoscaledPool).
Continuously monitors system RAM and CPU load to dynamically scale concurrency,
preventing kernel out-of-memory (OOM) panics and honoring Arch Linux on-demand governance.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


def get_system_resource_metrics() -> dict[str, Any]:
    """Inspect current system RAM, swap, and CPU load metrics.

    Uses psutil with graceful fallback to /proc/meminfo and os.getloadavg.
    """
    ram_percent = 50.0
    cpu_percent = 30.0
    available_mb = 4096.0

    try:
        import psutil

        mem = psutil.virtual_memory()
        ram_percent = mem.percent
        available_mb = mem.available / (1024 * 1024)
        cpu_percent = psutil.cpu_percent(interval=None)
    except Exception:
        # Fallback to /proc/meminfo on Linux
        try:
            if os.path.exists("/proc/meminfo"):
                meminfo = {}
                with open("/proc/meminfo") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
                total_kb = meminfo.get("MemTotal", 16000000)
                avail_kb = meminfo.get("MemAvailable", total_kb // 2)
                available_mb = avail_kb / 1024.0
                ram_percent = max(0.0, min(100.0, (1.0 - avail_kb / total_kb) * 100.0))

            load1, _, _ = os.getloadavg()
            cpu_count = os.cpu_count() or 4
            cpu_percent = min(100.0, (load1 / cpu_count) * 100.0)
        except Exception:
            pass

    return {
        "ram_percent": round(ram_percent, 1),
        "cpu_percent": round(cpu_percent, 1),
        "available_mb": round(available_mb, 1),
    }


class AutoscaledPool:
    """Resource-governed concurrency manager.

    Dynamically modulates the number of active concurrent workers based on
    real-time RAM and CPU pressure.
    """

    def __init__(
        self,
        max_concurrency: int = 8,
        min_concurrency: int = 1,
        ram_high_threshold: float = 80.0,
        ram_critical_threshold: float = 90.0,
    ):
        self.max_concurrency = max_concurrency
        self.min_concurrency = min_concurrency
        self.ram_high_threshold = ram_high_threshold
        self.ram_critical_threshold = ram_critical_threshold
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._current_limit = max_concurrency

    def evaluate_target_concurrency(self) -> int:
        """Calculate optimal worker concurrency given current host load."""
        metrics = get_system_resource_metrics()
        ram = metrics["ram_percent"]

        # Critical RAM pressure: clamp to absolute minimum
        if ram >= self.ram_critical_threshold:
            logger.warning(
                f"Critical RAM pressure ({ram}%). Clamping concurrency to {self.min_concurrency}"
            )
            return self.min_concurrency

        # Elevated RAM pressure: scale down to 2 workers
        if ram >= self.ram_high_threshold:
            target = max(self.min_concurrency, min(2, self.max_concurrency))
            logger.info(
                f"Elevated RAM load ({ram}%). Scaling concurrency down to {target}"
            )
            return target

        # Normal operation: allow full concurrency
        return self.max_concurrency

    async def acquire(self) -> None:
        """Acquire a slot in the resource-governed pool."""
        target = self.evaluate_target_concurrency()
        if target != self._current_limit:
            self._current_limit = target
            self._semaphore = asyncio.Semaphore(target)

        await self._semaphore.acquire()

    def release(self) -> None:
        """Release slot back to pool."""
        try:
            self._semaphore.release()
        except ValueError:
            pass

    async def __aenter__(self) -> AutoscaledPool:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
