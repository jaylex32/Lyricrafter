from __future__ import annotations

import os
import sys
from typing import TextIO


_NULL_STREAMS: list[TextIO] = []


def ensure_output_streams() -> None:
    """Give windowed frozen apps valid streams for libraries that log to a console."""
    # Hugging Face downloads are reported through Lyricrafter's own progress
    # callbacks. Its terminal progress bars can fail when a Windows GUI process
    # is launched without a console, even when PyInstaller supplies a stream-like
    # object instead of None.
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    for name in ("stdout", "stderr"):
        current = getattr(sys, name, None)
        if _stream_is_usable(current):
            continue
        stream = open(os.devnull, "w", encoding="utf-8")
        _NULL_STREAMS.append(stream)
        setattr(sys, name, stream)


def _stream_is_usable(stream: TextIO | None) -> bool:
    if stream is None:
        return False
    try:
        stream.write("")
        stream.flush()
    except (AttributeError, OSError, ValueError):
        return False
    return True
