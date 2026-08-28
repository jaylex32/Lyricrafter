from app.export.lrc import LyricLine
from app.lyrics.structure import (
    LyricSection,
    SectionOverride,
    coalesce_adjacent_choruses,
    detect_lyric_sections,
    repair_repeated_section,
    replace_section_text,
)


def _song_lines() -> list[LyricLine]:
    text = [
        "First verse opens the story",
        "A different line moves along",
        "We rise together tonight",
        "Nothing can stand in our way",
        "Second verse changes the picture",
        "Another new line carries on",
        "We rise together tonight",
        "Nothing can stand in our way",
        "A quiet turn changes everything",
        "This moment belongs on its own",
        "We rise together tonight",
        "Nothing can stand in our way",
        "One final word before goodbye",
    ]
    return [LyricLine(index * 3.0, value) for index, value in enumerate(text)]


def test_detects_repeated_choruses_and_late_bridge() -> None:
    sections = detect_lyric_sections(_song_lines(), duration=42.0)

    assert [section.kind for section in sections] == [
        "Verse",
        "Chorus",
        "Verse",
        "Chorus",
        "Bridge",
        "Chorus",
        "Outro",
    ]
    choruses = [section for section in sections if section.kind == "Chorus"]
    assert len(choruses) == 3
    assert len({section.repeat_group for section in choruses}) == 1
    assert choruses[0].label == "Chorus 1"


def test_manual_override_relabels_selected_rows() -> None:
    lines = _song_lines()
    sections = detect_lyric_sections(
        lines,
        duration=42.0,
        overrides=[SectionOverride(start_row=0, end_row=1, kind="Intro")],
    )

    assert sections[0].kind == "Intro"
    assert sections[0].source == "manual"
    assert sections[0].confidence == 1.0


def test_repair_repeat_keeps_destination_timestamps() -> None:
    lines = _song_lines()
    lines[6] = LyricLine(lines[6].start, "Incorrect chorus line")
    sections = detect_lyric_sections(_song_lines(), duration=42.0)
    choruses = [section for section in sections if section.kind == "Chorus"]

    repair = repair_repeated_section(lines, choruses[0], choruses[1])

    repaired = repair.lines[choruses[1].start_row : choruses[1].end_row + 1]
    assert [line.start for line in repaired] == [18.0, 21.0]
    assert [line.text for line in repaired] == [
        "We rise together tonight",
        "Nothing can stand in our way",
    ]
    assert repair.timing_mode == "kept"


def test_paste_with_extra_line_keeps_target_rows_and_timestamps() -> None:
    lines = _song_lines()
    target = [section for section in detect_lyric_sections(lines, 42.0) if section.kind == "Chorus"][1]

    repair = replace_section_text(lines, target, ["First", "Missing middle", "Last"])
    repaired = repair.lines[target.start_row : target.end_row + 1]

    assert len(repair.lines) == len(lines)
    assert [line.start for line in repaired] == [18.0, 21.0]
    assert len(repaired) == target.line_count
    assert repair.replaced_count == 2
    assert repair.unmatched_source == 1
    assert repair.unmatched_target == 0
    assert repair.timing_mode == "kept"
    assert repair.unmatched_source_indices == (1,)
    assert len(repair.mappings) == 2


def test_detector_and_repair_tolerate_a_missing_chorus_line() -> None:
    text = [
        "Verse begins with a unique thought",
        "Another unique verse line appears",
        "We are running through the fire",
        "Holding on through every night",
        "We will always rise again",
        "Second verse tells another story",
        "Clouds gather around the sleeping city",
        "We are running through the fire",
        "We will always rise again",
    ]
    lines = [LyricLine(index * 3.0, value) for index, value in enumerate(text)]
    sections = detect_lyric_sections(lines, duration=30.0)
    choruses = [section for section in sections if section.kind == "Chorus"]

    assert [(section.start_row, section.end_row) for section in choruses] == [(2, 4), (7, 8)]
    repair = repair_repeated_section(lines, choruses[0], choruses[1])
    repaired = repair.lines[choruses[1].start_row : choruses[1].end_row + 1]
    assert len(repair.lines) == len(lines)
    assert [line.start for line in repaired] == [21.0, 24.0]
    assert repair.replaced_count == 2
    assert repair.unmatched_source == 1
    assert repair.unmatched_target == 0
    assert repair.timing_mode == "kept"
    assert repair.confidence > 0.0


def test_shorter_master_leaves_unmatched_destination_row_and_timing_untouched() -> None:
    lines = [
        LyricLine(10.0, "Sing into the night"),
        LyricLine(12.0, "We will rise"),
        LyricLine(30.0, "Sing into night"),
        LyricLine(32.0, "Unexpected extra phrase"),
        LyricLine(34.0, "We rise"),
    ]
    source = LyricSection("source", "Chorus", "Chorus 1", 0, 1, 10.0, 14.0, 1.0)
    target = LyricSection("target", "Chorus", "Chorus 2", 2, 4, 30.0, 36.0, 1.0)

    repair = repair_repeated_section(lines, source, target)

    repaired = repair.lines[2:5]
    assert len(repair.lines) == len(lines)
    assert [line.start for line in repaired] == [30.0, 32.0, 34.0]
    assert repaired[0].text == "Sing into the night"
    assert repaired[1].text == "Unexpected extra phrase"
    assert repaired[2].text == "We will rise"
    assert repair.unmatched_source == 0
    assert repair.unmatched_target == 1
    assert repair.unmatched_target_indices == (1,)
    assert [mapping.target_index for mapping in repair.mappings] == [0, 2]


def test_repair_confidence_rewards_matching_text_and_equal_structure() -> None:
    matching = [
        LyricLine(10.0, "We rise together"),
        LyricLine(12.0, "Into the night"),
        LyricLine(30.0, "We rise together"),
        LyricLine(32.0, "Into the night"),
    ]
    unrelated = list(matching)
    unrelated[2] = LyricLine(30.0, "Completely different phrase")
    unrelated[3] = LyricLine(32.0, "Nothing matches here")
    source = LyricSection("source", "Chorus", "Chorus 1", 0, 1, 10.0, 14.0, 1.0)
    target = LyricSection("target", "Chorus", "Chorus 2", 2, 3, 30.0, 34.0, 1.0)

    matching_repair = repair_repeated_section(matching, source, target)
    unrelated_repair = repair_repeated_section(unrelated, source, target)

    assert matching_repair.confidence == 1.0
    assert unrelated_repair.confidence < matching_repair.confidence


def test_adjacent_auto_chorus_fragments_are_coalesced() -> None:
    lines = [LyricLine(index * 2.0, f"Line {index}") for index in range(6)]
    sections = [
        LyricSection("verse", "Verse", "Verse", 0, 1, 0.0, 4.0, 0.7),
        LyricSection("chorus-a", "Chorus", "Chorus", 2, 3, 4.0, 8.0, 0.96, "repeat-1"),
        LyricSection("chorus-b", "Chorus", "Chorus", 4, 5, 8.0, 12.0, 0.92, "repeat-2"),
    ]

    merged = coalesce_adjacent_choruses(lines, sections)

    assert len(merged) == 2
    assert (merged[1].start_row, merged[1].end_row) == (2, 5)
    assert merged[1].repeat_group == "repeat-1+repeat-2"


def test_adjacent_source_labeled_choruses_remain_separate() -> None:
    lines = [LyricLine(index * 2.0, f"Line {index}") for index in range(4)]
    sections = [
        LyricSection("a", "Chorus", "Chorus", 0, 1, 0.0, 4.0, 1.0, source="Genius"),
        LyricSection("b", "Chorus", "Chorus", 2, 3, 4.0, 8.0, 1.0, source="Genius"),
    ]

    assert coalesce_adjacent_choruses(lines, sections) == sections
