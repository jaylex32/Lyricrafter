from __future__ import annotations

from pathlib import Path

from app.lyrics.parsing import parse_lrc_text, parse_plain_text, read_text_file
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics


class LocalProvider:
    name = "Local"

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        candidates: list[LyricCandidate] = []
        for path in _sidecar_paths(query.source_path):
            if not path.exists():
                continue
            suffix = path.suffix.lower()
            text = read_text_file(path)
            if suffix == ".lrc":
                lines = parse_lrc_text(text)
                if not lines:
                    continue
                synced = True
            elif suffix == ".txt":
                if not parse_plain_text(text):
                    continue
                synced = False
            else:
                continue
            candidates.append(
                LyricCandidate(
                    provider=self.name,
                    title=query.title or path.stem,
                    artist=query.artist,
                    album=query.album,
                    synced=synced,
                    confidence=96 if synced else 82,
                    source_id=str(path),
                    payload={"path": str(path), "text": text},
                )
            )
        embedded = _embedded_lyrics(query.source_path)
        if embedded:
            lines = parse_lrc_text(embedded)
            candidates.append(
                LyricCandidate(
                    provider=self.name,
                    title=query.title or query.source_path.stem,
                    artist=query.artist,
                    album=query.album,
                    synced=bool(lines),
                    confidence=88 if lines else 76,
                    source_id="embedded",
                    payload={"text": embedded},
                )
            )
        return candidates

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        text = str(candidate.payload.get("text") or "")
        lines = parse_lrc_text(text) if candidate.synced else []
        return ProviderLyrics(
            provider=self.name,
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            synced=bool(lines),
            lines=lines,
            plain_text="" if lines else text,
            confidence=candidate.confidence,
            language=candidate.language,
        )


def _sidecar_paths(source: Path) -> list[Path]:
    base = source.with_suffix("")
    return [base.with_suffix(".lrc"), base.with_suffix(".txt")]


def _embedded_lyrics(source: Path) -> str:
    try:
        from mutagen import File

        audio = File(source)
    except Exception:
        audio = None
    if not audio:
        return ""
    for key in (
        "SYLT::eng",
        "USLT::eng",
        "lyrics",
        "LYRICS",
        "\xa9lyr",
        "UNSYNCEDLYRICS",
        "SYNCLYRICS",
    ):
        value = _tag_value(audio, key)
        if value:
            return value
    for key in getattr(audio, "keys", lambda: [])():
        if "lyric" in str(key).casefold():
            value = _tag_value(audio, key)
            if value:
                return value
    return ""


def _tag_value(audio, key) -> str:
    try:
        value = audio.get(key)
    except Exception:
        return ""
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        value = value[0]
    if hasattr(value, "text"):
        text = getattr(value, "text")
        if isinstance(text, list):
            return "\n".join(str(item) for item in text)
        return str(text)
    return str(value).strip()
