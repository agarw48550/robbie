"""Lightweight runtime metrics for Pi Zero performance budgets."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import log

# Targets from the upgrade plan (guidance, not hard fails).
TARGET_IDLE_CPU_PCT = 10.0
TARGET_TALKING_CPU_PCT = 45.0
TARGET_RAM_MB = 180.0
TARGET_BOOT_S = 8.0
TARGET_RECONNECT_S = 2.0


@dataclass
class PerfMetrics:
    boot_started_at: float = field(default_factory=time.monotonic)
    boot_completed_at: Optional[float] = None
    last_reconnect_s: Optional[float] = None
    samples: int = 0

    def mark_boot_complete(self) -> None:
        self.boot_completed_at = time.monotonic()
        elapsed = self.boot_completed_at - self.boot_started_at
        log.info("Boot complete in %.2fs (target <%.0fs)", elapsed, TARGET_BOOT_S)

    def mark_reconnect(self, seconds: float) -> None:
        self.last_reconnect_s = seconds
        log.info("Reconnect took %.2fs (target <%.0fs)", seconds, TARGET_RECONNECT_S)

    def snapshot(self) -> dict[str, Any]:
        rss_mb: Optional[float] = None
        try:
            import resource

            # ru_maxrss is KB on Linux, bytes on macOS — normalize roughly.
            raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mb = raw / 1024.0 if os.uname().sysname == "Linux" else raw / (1024.0 * 1024.0)
        except Exception:
            pass
        boot_s = None
        if self.boot_completed_at is not None:
            boot_s = self.boot_completed_at - self.boot_started_at
        self.samples += 1
        return {
            "boot_s": boot_s,
            "last_reconnect_s": self.last_reconnect_s,
            "rss_mb": rss_mb,
            "targets": {
                "idle_cpu_pct": TARGET_IDLE_CPU_PCT,
                "talking_cpu_pct": TARGET_TALKING_CPU_PCT,
                "ram_mb": TARGET_RAM_MB,
                "boot_s": TARGET_BOOT_S,
                "reconnect_s": TARGET_RECONNECT_S,
            },
        }

    def log_snapshot(self) -> None:
        snap = self.snapshot()
        log.info(
            "Perf snapshot rss_mb=%s boot_s=%s reconnect_s=%s",
            snap.get("rss_mb"),
            snap.get("boot_s"),
            snap.get("last_reconnect_s"),
        )


_METRICS = PerfMetrics()


def get_metrics() -> PerfMetrics:
    return _METRICS
