from __future__ import annotations

import os


CPU_PERFORMANCE_MODES = ("auto", "background", "balanced", "maximum", "custom")


def logical_cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def cpu_threads_for_mode(mode: str, custom_threads: int = 0, logical_threads: int | None = None) -> int:
    available = max(1, logical_threads or logical_cpu_count())
    normalized = mode if mode in CPU_PERFORMANCE_MODES else "auto"
    if normalized == "custom":
        return min(available, max(1, custom_threads or 1))

    ratios = {
        "background": 0.25,
        "balanced": 0.40,
        "auto": 0.60,
        "maximum": 1.0,
    }
    minimums = {"background": 1, "balanced": 2, "auto": 4, "maximum": 1}
    requested = max(minimums[normalized], round(available * ratios[normalized]))
    return min(available, requested)
