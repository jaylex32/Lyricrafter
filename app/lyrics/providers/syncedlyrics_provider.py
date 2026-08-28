from __future__ import annotations

from app.lyrics.align import confidence_for_candidate
from app.lyrics.parsing import parse_lrc_text
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics

SYNCEDLYRICS_PROVIDERS = ("Musixmatch", "Lrclib", "NetEase", "Megalobiz", "Genius")


class SyncedLyricsProvider:
    name = "Synced"

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        search_term = _search_term(query)
        if not search_term:
            return []

        candidates: list[LyricCandidate] = []
        for provider_name in SYNCEDLYRICS_PROVIDERS:
            for synced_only in (True, False):
                if synced_only and provider_name == "Genius":
                    continue
                text = _search_syncedlyrics(search_term, provider_name, synced_only=synced_only)
                if not text:
                    continue
                lines = parse_lrc_text(text)
                is_synced = bool(lines)
                if synced_only and not is_synced:
                    continue
                confidence = confidence_for_candidate(
                    query.title,
                    query.artist,
                    query.album,
                    query.duration,
                    query.title or query.source_path.stem,
                    query.artist,
                    query.album,
                    query.duration,
                    is_synced,
                )
                if provider_name == "Genius" and not is_synced:
                    confidence = min(confidence, 76)
                candidates.append(
                    LyricCandidate(
                        provider=f"{self.name}/{provider_name}",
                        title=query.title or query.source_path.stem,
                        artist=query.artist,
                        album=query.album,
                        synced=is_synced,
                        confidence=confidence,
                        language="",
                        source_id=f"{provider_name}:{'synced' if is_synced else 'plain'}",
                        payload={
                            "provider": provider_name,
                            "text": text,
                            "search_term": search_term,
                            "synced": is_synced,
                        },
                    )
                )
                if is_synced:
                    break
        return _dedupe_candidates(candidates)

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        text = str(candidate.payload.get("text") or "")
        lines = parse_lrc_text(text)
        return ProviderLyrics(
            provider=candidate.provider,
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            synced=bool(lines),
            lines=lines,
            plain_text="" if lines else text,
            confidence=candidate.confidence,
            language=candidate.language,
        )


def _search_term(query: LyricSearchQuery) -> str:
    parts = [query.artist, query.title]
    term = " ".join(part for part in parts if part).strip()
    return term or query.source_path.stem


def _search_syncedlyrics(search_term: str, provider: str, synced_only: bool) -> str | None:
    try:
        import syncedlyrics
    except ImportError as exc:
        raise RuntimeError("Install syncedlyrics to use the Synced source.") from exc
    return syncedlyrics.search(
        search_term,
        providers=[provider],
        synced_only=synced_only,
        plain_only=not synced_only,
    )


def _dedupe_candidates(candidates: list[LyricCandidate]) -> list[LyricCandidate]:
    seen: set[tuple[str, bool, str]] = set()
    unique: list[LyricCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.confidence, item.synced), reverse=True):
        text = str(candidate.payload.get("text") or "")
        key = (candidate.provider, candidate.synced, text[:160])
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique[:10]
