from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LyricLine:
    start: float
    text: str
    translation: str | None = None


BRACKET_ARTIFACT_RE = re.compile(r"\[(?:music|applause|laughter|silence|noise)\]", re.IGNORECASE)
OUTRO_ARTIFACT_RE = re.compile(
    r"^(?:"
    r"thanks?\s+for\s+watching"
    r"|thank\s+you\s+for\s+watching"
    r"|please\s+subscribe"
    r"|[¡!]*\s*suscr[ií]bete"
    r"|subt[ií]tulos?\s+por(?:\s+la\s+comunidad\s+de)?(?:\s+amara\.org)?"
    r"|like\s+and\s+subscribe"
    r"|subscribe\s+for\s+more"
    r"|see\s+you\s+next\s+time"
    r")[.!?\s]*$",
    re.IGNORECASE,
)


def clean_lyric_text(text: str) -> str:
    text = BRACKET_ARTIFACT_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return "" if OUTRO_ARTIFACT_RE.match(text) else text


def format_lrc_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_hundredths = int(round(seconds * 100))
    minutes, hundredths_remaining = divmod(total_hundredths, 60 * 100)
    whole_seconds, hundredths = divmod(hundredths_remaining, 100)
    return f"[{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}]"


def render_lrc(lines: list[LyricLine]) -> str:
    rendered = []
    for line in lines:
        text = clean_lyric_text(line.text)
        if text:
            rendered.append(f"{format_lrc_timestamp(line.start)} {text}")
    return "\n".join(rendered) + ("\n" if rendered else "")


def render_txt(lines: list[LyricLine]) -> str:
    rendered = [clean_lyric_text(line.text) for line in lines]
    rendered = [line for line in rendered if line]
    return "\n".join(rendered) + ("\n" if rendered else "")


def render_srt(lines: list[LyricLine]) -> str:
    rendered: list[str] = []
    clean_lines = [line for line in lines if clean_lyric_text(line.text)]
    for index, line in enumerate(clean_lines, start=1):
        end = _line_end(clean_lines, index - 1)
        rendered.append(
            f"{index}\n"
            f"{_format_srt_time(line.start)} --> {_format_srt_time(end)}\n"
            f"{clean_lyric_text(line.text)}"
        )
    return "\n\n".join(rendered) + ("\n" if rendered else "")


def render_vtt(lines: list[LyricLine]) -> str:
    rendered = ["WEBVTT"]
    clean_lines = [line for line in lines if clean_lyric_text(line.text)]
    for index, line in enumerate(clean_lines):
        end = _line_end(clean_lines, index)
        rendered.append(
            f"{_format_vtt_time(line.start)} --> {_format_vtt_time(end)}\n"
            f"{clean_lyric_text(line.text)}"
        )
    return "\n\n".join(rendered) + "\n"


def render_bilingual_txt(lines: list[LyricLine]) -> str:
    rendered: list[str] = []
    for line in lines:
        original = clean_lyric_text(line.text)
        translation = clean_lyric_text(line.translation or "")
        if original:
            rendered.append(original)
        if translation:
            rendered.append(translation)
    return "\n".join(rendered) + ("\n" if rendered else "")


def render_translated_lrc(lines: list[LyricLine]) -> str:
    rendered = []
    for line in lines:
        text = clean_lyric_text(line.translation or "")
        if text:
            rendered.append(f"{format_lrc_timestamp(line.start)} {text}")
    return "\n".join(rendered) + ("\n" if rendered else "")


def render_bilingual_lrc(lines: list[LyricLine]) -> str:
    rendered = []
    for line in lines:
        original = clean_lyric_text(line.text)
        translation = clean_lyric_text(line.translation or "")
        if original:
            rendered.append(f"{format_lrc_timestamp(line.start)} {original}")
        if translation:
            rendered.append(f"{format_lrc_timestamp(line.start)} {translation}")
    return "\n".join(rendered) + ("\n" if rendered else "")


def cleanup_lyric_lines(lines: list[LyricLine]) -> list[LyricLine]:
    cleaned: list[LyricLine] = []
    previous_text = ""
    previous_start = -999.0
    for line in lines:
        text = clean_lyric_text(line.text)
        translation = clean_lyric_text(line.translation or "") or None
        if not text:
            continue
        if text.casefold() == previous_text.casefold() and abs(line.start - previous_start) < 0.35:
            continue
        cleaned.append(LyricLine(start=line.start, text=text, translation=translation))
        previous_text = text
        previous_start = line.start
    return cleaned


def _line_end(lines: list[LyricLine], index: int) -> float:
    start = lines[index].start
    if index + 1 < len(lines):
        return max(start + 0.4, lines[index + 1].start - 0.05)
    return start + max(1.5, min(4.0, 0.7 + len(_words(lines[index].text)) * 0.18))


def _format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis_total = int(round(seconds * 1000))
    hours, remaining = divmod(millis_total, 3_600_000)
    minutes, remaining = divmod(remaining, 60_000)
    whole_seconds, millis = divmod(remaining, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def _format_vtt_time(seconds: float) -> str:
    return _format_srt_time(seconds).replace(",", ".")


def _words(text: str) -> list[str]:
    return [word for word in clean_lyric_text(text).split() if word]
