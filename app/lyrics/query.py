from __future__ import annotations

import re
from pathlib import Path

from app.lyrics.types import LyricSearchQuery


def query_from_audio(path: Path) -> LyricSearchQuery:
    tags = _read_tags(path)
    title = tags.get("title", "")
    artist = tags.get("artist", "")
    album = tags.get("album", "")
    duration = _read_duration(path)
    if not title:
        artist_from_name, title_from_name = _split_filename(path.stem)
        title = title_from_name
        artist = artist or artist_from_name
    return LyricSearchQuery(
        source_path=path,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        isrc=tags.get("isrc", ""),
    )


def _read_tags(path: Path) -> dict[str, str]:
    try:
        from mutagen import File

        audio = File(path, easy=True)
    except Exception:
        audio = None
    if audio is None:
        return {}
    return {
        "title": _first_tag(audio, "title"),
        "artist": _first_tag(audio, "artist", "albumartist", "artists"),
        "album": _first_tag(audio, "album"),
        "isrc": _first_tag(audio, "isrc"),
    }


def _read_duration(path: Path) -> int | None:
    try:
        from mutagen import File

        audio = File(path)
    except Exception:
        return None
    info = getattr(audio, "info", None)
    length = getattr(info, "length", None)
    return int(round(float(length))) if length else None


def _first_tag(audio, *keys: str) -> str:
    for key in keys:
        values = audio.get(key) or []
        if values:
            return str(values[0]).strip()
    return ""


def _split_filename(stem: str) -> tuple[str, str]:
    cleaned = re.sub(r"\[[^\]]+\]|\([^)]+\)", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
    parts = [part.strip() for part in re.split(r"\s+-\s+", cleaned, maxsplit=1)]
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    return "", cleaned
