from __future__ import annotations

import os
import sys
from typing import TextIO


_NULL_STREAMS: list[TextIO] = []


def ensure_output_streams() -> None:
    """Give windowed frozen apps valid streams for libraries that log to a console."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        stream = open(os.devnull, "w", encoding="utf-8")
        _NULL_STREAMS.append(stream)
        setattr(sys, name, stream)
