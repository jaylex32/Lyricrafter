from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WordTiming:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[WordTiming] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptionResult:
    language: str | None
    duration: float | None
    segments: list[TranscriptSegment]
