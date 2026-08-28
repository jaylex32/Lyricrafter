from __future__ import annotations

from pathlib import Path


def build_initial_prompt(source_path: Path, user_hints: str = "", use_metadata: bool = True) -> str:
    parts = [
        "Transcribe this song as sung lyrics.",
        "Preserve repeated choruses, ad-libs, names, and short vocal phrases.",
        "Do not add captions, commentary, or outro phrases that are not sung.",
    ]
    if use_metadata:
        metadata = audio_metadata_hints(source_path)
        if metadata:
            parts.append(metadata)
    cleaned_hints = " ".join(user_hints.split())
    if cleaned_hints:
        parts.append(f"User hints: {cleaned_hints}")
    return " ".join(parts)[:900]


def audio_metadata_hints(source_path: Path) -> str:
    values = _read_mutagen_tags(source_path)
    title = values.get("title") or source_path.stem
    artist = values.get("artist") or values.get("albumartist")
    album = values.get("album")
    details: list[str] = []
    if title:
        details.append(f"title: {title}")
    if artist:
        details.append(f"artist: {artist}")
    if album:
        details.append(f"album: {album}")
    return "Audio metadata hints: " + "; ".join(details) if details else ""


def _read_mutagen_tags(source_path: Path) -> dict[str, str]:
    try:
        from mutagen import File
    except ImportError:
        return {}
    try:
        audio = File(source_path, easy=True)
    except Exception:
        return {}
    if not audio or not audio.tags:
        return {}
    result: dict[str, str] = {}
    for key in ("title", "artist", "albumartist", "album"):
        value = audio.tags.get(key)
        if isinstance(value, list) and value:
            result[key] = str(value[0])
        elif value:
            result[key] = str(value)
    return result
