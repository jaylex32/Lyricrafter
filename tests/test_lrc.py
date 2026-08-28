from app.export.lrc import (
    LyricLine,
    format_lrc_timestamp,
    render_bilingual_lrc,
    render_bilingual_txt,
    cleanup_lyric_lines,
    render_lrc,
    render_srt,
    render_translated_lrc,
    render_txt,
    render_vtt,
)
from app.transcription.lyrics import transcript_to_lyric_lines
from app.transcription.types import TranscriptSegment, WordTiming


def test_format_lrc_timestamp() -> None:
    assert format_lrc_timestamp(0) == "[00:00.00]"
    assert format_lrc_timestamp(65.432) == "[01:05.43]"
    assert format_lrc_timestamp(-2) == "[00:00.00]"


def test_render_lrc_and_txt_clean_artifacts() -> None:
    lines = [
        LyricLine(1.2, " Hello   world "),
        LyricLine(3.4, "[Music] Another line"),
    ]

    assert render_lrc(lines) == "[00:01.20] Hello world\n[00:03.40] Another line\n"
    assert render_txt(lines) == "Hello world\nAnother line\n"


def test_render_srt_and_vtt_from_lyric_timing() -> None:
    lines = [LyricLine(1.2, "Hello world"), LyricLine(3.4, "Another line")]

    assert "00:00:01,200 --> 00:00:03,350" in render_srt(lines)
    assert render_vtt(lines).startswith("WEBVTT\n\n00:00:01.200 --> 00:00:03.350")


def test_render_filters_common_whisper_outro_hallucinations() -> None:
    lines = [
        LyricLine(1.2, "Real lyric"),
        LyricLine(9.9, "Thanks for watching!"),
        LyricLine(11.0, "Like and subscribe"),
        LyricLine(12.0, "¡SUSCRÍBETE!"),
        LyricLine(13.0, "Subtítulos por la comunidad de Amara.org"),
    ]

    assert render_lrc(lines) == "[00:01.20] Real lyric\n"
    assert render_txt(lines) == "Real lyric\n"


def test_transcript_to_lyric_lines_preserves_segments_without_words() -> None:
    lines = transcript_to_lyric_lines(
        [
            TranscriptSegment(
                start=0.0,
                end=1.0,
                text="First line",
                words=[WordTiming(0.0, 0.4, "First"), WordTiming(0.5, 0.9, "line")],
            ),
            TranscriptSegment(start=2.0, end=3.0, text="Second line without word timings"),
        ]
    )

    assert [line.text for line in lines] == ["First line", "Second line without word timings"]


def test_bilingual_renderers() -> None:
    lines = [
        LyricLine(1.0, "Hola", "Hello"),
        LyricLine(2.0, "Mundo", "World"),
    ]

    assert render_translated_lrc(lines) == "[00:01.00] Hello\n[00:02.00] World\n"
    assert render_bilingual_lrc(lines) == (
        "[00:01.00] Hola\n[00:01.00] Hello\n[00:02.00] Mundo\n[00:02.00] World\n"
    )
    assert render_bilingual_txt(lines) == "Hola\nHello\nMundo\nWorld\n"


def test_cleanup_lyric_lines_removes_artifacts_and_near_duplicates() -> None:
    lines = [
        LyricLine(1.0, " Hello   world "),
        LyricLine(1.2, "Hello world"),
        LyricLine(4.0, "Thanks for watching!"),
        LyricLine(5.0, "Next line"),
    ]

    assert cleanup_lyric_lines(lines) == [
        LyricLine(1.0, "Hello world", None),
        LyricLine(5.0, "Next line", None),
    ]
