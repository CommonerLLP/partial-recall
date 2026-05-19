"""Hardware detection for embedding model recommendations.

Stdlib-only — no psutil or other deps. Best-effort; never raises.
Used by `partial-recall init` to offer a hardware-appropriate model ladder.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HardwareProfile:
    ram_gb: float | None
    is_apple_silicon: bool
    tier: str  # "minimal" | "standard" | "powerful"

    def ram_label(self) -> str:
        if self.ram_gb is None:
            return "unknown RAM"
        return f"~{self.ram_gb:.0f} GB RAM"

    def chip_label(self) -> str:
        if self.is_apple_silicon:
            return "Apple Silicon (Metal acceleration available)"
        return ""


def detect_hardware() -> HardwareProfile:
    """Detect machine RAM and chip type. Never raises."""
    ram_gb = _detect_ram_gb()
    is_apple_silicon = (
        platform.system() == "Darwin" and platform.machine() == "arm64"
    )
    return HardwareProfile(
        ram_gb=ram_gb,
        is_apple_silicon=is_apple_silicon,
        tier=_tier(ram_gb, is_apple_silicon),
    )


def _detect_ram_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
            ).strip()
            return round(int(out) / (1024 ** 3), 1)
        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
    except Exception:  # noqa: BLE001
        log.debug("hardware.detect_ram_failed")
    return None


def _tier(ram_gb: float | None, is_apple_silicon: bool) -> str:
    # Apple Silicon M-series unified memory is more efficient than x86 DRAM —
    # a 16 GB M-series machine can comfortably run models that need 12 GB on x86.
    if is_apple_silicon and ram_gb is not None and ram_gb >= 16:
        return "powerful"
    if ram_gb is None:
        return "standard"
    if ram_gb < 6:
        return "minimal"
    if ram_gb < 13:
        return "standard"
    return "powerful"
