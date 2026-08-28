from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.export.lrc import LyricLine, clean_lyric_text

LRC_TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
SRT_BLOCK_RE = re.compile(
    r"(?:^\d+\s*)?(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"\d{2}:\d{2}:\d{2}[,.]\d{1,3}\s*(.+?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
VTT_TIMESTAMP_RE = re.compile(
    r"(?:(\d{2}):)?(\d{2}):(\d{2})[.](\d{1,3})\s*-->\s*"
    r"(?:(?:\d{2}:)?\d{2}:\d{2}[.]\d{1,3})\s*(.+?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
TAG_RE = re.compile(r"<[^>]+>")
SECTION_HEADER_RE = re.compile(r"^\[[^\]]+\]$")
INLINE_SECTION_HEADER_RE = re.compile(r"\[[^\]]+\]")
GENIUS_RECOMMENDATION_RE = re.compile(r"^you\s+might\s+also\s+like$", re.IGNORECASE)
GENIUS_CONTRIBUTORS_RE = re.compile(r"^\d+\s+contributors?$", re.IGNORECASE)
GENIUS_EMBED_RE = re.compile(r"^\d*\s*embed$", re.IGNORECASE)
GENIUS_TITLE_RE = re.compile(r"^.+\s+lyrics$", re.IGNORECASE)
GENIUS_NOISE_RE = re.compile(
    r"^(translations?|read more|see .+ live|get tickets|sign up|log in|about|credits|release date)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlainSectionHint:
    kind: str
    start_line: int
    end_line: int


def parse_lrc_text(value: str) -> list[LyricLine]:
    lines: list[LyricLine] = []
    for raw_line in value.splitlines():
        matches = list(LRC_TIMESTAMP_RE.finditer(raw_line))
        if not matches:
            continue
        text = LRC_TIMESTAMP_RE.sub("", raw_line).strip()
        text = clean_lyric_text(text)
        if not text:
            continue
        for match in matches:
            lines.append(LyricLine(start=_lrc_seconds(match), text=text))
    return sorted(lines, key=lambda line: line.start)


def parse_plain_text(value: str) -> list[str]:
    lines, _hints = parse_plain_text_with_sections(value)
    return lines


def parse_plain_text_with_sections(value: str) -> tuple[list[str], list[PlainSectionHint]]:
    lines: list[str] = []
    hints: list[PlainSectionHint] = []
    active_kind: str | None = None
    active_start = 0
    skip_recommendations = False
    for raw_line in value.splitlines():
        text = clean_lyric_text(raw_line)
        if not text:
            continue
        if SECTION_HEADER_RE.match(text):
            skip_recommendations = False
            kind = _section_kind(text)
            if kind:
                if active_kind and len(lines) > active_start:
                    hints.append(PlainSectionHint(active_kind, active_start, len(lines) - 1))
                active_kind = kind
                active_start = len(lines)
            continue
        prefix_header = text.startswith("[")
        inline_headers = INLINE_SECTION_HEADER_RE.findall(text)
        text = clean_lyric_text(INLINE_SECTION_HEADER_RE.sub("", text))
        if not text:
            continue
        if GENIUS_RECOMMENDATION_RE.match(text):
            skip_recommendations = True
            continue
        if skip_recommendations:
            continue
        if _is_plain_text_noise(text, accepted_count=len(lines)):
            continue
        if prefix_header and inline_headers:
            kind = _section_kind(inline_headers[0])
            if kind:
                if active_kind and len(lines) > active_start:
                    hints.append(PlainSectionHint(active_kind, active_start, len(lines) - 1))
                active_kind = kind
                active_start = len(lines)
        lines.append(text)
        if not prefix_header and inline_headers:
            kind = _section_kind(inline_headers[-1])
            if kind:
                if active_kind and len(lines) > active_start:
                    hints.append(PlainSectionHint(active_kind, active_start, len(lines) - 1))
                active_kind = kind
                active_start = len(lines)
    if active_kind and len(lines) > active_start:
        hints.append(PlainSectionHint(active_kind, active_start, len(lines) - 1))
    return lines, hints


def parse_caption_text(value: str, suffix: str) -> list[LyricLine]:
    suffix = suffix.lower()
    pattern = VTT_TIMESTAMP_RE if suffix == ".vtt" else SRT_BLOCK_RE
    lines: list[LyricLine] = []
    for match in pattern.finditer(value):
        text = _caption_text(match.group(match.lastindex or 0))
        if not text:
            continue
        if suffix == ".vtt":
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            millis = int(match.group(4).ljust(3, "0")[:3])
        else:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            millis = int(match.group(4).ljust(3, "0")[:3])
        lines.append(LyricLine(start=(hours * 3600) + (minutes * 60) + seconds + (millis / 1000), text=text))
    return lines


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def _lrc_seconds(match: re.Match[str]) -> float:
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or "0"
    if len(fraction) == 1:
        decimal = int(fraction) / 10
    elif len(fraction) == 2:
        decimal = int(fraction) / 100
    else:
        decimal = int(fraction[:3]) / 1000
    return (minutes * 60) + seconds + decimal


def _caption_text(value: str) -> str:
    text = TAG_RE.sub("", value)
    text = re.sub(r"\{\\.*?\}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return clean_lyric_text(text)


def _is_plain_text_noise(text: str, accepted_count: int) -> bool:
    if GENIUS_CONTRIBUTORS_RE.match(text):
        return True
    if GENIUS_EMBED_RE.match(text):
        return True
    if GENIUS_NOISE_RE.match(text):
        return True
    if accepted_count < 4 and GENIUS_TITLE_RE.match(text):
        return True
    return False


def _section_kind(header: str) -> str | None:
    value = header.strip().strip("[]").split(":", 1)[0].strip().casefold()
    value = value.replace("_", " ").replace("-", " ")
    if value.startswith(("pre chorus", "pre coro", "precoro")):
        return "Pre-Chorus"
    if value.startswith(("post chorus", "post coro", "postcoro")):
        return "Post-Chorus"
    if value.startswith(("chorus", "coro", "estribillo")):
        return "Chorus"
    if value.startswith(("verse", "verso", "estrofa")):
        return "Verse"
    if value.startswith(("bridge", "puente")):
        return "Bridge"
    if value.startswith(("hook", "refrain")):
        return "Hook"
    if value.startswith("intro"):
        return "Intro"
    if value.startswith(("outro", "salida")):
        return "Outro"
    return None
