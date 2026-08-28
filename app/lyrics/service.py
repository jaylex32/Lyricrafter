from __future__ import annotations

from app.lyrics.providers import CaptionProvider, ExperimentalProvider, LRCLIBProvider, LocalProvider, SyncedLyricsProvider
from app.lyrics.query import query_from_audio
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics

PROVIDER_FACTORIES = {
    "lrclib": LRCLIBProvider,
    "local": LocalProvider,
    "captions": CaptionProvider,
    "synced": SyncedLyricsProvider,
    "experimental": ExperimentalProvider,
}


class LyricsSourceService:
    def __init__(self, enabled: dict[str, bool] | None = None) -> None:
        self.enabled = enabled or {
            "lrclib": True,
            "local": True,
            "captions": True,
            "synced": True,
            "experimental": False,
        }
        self.providers = {
            key: factory()
            for key, factory in PROVIDER_FACTORIES.items()
            if self.enabled.get(key, False)
        }

    def build_query(self, path) -> LyricSearchQuery:
        return query_from_audio(path)

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        candidates: list[LyricCandidate] = []
        for provider in self.providers.values():
            try:
                candidates.extend(provider.search(query))
            except Exception:
                continue
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        key = _provider_key(candidate.provider)
        provider = self.providers.get(key)
        if provider is None:
            provider_cls = PROVIDER_FACTORIES.get(key)
            if provider_cls is None:
                raise RuntimeError(f"Unknown lyric source: {candidate.provider}")
            provider = provider_cls()
        return provider.fetch(candidate)


def _provider_key(provider_name: str) -> str:
    normalized = provider_name.strip().casefold()
    if normalized == "lrclib":
        return "lrclib"
    if normalized == "local":
        return "local"
    if normalized == "captions":
        return "captions"
    if normalized == "synced" or normalized.startswith("synced/"):
        return "synced"
    return "experimental"
