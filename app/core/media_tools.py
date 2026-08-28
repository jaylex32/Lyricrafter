from __future__ import annotations

import shutil
from pathlib import Path


def ffmpeg_location() -> str | None:
    bundled = bundled_ffmpeg_exe()
    if bundled:
        return str(bundled)
    system = shutil.which("ffmpeg")
    return system


def bundled_ffmpeg_exe() -> Path | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    return path if path.exists() else None
