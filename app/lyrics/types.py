from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.export.lrc import LyricLine


@dataclass(frozen=True)
class LyricSearchQuery:
    source_path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: int | None = None
    isrc: str = ""


@dataclass(frozen=True)
class LyricCandidate:
    provider: str
    title: str
    artist: str = ""
    album: str = ""
    synced: bool = False
    confidence: int = 0
    language: str = ""
    source_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return "Synced" if self.synced else "Plain"


@dataclass(frozen=True)
class ProviderLyrics:
    provider: str
    title: str
    artist: str = ""
    album: str = ""
    synced: bool = False
    lines: list[LyricLine] = field(default_factory=list)
    plain_text: str = ""
    confidence: int = 0
    language: str = ""
