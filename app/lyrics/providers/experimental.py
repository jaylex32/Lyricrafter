from __future__ import annotations

from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics


class ExperimentalProvider:
    name = "Exp."

    def search(self, query: LyricSearchQuery) -> list[LyricCandidate]:
        return []

    def fetch(self, candidate: LyricCandidate) -> ProviderLyrics:
        return ProviderLyrics(
            provider=self.name,
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            synced=False,
            plain_text="",
            confidence=0,
        )
