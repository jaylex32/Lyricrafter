from app.core.youtube import (
    DEFAULT_FILENAME_TEMPLATE,
    looks_like_video_url,
    normalize_audio_format,
    parse_video_urls,
    yt_dlp_filename_template,
)


def test_looks_like_video_url_accepts_supported_sites() -> None:
    assert looks_like_video_url("https://www.youtube.com/watch?v=abc")
    assert looks_like_video_url("https://youtu.be/abc")
    assert looks_like_video_url("https://soundcloud.com/artist/song")


def test_looks_like_video_url_rejects_plain_paths() -> None:
    assert not looks_like_video_url(r"C:\Music\song.flac")
    assert not looks_like_video_url("not a url")


def test_parse_video_urls_accepts_multiple_urls_and_deduplicates() -> None:
    urls = parse_video_urls(
        "https://youtu.be/abc https://www.youtube.com/watch?v=def\n"
        "https://youtu.be/abc https://example.com/nope"
    )

    assert urls == ["https://youtu.be/abc", "https://www.youtube.com/watch?v=def"]


def test_filename_template_converts_user_tokens_for_yt_dlp() -> None:
    assert yt_dlp_filename_template("{uploader} - {title} [{id}]") == (
        "%(uploader).80s - %(title).180s [%(id)s].%(ext)s"
    )


def test_filename_template_falls_back_for_plain_text() -> None:
    assert yt_dlp_filename_template("song") == yt_dlp_filename_template(DEFAULT_FILENAME_TEMPLATE)


def test_normalize_audio_format_falls_back_to_m4a() -> None:
    assert normalize_audio_format("MP3") == "mp3"
    assert normalize_audio_format("bad") == "m4a"
