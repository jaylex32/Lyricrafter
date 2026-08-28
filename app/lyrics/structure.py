from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re
import unicodedata

from app.export.lrc import LyricLine, clean_lyric_text


SECTION_KINDS = (
    "Intro",
    "Verse",
    "Pre-Chorus",
    "Chorus",
    "Post-Chorus",
    "Hook",
    "Bridge",
    "Outro",
)


@dataclass(frozen=True)
class LyricSection:
    id: str
    kind: str
    label: str
    start_row: int
    end_row: int
    start: float
    end: float
    confidence: float
    repeat_group: str | None = None
    source: str = "auto"

    @property
    def line_count(self) -> int:
        return max(0, self.end_row - self.start_row + 1)


@dataclass(frozen=True)
class SectionOverride:
    start_row: int
    end_row: int
    kind: str
    source: str = "manual"


@dataclass(frozen=True)
class SectionLineMapping:
    source_index: int
    target_index: int
    similarity: float


@dataclass(frozen=True)
class SectionRepair:
    lines: list[LyricLine]
    replaced_count: int
    timing_mode: str
    unmatched_source: int = 0
    unmatched_target: int = 0
    confidence: float = 0.0
    mappings: tuple[SectionLineMapping, ...] = ()
    unmatched_source_indices: tuple[int, ...] = ()
    unmatched_target_indices: tuple[int, ...] = ()


@dataclass
class _RepeatGroup:
    intervals: list[tuple[int, int]]
    score: float


def detect_lyric_sections(
    lines: list[LyricLine],
    duration: float | None = None,
    overrides: list[SectionOverride] | None = None,
) -> list[LyricSection]:
    if not lines:
        return []
    track_end = max(float(duration or 0.0), lines[-1].start + 4.0)
    groups = _repeat_groups(lines)
    sections = _sections_from_groups(lines, groups, track_end)
    sections = coalesce_adjacent_choruses(lines, sections)
    if overrides:
        sections = _apply_overrides(lines, sections, overrides, track_end)
    return _renumber_sections(sections)


def coalesce_adjacent_choruses(
    lines: list[LyricLine],
    sections: list[LyricSection],
    max_line_gap: float = 8.0,
) -> list[LyricSection]:
    if not sections:
        return []
    merged: list[LyricSection] = [sections[0]]
    for current in sections[1:]:
        previous = merged[-1]
        line_gap = current.start - lines[previous.end_row].start
        should_merge = (
            previous.kind == "Chorus"
            and current.kind == "Chorus"
            and previous.source == "auto"
            and current.source == "auto"
            and current.start_row == previous.end_row + 1
            and line_gap <= max_line_gap
        )
        if not should_merge:
            merged.append(current)
            continue
        repeat_groups = sorted(
            {
                group
                for section in (previous, current)
                for group in (section.repeat_group or "").split("+")
                if group
            }
        )
        total_lines = max(1, previous.line_count + current.line_count)
        confidence = (
            previous.confidence * previous.line_count + current.confidence * current.line_count
        ) / total_lines
        merged[-1] = LyricSection(
            id=f"chorus-{previous.start_row}-{current.end_row}",
            kind="Chorus",
            label="Chorus",
            start_row=previous.start_row,
            end_row=current.end_row,
            start=previous.start,
            end=current.end,
            confidence=confidence,
            repeat_group="+".join(repeat_groups) or None,
            source="auto",
        )
    return merged


def repair_repeated_section(
    lines: list[LyricLine],
    source: LyricSection,
    target: LyricSection,
) -> SectionRepair:
    source_lines = lines[source.start_row : source.end_row + 1]
    target_lines = lines[target.start_row : target.end_row + 1]
    if not source_lines or not target_lines:
        raise ValueError("Both source and target sections need lyric lines.")
    if source.start_row == target.start_row and source.end_row == target.end_row:
        raise ValueError("Choose a different section to repair.")

    replacement, mappings, unmatched_source_indices, unmatched_target_indices = _timing_safe_replacement(
        source_lines,
        target_lines,
    )
    confidence = _repair_confidence(mappings, len(source_lines), len(target_lines))
    updated = list(lines)
    updated[target.start_row : target.end_row + 1] = replacement
    return SectionRepair(
        updated,
        len(mappings),
        "kept",
        len(unmatched_source_indices),
        len(unmatched_target_indices),
        confidence,
        mappings,
        unmatched_source_indices,
        unmatched_target_indices,
    )


def replace_section_text(
    lines: list[LyricLine],
    target: LyricSection,
    text_lines: list[str],
) -> SectionRepair:
    clean_text = [clean_lyric_text(text) for text in text_lines]
    clean_text = [text for text in clean_text if text]
    target_lines = lines[target.start_row : target.end_row + 1]
    if not clean_text or not target_lines:
        raise ValueError("The section and pasted text must not be empty.")
    source_lines = [LyricLine(start=float(index), text=text) for index, text in enumerate(clean_text)]
    replacement, mappings, unmatched_source_indices, unmatched_target_indices = _timing_safe_replacement(
        source_lines,
        target_lines,
    )
    confidence = _repair_confidence(mappings, len(source_lines), len(target_lines))
    updated = list(lines)
    updated[target.start_row : target.end_row + 1] = replacement
    return SectionRepair(
        updated,
        len(mappings),
        "kept",
        len(unmatched_source_indices),
        len(unmatched_target_indices),
        confidence,
        mappings,
        unmatched_source_indices,
        unmatched_target_indices,
    )


def _repeat_groups(lines: list[LyricLine]) -> list[_RepeatGroup]:
    normalized = [_normalize(line.text) for line in lines]
    token_positions: dict[str, list[int]] = {}
    text_positions: dict[str, list[int]] = {}
    line_tokens: list[set[str]] = []
    for index, value in enumerate(normalized):
        text_positions.setdefault(value, []).append(index)
        tokens = set(value.split())
        line_tokens.append(tokens)
        for token in tokens:
            token_positions.setdefault(token, []).append(index)
    candidates: list[tuple[int, int, int, int, float]] = []
    count = len(lines)
    max_token_occurrences = max(16, min(48, count // 4))
    for left in range(count):
        ranked_tokens = sorted(
            (
                token
                for token in line_tokens[left]
                if 2 <= len(token_positions[token]) <= max_token_occurrences
            ),
            key=lambda token: len(token_positions[token]),
        )[:4]
        possible_rights = {
            index
            for token in ranked_tokens
            for index in token_positions[token]
            if index >= left + 2
        }
        if not possible_rights:
            possible_rights = {
                index for index in text_positions.get(normalized[left], []) if index >= left + 2
            }
        for right in sorted(possible_rights):
            first_score = _text_similarity(normalized[left], normalized[right])
            if first_score < 0.76:
                continue
            left_pos = left
            right_pos = right
            scores: list[float] = []
            matched = 0
            edits = 0
            while left_pos < right and right_pos < count and max(left_pos - left, right_pos - right) < 12:
                score = _text_similarity(normalized[left_pos], normalized[right_pos])
                if score >= 0.68:
                    scores.append(score)
                    matched += 1
                    left_pos += 1
                    right_pos += 1
                    continue
                if edits >= 1:
                    break
                skip_left = (
                    _text_similarity(normalized[left_pos + 1], normalized[right_pos])
                    if left_pos + 1 < right
                    else 0.0
                )
                skip_right = (
                    _text_similarity(normalized[left_pos], normalized[right_pos + 1])
                    if right_pos + 1 < count
                    else 0.0
                )
                next_pair = (
                    _text_similarity(normalized[left_pos + 1], normalized[right_pos + 1])
                    if left_pos + 1 < right and right_pos + 1 < count
                    else 0.0
                )
                if skip_left >= 0.68 or skip_right >= 0.68:
                    if skip_left >= skip_right:
                        left_pos += 1
                    else:
                        right_pos += 1
                    edits += 1
                    continue
                if next_pair >= 0.68:
                    scores.append(0.35)
                    left_pos += 1
                    right_pos += 1
                    edits += 1
                    continue
                break
            left_end = left_pos - 1
            right_end = right_pos - 1
            token_count = sum(len(normalized[index].split()) for index in range(left, left_end + 1))
            if matched >= 2 and token_count >= 6:
                candidates.append((left, left_end, right, right_end, sum(scores) / len(scores)))

    candidates.sort(
        key=lambda item: (min(item[1] - item[0], item[3] - item[2]), item[4]),
        reverse=True,
    )
    groups: list[_RepeatGroup] = []
    for left, left_end, right, right_end, score in candidates:
        first = (left, left_end)
        second = (right, right_end)
        attached = False
        for group in groups:
            if _matches_any(first, group.intervals) and not _overlaps_any(second, group.intervals):
                group.intervals.append(second)
                group.score = max(group.score, score)
                attached = True
                break
            if _matches_any(second, group.intervals) and not _overlaps_any(first, group.intervals):
                group.intervals.append(first)
                group.score = max(group.score, score)
                attached = True
                break
        if attached:
            continue
        if _overlaps_any(first, [item for group in groups for item in group.intervals]):
            continue
        if _overlaps_any(second, [item for group in groups for item in group.intervals]):
            continue
        groups.append(_RepeatGroup([first, second], score))

    for group in groups:
        group.intervals = sorted(set(group.intervals))
    return [group for group in groups if len(group.intervals) >= 2]


def _sections_from_groups(
    lines: list[LyricLine],
    groups: list[_RepeatGroup],
    track_end: float,
) -> list[LyricSection]:
    repeated: list[tuple[int, int, str, float]] = []
    for group_index, group in enumerate(groups, start=1):
        for start_row, end_row in group.intervals:
            repeated.append((start_row, end_row, f"repeat-{group_index}", group.score))
    repeated.sort()
    repeated = _remove_overlapping_intervals(repeated)

    if not repeated:
        ranges = _ranges_from_timing(lines)
        sections = [
            _make_section(lines, start, end, "Verse", 0.58, None, track_end)
            for start, end in ranges
        ]
        if len(sections) > 1 and sections[-1].line_count <= 4:
            sections[-1] = replace(sections[-1], kind="Outro", confidence=0.52)
        return sections

    sections: list[LyricSection] = []
    cursor = 0
    occurrence_count = len(repeated)
    for repeat_index, (start_row, end_row, group_id, score) in enumerate(repeated):
        if cursor < start_row:
            kind = _unique_kind(repeat_index, occurrence_count, start_row - cursor)
            confidence = 0.62 if kind == "Verse" else 0.55
            sections.append(_make_section(lines, cursor, start_row - 1, kind, confidence, None, track_end))
        sections.append(
            _make_section(lines, start_row, end_row, "Chorus", min(0.98, 0.74 + score * 0.24), group_id, track_end)
        )
        cursor = max(cursor, end_row + 1)
    if cursor < len(lines):
        tail_count = len(lines) - cursor
        kind = "Outro" if tail_count <= 5 else "Verse"
        sections.append(_make_section(lines, cursor, len(lines) - 1, kind, 0.55, None, track_end))
    return sections


def _unique_kind(repeat_index: int, occurrence_count: int, line_count: int) -> str:
    if repeat_index == 0:
        return "Verse"
    if occurrence_count >= 3 and repeat_index == occurrence_count - 1 and line_count <= 8:
        return "Bridge"
    return "Verse"


def _ranges_from_timing(lines: list[LyricLine]) -> list[tuple[int, int]]:
    if len(lines) < 2:
        return [(0, len(lines) - 1)]
    gaps = [max(0.0, lines[index + 1].start - lines[index].start) for index in range(len(lines) - 1)]
    typical = sorted(gaps)[len(gaps) // 2] if gaps else 2.5
    boundary = max(7.0, typical * 3.2)
    starts = [0]
    for index, gap in enumerate(gaps):
        if gap >= boundary:
            starts.append(index + 1)
    ranges: list[tuple[int, int]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines) - 1
        ranges.append((start, end))
    return ranges


def _apply_overrides(
    lines: list[LyricLine],
    sections: list[LyricSection],
    overrides: list[SectionOverride],
    track_end: float,
) -> list[LyricSection]:
    metadata: list[tuple[str, float, str | None, str]] = [("Verse", 0.5, None, "auto") for _ in lines]
    for section in sections:
        for row in range(section.start_row, section.end_row + 1):
            metadata[row] = (section.kind, section.confidence, section.repeat_group, section.source)
    for override in overrides:
        start = max(0, min(len(lines) - 1, override.start_row))
        end = max(start, min(len(lines) - 1, override.end_row))
        for row in range(start, end + 1):
            metadata[row] = (override.kind, 1.0, None, override.source)

    rebuilt: list[LyricSection] = []
    start = 0
    current = metadata[0]
    for row in range(1, len(lines) + 1):
        if row == len(lines) or metadata[row] != current:
            kind, confidence, repeat_group, source = current
            rebuilt.append(
                _make_section(lines, start, row - 1, kind, confidence, repeat_group, track_end, source)
            )
            if row < len(lines):
                start = row
                current = metadata[row]
    return rebuilt


def _make_section(
    lines: list[LyricLine],
    start_row: int,
    end_row: int,
    kind: str,
    confidence: float,
    repeat_group: str | None,
    track_end: float,
    source: str = "auto",
) -> LyricSection:
    start = lines[start_row].start
    end = lines[end_row + 1].start if end_row + 1 < len(lines) else track_end
    return LyricSection(
        id=f"{kind.casefold().replace(' ', '-')}-{start_row}-{end_row}",
        kind=kind,
        label=kind,
        start_row=start_row,
        end_row=end_row,
        start=start,
        end=max(start + 0.1, end),
        confidence=max(0.0, min(1.0, confidence)),
        repeat_group=repeat_group,
        source=source,
    )


def _renumber_sections(sections: list[LyricSection]) -> list[LyricSection]:
    totals: dict[str, int] = {}
    for section in sections:
        totals[section.kind] = totals.get(section.kind, 0) + 1
    counters: dict[str, int] = {}
    numbered: list[LyricSection] = []
    for section in sections:
        counters[section.kind] = counters.get(section.kind, 0) + 1
        suffix = f" {counters[section.kind]}" if totals[section.kind] > 1 else ""
        numbered.append(replace(section, label=f"{section.kind}{suffix}"))
    return numbered


def _timing_safe_replacement(
    source_lines: list[LyricLine],
    target_lines: list[LyricLine],
) -> tuple[
    list[LyricLine],
    tuple[SectionLineMapping, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    """Map trusted text onto existing rows without changing any destination timing."""
    if len(source_lines) == len(target_lines):
        replacement = [
            LyricLine(
                start=target_line.start,
                text=source_line.text,
                translation=target_line.translation,
            )
            for source_line, target_line in zip(source_lines, target_lines)
        ]
        mappings = tuple(
            SectionLineMapping(
                source_index=index,
                target_index=index,
                similarity=_text_similarity(_normalize(source.text), _normalize(target.text)),
            )
            for index, (source, target) in enumerate(zip(source_lines, target_lines))
        )
        return replacement, mappings, (), ()

    pairs = _monotonic_line_pairs(source_lines, target_lines)
    mappings = tuple(
        SectionLineMapping(
            source_index=source_index,
            target_index=target_index,
            similarity=_text_similarity(
                _normalize(source_lines[source_index].text),
                _normalize(target_lines[target_index].text),
            ),
        )
        for source_index, target_index in pairs
    )
    replacement = list(target_lines)
    for mapping in mappings:
        source_index = mapping.source_index
        target_index = mapping.target_index
        source_line = source_lines[source_index]
        target_line = target_lines[target_index]
        replacement[target_index] = LyricLine(
            start=target_line.start,
            text=source_line.text,
            translation=target_line.translation,
        )
    mapped_sources = {mapping.source_index for mapping in mappings}
    mapped_targets = {mapping.target_index for mapping in mappings}
    unmatched_sources = tuple(index for index in range(len(source_lines)) if index not in mapped_sources)
    unmatched_targets = tuple(index for index in range(len(target_lines)) if index not in mapped_targets)
    return replacement, mappings, unmatched_sources, unmatched_targets


def _repair_confidence(
    mappings: tuple[SectionLineMapping, ...],
    source_count: int,
    target_count: int,
) -> float:
    if not mappings:
        return 0.0
    coverage = len(mappings) / max(1, max(source_count, target_count))
    text_score = sum(mapping.similarity for mapping in mappings) / len(mappings)
    line_balance = min(source_count, target_count) / max(1, max(source_count, target_count))
    return max(0.0, min(1.0, text_score * 0.55 + coverage * 0.25 + line_balance * 0.20))


def _monotonic_line_pairs(
    source_lines: list[LyricLine],
    target_lines: list[LyricLine],
) -> list[tuple[int, int]]:
    """Match every row from the smaller side to an ordered subset of the larger side."""
    if not source_lines or not target_lines:
        return []
    if len(source_lines) <= len(target_lines):
        selected_targets = _ordered_subset_assignment(source_lines, target_lines)
        return [(source_index, target_index) for source_index, target_index in enumerate(selected_targets)]
    selected_sources = _ordered_subset_assignment(target_lines, source_lines)
    return [(source_index, target_index) for target_index, source_index in enumerate(selected_sources)]


def _ordered_subset_assignment(
    required_lines: list[LyricLine],
    candidate_lines: list[LyricLine],
) -> list[int]:
    """Assign ordered required rows to unique candidate rows with minimum alignment cost."""
    required_count = len(required_lines)
    candidate_count = len(candidate_lines)
    costs = [[float("inf")] * candidate_count for _ in range(required_count)]
    previous = [[-1] * candidate_count for _ in range(required_count)]

    for candidate_index in range(candidate_count):
        if candidate_count - candidate_index < required_count:
            continue
        costs[0][candidate_index] = _line_assignment_cost(
            required_lines[0],
            candidate_lines[candidate_index],
            0,
            candidate_index,
            required_count,
            candidate_count,
        )

    for required_index in range(1, required_count):
        first_candidate = required_index
        last_candidate = candidate_count - (required_count - required_index)
        for candidate_index in range(first_candidate, last_candidate + 1):
            best_previous = min(
                range(required_index - 1, candidate_index),
                key=lambda index: costs[required_index - 1][index],
            )
            costs[required_index][candidate_index] = (
                costs[required_index - 1][best_previous]
                + _line_assignment_cost(
                    required_lines[required_index],
                    candidate_lines[candidate_index],
                    required_index,
                    candidate_index,
                    required_count,
                    candidate_count,
                )
            )
            previous[required_index][candidate_index] = best_previous

    last_index = min(
        range(required_count - 1, candidate_count),
        key=lambda index: costs[-1][index],
    )
    selected = [last_index]
    for required_index in range(required_count - 1, 0, -1):
        last_index = previous[required_index][last_index]
        selected.append(last_index)
    selected.reverse()
    return selected


def _line_assignment_cost(
    required: LyricLine,
    candidate: LyricLine,
    required_index: int,
    candidate_index: int,
    required_count: int,
    candidate_count: int,
) -> float:
    required_position = required_index / max(1, required_count - 1)
    candidate_position = candidate_index / max(1, candidate_count - 1)
    similarity = _text_similarity(_normalize(required.text), _normalize(candidate.text))
    return (1.0 - similarity) * 0.68 + abs(required_position - candidate_position) * 0.32


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", clean_lyric_text(text).casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(overlap, SequenceMatcher(None, left, right, autojunk=False).ratio())


def _matches_any(interval: tuple[int, int], intervals: list[tuple[int, int]]) -> bool:
    return any(_overlap_ratio(interval, other) >= 0.8 for other in intervals)


def _overlaps_any(interval: tuple[int, int], intervals: list[tuple[int, int]]) -> bool:
    return any(not (interval[1] < other[0] or interval[0] > other[1]) for other in intervals)


def _overlap_ratio(left: tuple[int, int], right: tuple[int, int]) -> float:
    overlap = max(0, min(left[1], right[1]) - max(left[0], right[0]) + 1)
    return overlap / max(1, min(left[1] - left[0] + 1, right[1] - right[0] + 1))


def _remove_overlapping_intervals(
    intervals: list[tuple[int, int, str, float]],
) -> list[tuple[int, int, str, float]]:
    selected: list[tuple[int, int, str, float]] = []
    for interval in sorted(intervals, key=lambda item: (item[0], -(item[1] - item[0]), -item[3])):
        if not any(not (interval[1] < item[0] or interval[0] > item[1]) for item in selected):
            selected.append(interval)
    return sorted(selected)
