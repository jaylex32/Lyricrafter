from app.core.quality import check_lyrics_quality, format_quality_report, quality_label, quality_score
from app.export.lrc import LyricLine


def test_quality_check_reports_pass_for_clean_lines() -> None:
    issues = check_lyrics_quality([LyricLine(1, "First line"), LyricLine(4, "Second line")])

    assert issues[0].severity == "Pass"


def test_quality_check_flags_timing_and_length_issues() -> None:
    issues = check_lyrics_quality(
        [
            LyricLine(2, "First line"),
            LyricLine(1, "Earlier line"),
            LyricLine(1.1, " ".join(["word"] * 17)),
        ]
    )
    report = format_quality_report(issues)

    assert "earlier than the previous line" in report
    assert "many words" in report


def test_quality_score_rewards_clean_lyrics_and_penalizes_errors() -> None:
    clean = check_lyrics_quality([LyricLine(1, "First line"), LyricLine(4, "Second line")])
    broken = check_lyrics_quality([LyricLine(2, "First"), LyricLine(1, "Second")])

    assert quality_score(clean) == 100
    assert quality_score(broken) < quality_score(clean)
    assert quality_label(quality_score(clean)) == "Ready"
