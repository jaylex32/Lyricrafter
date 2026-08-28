from __future__ import annotations

from dataclasses import dataclass

from app.export.lrc import LyricLine, clean_lyric_text


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    row: int | None
    message: str


def check_lyrics_quality(lines: list[LyricLine]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if not lines:
        return [QualityIssue("Error", None, "No lyric lines are loaded.")]

    previous_start: float | None = None
    previous_text = ""
    for index, line in enumerate(lines):
        row = index + 1
        text = clean_lyric_text(line.text)
        if not text:
            issues.append(QualityIssue("Error", row, "Empty or artifact-only lyric line."))
        if line.start < 0:
            issues.append(QualityIssue("Error", row, "Timestamp is negative."))
        if previous_start is not None:
            gap = line.start - previous_start
            if gap < 0:
                issues.append(QualityIssue("Error", row, "Timestamp is earlier than the previous line."))
            elif gap < 0.25:
                issues.append(QualityIssue("Warning", row, "Line starts less than 0.25s after the previous line."))
            elif gap > 14:
                issues.append(QualityIssue("Review", row, f"Long silence or missing lyric before this line ({gap:.1f}s gap)."))
        if len(text) > 95:
            issues.append(QualityIssue("Review", row, "Line is very long; consider splitting for readability."))
        if len(text.split()) > 16:
            issues.append(QualityIssue("Review", row, "Line has many words; consider splitting for better sync."))
        if previous_text and text.casefold() == previous_text.casefold() and previous_start is not None:
            if abs(line.start - previous_start) < 0.5:
                issues.append(QualityIssue("Warning", row, "Near-duplicate line very close to previous line."))
        previous_start = line.start
        previous_text = text

    if not issues:
        issues.append(QualityIssue("Pass", None, "No obvious timing or cleanup issues found."))
    return issues


def format_quality_report(issues: list[QualityIssue]) -> str:
    rows: list[str] = []
    for issue in issues:
        location = f"Line {issue.row}: " if issue.row is not None else ""
        rows.append(f"{issue.severity}: {location}{issue.message}")
    return "\n".join(rows)


def quality_score(issues: list[QualityIssue]) -> int:
    penalties = {"Error": 18, "Warning": 7, "Review": 3}
    penalty = sum(penalties.get(issue.severity, 0) for issue in issues)
    return max(0, min(100, 100 - penalty))


def quality_label(score: int) -> str:
    if score >= 95:
        return "Ready"
    if score >= 82:
        return "Good"
    if score >= 65:
        return "Review"
    return "Needs work"
