from pathlib import Path

from app.export.embed import can_embed_lyrics


def test_can_embed_known_audio_formats() -> None:
    assert can_embed_lyrics(Path("song.mp3"))
    assert can_embed_lyrics(Path("song.flac"))
    assert can_embed_lyrics(Path("song.ogg"))
    assert can_embed_lyrics(Path("song.opus"))
    assert can_embed_lyrics(Path("song.m4a"))
    assert not can_embed_lyrics(Path("song.wav"))
