from pathlib import Path

from app.export.lrc import LyricLine
from app.lyrics.align import align_plain_lyrics, confidence_for_candidate
from app.lyrics.parsing import parse_lrc_text, parse_plain_text, parse_plain_text_with_sections
from app.lyrics.providers.local import LocalProvider
from app.lyrics.providers.lrclib import LRCLIBProvider
from app.lyrics.providers.syncedlyrics_provider import SyncedLyricsProvider
from app.lyrics.service import LyricsSourceService
from app.lyrics.types import LyricSearchQuery


def test_parse_lrc_text_supports_multiple_timestamps() -> None:
    lines = parse_lrc_text("[00:01.20][00:03.40] Hello\n[01:02.5] World")

    assert lines == [
        LyricLine(1.2, "Hello"),
        LyricLine(3.4, "Hello"),
        LyricLine(62.5, "World"),
    ]


def test_local_provider_finds_sidecar_lrc_and_txt(tmp_path: Path) -> None:
    source = tmp_path / "Artist - Song.flac"
    source.write_bytes(b"fake")
    source.with_suffix(".lrc").write_text("[00:01.00] Hello\n", encoding="utf-8")
    source.with_suffix(".txt").write_text("Hello\nworld\n", encoding="utf-8")
    query = LyricSearchQuery(source_path=source, title="Song", artist="Artist")

    candidates = LocalProvider().search(query)

    assert [candidate.kind for candidate in candidates] == ["Synced", "Plain"]
    assert LocalProvider().fetch(candidates[0]).lines == [LyricLine(1.0, "Hello")]


def test_lrclib_provider_parses_search_response(monkeypatch) -> None:
    def fake_json(_url: str):
        return [
            {
                "id": 123,
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 180,
                "lang": "en",
                "plainLyrics": "Hello",
                "syncedLyrics": "[00:01.00] Hello",
            }
        ]

    monkeypatch.setattr("app.lyrics.providers.lrclib._get_json", fake_json)
    query = LyricSearchQuery(
        source_path=Path("song.flac"),
        title="Song",
        artist="Artist",
        album="Album",
        duration=180,
    )

    candidates = LRCLIBProvider().search(query)
    lyrics = LRCLIBProvider().fetch(candidates[0])

    assert candidates[0].provider == "LRCLIB"
    assert candidates[0].synced is True
    assert candidates[0].confidence >= 90
    assert lyrics.lines == [LyricLine(1.0, "Hello")]


def test_syncedlyrics_provider_returns_synced_and_genius_plain(monkeypatch) -> None:
    def fake_search(search_term: str, provider: str, synced_only: bool):
        assert search_term == "Artist Song"
        if provider == "NetEase" and synced_only:
            return "[00:01.00] Hello"
        if provider == "Genius" and not synced_only:
            return "[Verse]\nHello from Genius"
        return None

    monkeypatch.setattr("app.lyrics.providers.syncedlyrics_provider._search_syncedlyrics", fake_search)
    query = LyricSearchQuery(source_path=Path("Artist - Song.flac"), title="Song", artist="Artist", duration=180)

    candidates = SyncedLyricsProvider().search(query)

    assert [candidate.provider for candidate in candidates] == ["Synced/NetEase", "Synced/Genius"]
    assert candidates[0].synced is True
    assert candidates[1].synced is False
    assert SyncedLyricsProvider().fetch(candidates[0]).lines == [LyricLine(1.0, "Hello")]
    assert "Hello from Genius" in SyncedLyricsProvider().fetch(candidates[1]).plain_text


def test_service_fetches_syncedlyrics_subprovider_when_disabled_in_dialog_fetch_path(monkeypatch) -> None:
    def fake_search(_search_term: str, provider: str, synced_only: bool):
        if provider == "Genius" and not synced_only:
            return "Hello from Genius"
        return None

    monkeypatch.setattr("app.lyrics.providers.syncedlyrics_provider._search_syncedlyrics", fake_search)
    service = LyricsSourceService({"synced": True})
    query = LyricSearchQuery(source_path=Path("Artist - Song.flac"), title="Song", artist="Artist")

    candidate = service.search(query)[0]
    lyrics = service.fetch(candidate)

    assert candidate.provider == "Synced/Genius"
    assert lyrics.provider == "Synced/Genius"
    assert lyrics.plain_text == "Hello from Genius"


def test_plain_provider_lyrics_align_to_ai_timing() -> None:
    timed = [LyricLine(1.0, "helo wrld"), LyricLine(5.0, "second line")]
    aligned, warnings = align_plain_lyrics(timed, ["Hello world", "Second line"])

    assert aligned == [LyricLine(1.0, "Hello world"), LyricLine(5.0, "Second line")]
    assert warnings == []


def test_plain_alignment_preserves_copied_line_breaks_with_ai_timing() -> None:
    timed = [
        LyricLine(9.38, "alpha river moves tonight."),
        LyricLine(14.16, "silver lights return."),
    ]
    copied = ["Alpha river", "Moves tonight", "Silver lights return"]

    aligned, warnings = align_plain_lyrics(timed, copied)

    assert [line.text for line in aligned] == ["Alpha river", "Moves tonight", "Silver lights return"]
    assert aligned[0].start == 9.38
    assert 11.5 < aligned[1].start < 12.5
    assert aligned[2].start == 14.16
    assert warnings


def test_parse_plain_text_removes_genius_headers_and_recommendations() -> None:
    text = """
    4 Contributors
    MAS DE TI Lyrics
    [Coro: Artist]
    First lyric
    You might also like
    Unrelated Song
    Another Artist
    [Verso 1: Artist]
    Second lyric
    """

    assert parse_plain_text(text) == ["First lyric", "Second lyric"]


def test_plain_parser_preserves_genius_section_hints() -> None:
    lines, hints = parse_plain_text_with_sections(
        "[Verse 1: Artist]\nOpening line\nSecond line\n[Chorus]\nRepeat one\nRepeat two"
    )

    assert lines == ["Opening line", "Second line", "Repeat one", "Repeat two"]
    assert [(hint.kind, hint.start_line, hint.end_line) for hint in hints] == [
        ("Verse", 0, 1),
        ("Chorus", 2, 3),
    ]


def test_parse_plain_text_removes_inline_genius_section_headers() -> None:
    text = """
    Pero debo olvidarte, bebé[Pre-Coro]
    Y sé que está mal olvidarme de lo de nosotro'
    Y espero que te olvides de mí (Zion, baby)[Verso 1]
    """

    assert parse_plain_text(text) == [
        "Pero debo olvidarte, bebé",
        "Y sé que está mal olvidarme de lo de nosotro'",
        "Y espero que te olvides de mí (Zion, baby)",
    ]


def test_strict_plain_alignment_keeps_ai_timing_and_does_not_insert_provider_noise() -> None:
    timed = [
        LyricLine(184.05, "Agua bendita que calma esta sed"),
        LyricLine(186.26, "La vieja me dice cuándo voy a verla"),
        LyricLine(191.35, "Conmigo brillaba como estrella"),
        LyricLine(200.64, "Pero debo olvidarte, bebe"),
        LyricLine(203.04, "Y se que esta mal olvidarme de lo"),
    ]
    copied = parse_plain_text(
        """
        4 Contributors
        MAS DE TI Lyrics
        Yeah
        Woah, woah, oh, oh
        Agua bendita que calma esta sed
        La vieja me dice cuándo voy a verla
        Conmigo brillaba' como estrella
        Pero debo olvidarte, bebé[Pre-Coro]
        Y sé que está mal olvidarme de lo de nosotro'
        """
    )

    aligned, warnings = align_plain_lyrics(timed, copied, threshold=0.68)

    assert [line.start for line in aligned] == [line.start for line in timed]
    assert len(aligned) == len(timed)
    assert aligned[0].text == "Agua bendita que calma esta sed"
    assert aligned[2].text == "Conmigo brillaba' como estrella"
    assert all("Contributors" not in line.text and "Lyrics" not in line.text for line in aligned)
    assert warnings


def test_alignment_rejects_false_late_anchor_after_repeated_section() -> None:
    timed = [
        LyricLine(120.0, "bright signal calls the marker"),
        LyricLine(132.0, "steady motion over glass"),
        LyricLine(134.5, "open window turning slowly"),
        LyricLine(196.0, "bright bright signal"),
        LyricLine(200.0, "closing pattern returns"),
    ]
    copied = [
        "Bright signal calls the marker",
        "Small bridge line",
        "Steady motion over glass",
        "Open window turning slowly",
        "Closing pattern returns",
    ]

    aligned, warnings = align_plain_lyrics(timed, copied)

    assert [line.text for line in aligned[:4]] == copied[:4]
    assert 120 <= aligned[1].start < 130
    assert aligned[2].start == 132.0
    assert aligned[3].start == 134.5
    assert warnings


def test_alignment_trusts_strong_ai_anchor_after_long_intro_gap() -> None:
    timed = [
        LyricLine(8.0, "first verse opening line"),
        LyricLine(26.0, "second verse line should not pull forward"),
        LyricLine(30.0, "third verse line"),
    ]
    copied = [
        "First verse opening line",
        "Bridge lyric near the opening",
        "Second verse line should not pull forward",
    ]

    aligned, warnings = align_plain_lyrics(timed, copied)

    assert aligned[0].start == 8.0
    assert 9.0 <= aligned[1].start <= 11.0
    assert aligned[2].start == 26.0
    assert warnings


def test_cleanup_keeps_intentional_repeated_lyrics() -> None:
    timed = [
        LyricLine(10.0, "you are shallow"),
        LyricLine(12.0, "you are shallow"),
        LyricLine(14.0, "you are shallow"),
    ]
    copied = ["You are shallow", "You are shallow", "You are shallow"]

    aligned, warnings = align_plain_lyrics(timed, copied)

    assert [line.text for line in aligned] == copied
    assert [line.start for line in aligned] == [10.0, 12.0, 14.0]
    assert warnings == []


def test_confidence_scores_duration_and_synced_bonus() -> None:
    score = confidence_for_candidate("Song", "Artist", "Album", 180, "Song", "Artist", "Album", 181, True)

    assert score >= 90
