from __future__ import annotations

import re

from app.export.lrc import LyricLine, clean_lyric_text
from app.transcription.types import TranscriptSegment, WordTiming

LINE_END_RE = re.compile(r"[.!?。！？]$")


def transcript_to_lyric_lines(
    segments: list[TranscriptSegment],
    max_chars: int = 52,
    pause_threshold: float = 0.9,
) -> list[LyricLine]:
    lines: list[LyricLine] = []
    for segment in segments:
        if segment.words:
            lines.extend(_words_to_lines(segment.words, max_chars, pause_threshold))
            continue

        text = clean_lyric_text(segment.text)
        if text:
            lines.append(LyricLine(start=segment.start, text=text))

    return [line for line in lines if line.text]


def _words_to_lines(
    words: list[WordTiming],
    max_chars: int = 52,
    pause_threshold: float = 0.9,
) -> list[LyricLine]:
    lines: list[LyricLine] = []
    current: list[WordTiming] = []
    for word in words:
        text = word.text.strip()
        if not text:
            continue

        if current:
            gap = max(0.0, word.start - current[-1].end)
            current_text = " ".join(item.text.strip() for item in current).strip()
            should_break = (
                gap >= pause_threshold
                or len(current_text) + 1 + len(text) > max_chars
                or LINE_END_RE.search(current[-1].text.strip()) is not None
            )
            if should_break:
                lines.append(_line_from_words(current))
                current = []

        current.append(word)

    if current:
        lines.append(_line_from_words(current))

    return [line for line in lines if line.text]


def _line_from_words(words: list[WordTiming]) -> LyricLine:
    text = " ".join(word.text.strip() for word in words)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return LyricLine(start=words[0].start, text=clean_lyric_text(text))
