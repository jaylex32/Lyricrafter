from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.export.lrc import LyricLine, clean_lyric_text

NORMALIZE_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)
TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def align_plain_lyrics(
    timed_lines: list[LyricLine],
    provider_lines: list[str],
    threshold: float = 0.56,
) -> tuple[list[LyricLine], list[str]]:
    clean_provider = [clean_lyric_text(line) for line in provider_lines]
    clean_provider = [line for line in clean_provider if line]
    if not timed_lines or not clean_provider:
        return timed_lines, ["No AI timing or provider text available for alignment."]

    if threshold >= 0.62:
        return _replace_ai_lines_from_provider(timed_lines, clean_provider, threshold)

    aligned, warnings = _align_provider_lines_to_ai_anchors(timed_lines, clean_provider, threshold)
    if aligned:
        return cleanup_aligned_fragments(aligned), warnings
    return _align_by_ordered_chunks(timed_lines, clean_provider, threshold)


def cleanup_aligned_fragments(lines: list[LyricLine]) -> list[LyricLine]:
    cleaned: list[LyricLine] = []
    previous_text = ""
    for line in lines:
        text = clean_lyric_text(line.text)
        if not text:
            continue
        if previous_text and _is_repeated_tail(previous_text, text):
            continue
        cleaned.append(LyricLine(start=line.start, text=text, translation=line.translation))
        previous_text = text
    return cleaned


def confidence_for_candidate(
    query_title: str,
    query_artist: str,
    query_album: str,
    query_duration: int | None,
    title: str,
    artist: str,
    album: str,
    duration: int | None,
    has_synced: bool,
) -> int:
    score = 0.0
    score += _line_score(query_title, title) * 48
    if query_artist and artist:
        score += _line_score(query_artist, artist) * 28
    elif not query_artist:
        score += 12
    if query_album and album:
        score += _line_score(query_album, album) * 10
    if query_duration and duration:
        delta = abs(query_duration - duration)
        score += max(0, 12 - min(delta, 12))
    if has_synced:
        score += 8
    return max(0, min(100, int(round(score))))


def _line_score(left: str, right: str) -> float:
    left_norm = _normalize(left)
    right_norm = _normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return NORMALIZE_RE.sub(" ", value).strip()


def _normalize_token(value: str) -> str:
    return _normalize(value).replace(" ", "")


def _tokens(value: str) -> list[str]:
    return [_normalize_token(match.group(0)) for match in TOKEN_RE.finditer(value) if _normalize_token(match.group(0))]


def _align_provider_lines_to_ai_anchors(
    timed_lines: list[LyricLine],
    provider_lines: list[str],
    threshold: float,
) -> tuple[list[LyricLine], list[str]]:
    anchors = _line_anchors(timed_lines, provider_lines, threshold)
    if not anchors:
        return [], ["No strong AI timing anchors found."]
    anchor_ratio = len(anchors) / max(1, len(provider_lines))
    minimum_ratio = 0.18 if threshold >= 0.62 else 0.10
    if len(provider_lines) >= 12 and len(anchors) < 3:
        return [], ["Not enough strong AI timing anchors found."]
    if len(provider_lines) >= 20 and anchor_ratio < minimum_ratio:
        return [], ["Provider text did not match enough AI-timed lines for safe full alignment."]

    anchor_by_provider = {provider_index: start for provider_index, _timed_index, start, _score in anchors}
    aligned: list[LyricLine | None] = [None] * len(provider_lines)
    warnings: list[str] = []
    for provider_index, start in anchor_by_provider.items():
        aligned[provider_index] = LyricLine(start=start, text=provider_lines[provider_index])

    anchor_indexes = sorted(anchor_by_provider)
    _fill_before_first_anchor(aligned, provider_lines, anchor_indexes[0], anchor_by_provider[anchor_indexes[0]], warnings)
    for left, right in zip(anchor_indexes, anchor_indexes[1:]):
        _fill_between_anchors(
            aligned,
            provider_lines,
            left,
            anchor_by_provider[left],
            right,
            anchor_by_provider[right],
            warnings,
        )
    _fill_after_last_anchor(aligned, provider_lines, anchor_indexes[-1], anchor_by_provider[anchor_indexes[-1]], warnings)

    complete = [line for line in aligned if line is not None]
    weak = sum(1 for warning in warnings if "estimated" in warning)
    if weak:
        warnings.append(f"{weak} line(s) need timing review.")
    return _make_monotonic(complete), warnings


def _line_anchors(
    timed_lines: list[LyricLine],
    provider_lines: list[str],
    threshold: float,
) -> list[tuple[int, int, float, float]]:
    anchors: list[tuple[int, int, float, float]] = []
    timed_index = 0
    for provider_index, provider_line in enumerate(provider_lines):
        best: tuple[int, float, float] | None = None
        for candidate in _timed_candidates(timed_lines, timed_index):
            score = _candidate_score(provider_line, candidate.text)
            adjusted = score - max(0, candidate.start_index - timed_index) * 0.01
            if best is None or adjusted > best[2]:
                best = (candidate.start_index, candidate.start, adjusted)
        if best is None:
            continue
        anchor_threshold = _anchor_threshold(provider_line, threshold)
        if best[2] >= anchor_threshold:
            anchors.append((provider_index, best[0], best[1], best[2]))
            timed_index = best[0] + 1
    return anchors


class _TimedCandidate:
    def __init__(self, start_index: int, start: float, text: str) -> None:
        self.start_index = start_index
        self.start = start
        self.text = text


def _timed_candidates(lines: list[LyricLine], start_index: int, max_chunk: int = 3) -> list[_TimedCandidate]:
    candidates: list[_TimedCandidate] = []
    for index in range(start_index, len(lines)):
        parts: list[str] = []
        for end in range(index, min(len(lines), index + max_chunk)):
            parts.append(lines[end].text)
            candidates.append(_TimedCandidate(index, lines[index].start, " ".join(parts)))
    return candidates


def _anchor_threshold(line: str, threshold: float) -> float:
    token_count = len(_tokens(line))
    if token_count <= 2:
        base = 0.78
    elif token_count <= 4:
        base = 0.70
    else:
        base = 0.58
    if threshold >= 0.62:
        return max(base, threshold)
    if threshold < 0.56 and token_count > 4:
        return max(0.50, threshold)
    if threshold < 0.56 and token_count > 2:
        return max(0.64, threshold)
    return base


def _candidate_score(provider_line: str, timed_text: str) -> float:
    return _text_match_score(provider_line, timed_text)


def _text_match_score(left: str, right: str) -> float:
    base = _line_score(left, right)
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return base
    token_score = SequenceMatcher(None, left_tokens, right_tokens).ratio()
    base = max(base, token_score)
    if len(left_tokens) <= len(right_tokens) and _is_contiguous_subsequence(left_tokens, right_tokens):
        return max(base, 0.94)
    if len(right_tokens) <= len(left_tokens) and _is_contiguous_subsequence(right_tokens, left_tokens):
        return max(base, 0.90)
    if len(left_tokens) >= 4 and right_tokens[: len(left_tokens)] == left_tokens:
        return max(base, 0.86)
    if len(right_tokens) >= 4 and left_tokens[: len(right_tokens)] == right_tokens:
        return max(base, 0.84)
    return base


def _is_contiguous_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    for index in range(0, len(haystack) - len(needle) + 1):
        if haystack[index : index + len(needle)] == needle:
            return True
    return False


def _fill_before_first_anchor(
    aligned: list[LyricLine | None],
    provider_lines: list[str],
    first_index: int,
    first_start: float,
    warnings: list[str],
) -> None:
    start = max(0.0, first_start)
    for index in range(first_index - 1, -1, -1):
        start = max(0.0, start - _estimated_line_gap(provider_lines[index]))
        aligned[index] = LyricLine(start=start, text=provider_lines[index])
        warnings.append(f"Line {index + 1}: timing estimated before first AI anchor.")


def _fill_between_anchors(
    aligned: list[LyricLine | None],
    provider_lines: list[str],
    left_index: int,
    left_start: float,
    right_index: int,
    right_start: float,
    warnings: list[str],
) -> None:
    start = left_start
    missing = right_index - left_index - 1
    if missing > 0 and right_start - left_start <= _distribution_gap_limit(missing):
        step = (right_start - left_start) / (missing + 1)
        for offset, index in enumerate(range(left_index + 1, right_index), start=1):
            start = left_start + (step * offset)
            aligned[index] = LyricLine(start=max(0.0, start), text=provider_lines[index])
            warnings.append(f"Line {index + 1}: timing estimated between AI anchors.")
        return
    for offset, index in enumerate(range(left_index + 1, right_index), start=1):
        remaining = missing - offset + 1
        candidate = start + _estimated_line_gap(provider_lines[index])
        latest = right_start - (0.05 * remaining)
        if candidate >= latest:
            candidate = start + max(0.05, (right_start - start) / (remaining + 1))
        aligned[index] = LyricLine(start=max(0.0, candidate), text=provider_lines[index])
        start = candidate
        warnings.append(f"Line {index + 1}: timing estimated between AI anchors.")


def _fill_after_last_anchor(
    aligned: list[LyricLine | None],
    provider_lines: list[str],
    last_index: int,
    last_start: float,
    warnings: list[str],
) -> None:
    start = last_start
    for index in range(last_index + 1, len(provider_lines)):
        start += _estimated_line_gap(provider_lines[index])
        aligned[index] = LyricLine(start=start, text=provider_lines[index])
        warnings.append(f"Line {index + 1}: timing estimated after last AI anchor.")


def _make_monotonic(lines: list[LyricLine]) -> list[LyricLine]:
    adjusted: list[LyricLine] = []
    previous = -1.0
    for line in lines:
        start = line.start
        if start <= previous:
            start = previous + 0.05
        adjusted.append(LyricLine(start=start, text=line.text, translation=line.translation))
        previous = start
    return adjusted


def _is_repeated_tail(previous: str, current: str) -> bool:
    previous_norm = _normalize(previous)
    current_norm = _normalize(current)
    if previous_norm == current_norm:
        return False
    if not current_norm or len(current_norm.split()) > 4:
        return False
    return previous_norm.endswith(current_norm)


def _estimated_line_gap(line: str) -> float:
    token_count = max(1, len(_tokens(line)))
    return max(0.6, min(2.4, 0.45 + token_count * 0.22))


def _distribution_gap_limit(missing_count: int) -> float:
    return max(5.5, min(10.0, (missing_count + 1) * 3.0))


def _align_by_ordered_chunks(
    timed_lines: list[LyricLine],
    clean_provider: list[str],
    threshold: float,
) -> tuple[list[LyricLine], list[str]]:
    aligned: list[LyricLine] = []
    warnings: list[str] = []
    provider_index = 0

    for row, timed in enumerate(timed_lines, start=1):
        timed_text = clean_lyric_text(timed.text)
        match = _best_ordered_chunk(timed_text, clean_provider, provider_index)
        if match and match.score >= threshold:
            provider_index = match.end
            aligned.append(LyricLine(timed.start, " ".join(clean_provider[match.start : match.end]), timed.translation))
        else:
            aligned.append(timed)
            warnings.append(f"Line {row}: provider text match was weak.")
            if match and match.score >= 0.42:
                provider_index = match.end

    if provider_index < len(clean_provider):
        warnings.append(f"{len(clean_provider) - provider_index} provider line(s) were not matched to AI timing.")
    return cleanup_aligned_fragments(aligned), warnings


def _replace_ai_lines_from_provider(
    timed_lines: list[LyricLine],
    clean_provider: list[str],
    threshold: float,
) -> tuple[list[LyricLine], list[str]]:
    aligned: list[LyricLine] = []
    warnings: list[str] = []
    provider_index = 0
    replaced = 0

    for row, timed in enumerate(timed_lines, start=1):
        timed_text = clean_lyric_text(timed.text)
        match = _best_ordered_chunk(
            timed_text,
            clean_provider,
            provider_index,
            max_skip=10,
            max_chunk=4,
        )
        if match and match.score >= threshold:
            provider_index = match.end
            replacement = " ".join(clean_provider[match.start : match.end])
            aligned.append(LyricLine(timed.start, replacement, timed.translation))
            replaced += 1
            continue
        aligned.append(timed)
        warnings.append(f"Line {row}: kept AI text because provider match was weak.")

    if replaced == 0:
        warnings.append("No provider lines were matched safely; AI timing and text were preserved.")
    else:
        warnings.append(f"Safely replaced {replaced} of {len(timed_lines)} AI-timed line(s).")
    if provider_index < len(clean_provider):
        warnings.append(f"{len(clean_provider) - provider_index} provider line(s) were not used.")
    return cleanup_aligned_fragments(aligned), warnings


class _ChunkMatch:
    def __init__(self, start: int, end: int, score: float) -> None:
        self.start = start
        self.end = end
        self.score = score


def _best_ordered_chunk(
    timed_text: str,
    provider_lines: list[str],
    provider_index: int,
    max_skip: int = 0,
    max_chunk: int = 4,
) -> _ChunkMatch | None:
    best: _ChunkMatch | None = None
    upper_start = min(len(provider_lines), provider_index + max_skip + 1)
    for start in range(provider_index, upper_start):
        for end in range(start + 1, min(len(provider_lines), start + max_chunk) + 1):
            chunk = " ".join(provider_lines[start:end])
            score = _text_match_score(timed_text, chunk)
            skip_penalty = max(0, start - provider_index) * 0.04
            length_penalty = min(0.20, abs(len(_tokens(timed_text)) - len(_tokens(chunk))) * 0.02)
            adjusted = score - skip_penalty - length_penalty
            if best is None or adjusted > best.score:
                best = _ChunkMatch(start, end, adjusted)
    return best
