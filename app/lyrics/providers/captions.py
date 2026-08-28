from __future__ import annotations

from pathlib import Path

from app.lyrics.parsing import parse_caption_text, read_text_file
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics


class CaptionProvider:
    name = "Captions"

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        candidates: list[LyricCandidate] = []
        for path in _caption_paths(query.source_path):
            text = read_text_file(path)
            lines = parse_caption_text(text, path.suffix)
            if not lines:
                continue
            candidates.append(
                LyricCandidate(
                    provider=self.name,
                    title=query.title or path.stem,
                    artist=query.artist,
                    album=query.album,
                    synced=True,
                    confidence=72,
                    source_id=str(path),
                    payload={"path": str(path), "text": text, "suffix": path.suffix},
                )
            )
        return candidates

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        text = str(candidate.payload.get("text") or "")
        suffix = str(candidate.payload.get("suffix") or ".srt")
        lines = parse_caption_text(text, suffix)
        return ProviderLyrics(
            provider=self.name,
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            synced=bool(lines),
            lines=lines,
            plain_text="",
            confidence=candidate.confidence,
            language=candidate.language,
        )


def _caption_paths(source: Path) -> list[Path]:
    base = source.with_suffix("")
    exact = [base.with_suffix(".srt"), base.with_suffix(".vtt")]
    globbed = sorted(source.parent.glob(f"{base.name}*.srt")) + sorted(source.parent.glob(f"{base.name}*.vtt"))
    seen: set[Path] = set()
    paths: list[Path] = []
    for path in exact + globbed:
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths
