from pathlib import Path

from app.core.media_tools import ffmpeg_location


def test_ffmpeg_location_uses_available_binary() -> None:
    location = ffmpeg_location()

    assert location
    assert Path(location).exists()


def test_yt_dlp_can_see_bundled_ffmpeg() -> None:
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

    with YoutubeDL({"ffmpeg_location": ffmpeg_location(), "quiet": True}) as downloader:
        postprocessor = FFmpegPostProcessor(downloader)

    assert postprocessor.available
