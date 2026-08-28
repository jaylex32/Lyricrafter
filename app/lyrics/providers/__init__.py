from __future__ import annotations

from app.lyrics.providers.captions import CaptionProvider
from app.lyrics.providers.experimental import ExperimentalProvider
from app.lyrics.providers.local import LocalProvider
from app.lyrics.providers.lrclib import LRCLIBProvider
from app.lyrics.providers.syncedlyrics_provider import SyncedLyricsProvider
from app.lyrics.types import LyricCandidate, LyricSearchQuery, ProviderLyrics

__all__ = [
    "CaptionProvider",
    "ExperimentalProvider",
    "LRCLIBProvider",
    "LocalProvider",
    "SyncedLyricsProvider",
    "LyricCandidate",
    "LyricSearchQuery",
    "ProviderLyrics",
]
