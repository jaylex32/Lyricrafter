from pathlib import Path
from io import BytesIO

from PIL import Image

from app.metadata.cover import normalize_cover_image
from app.metadata.service import TrackMetadata, has_track_metadata, metadata_from_source_info, query_from_filename
from app.metadata.tags import can_write_metadata


def test_query_from_filename_uses_artist_title_shape() -> None:
    assert query_from_filename(Path("Artist - Song Title [abc123].m4a")) == (
        'artist:"Artist" AND recording:"Song Title"'
    )


def test_metadata_extension_support() -> None:
    assert can_write_metadata(Path("song.mp3"))
    assert can_write_metadata(Path("song.flac"))
    assert can_write_metadata(Path("song.m4a"))
    assert not can_write_metadata(Path("song.wav"))


def test_metadata_dataclass_defaults() -> None:
    metadata = TrackMetadata(title="Song")

    assert metadata.title == "Song"
    assert metadata.cover_data is None


def test_source_info_metadata_uses_track_fields_only() -> None:
    metadata = metadata_from_source_info(
        {
            "title": "Video Title",
            "track": "Track Name",
            "artist": "Artist Name",
            "album": "Album Name",
            "uploader": "Channel Name",
            "release_date": "20260426",
        }
    )

    assert metadata.title == "Track Name"
    assert metadata.artist == "Artist Name"
    assert metadata.album == "Album Name"
    assert metadata.date == "2026-04-26"


def test_source_info_does_not_treat_uploader_as_artist() -> None:
    metadata = metadata_from_source_info({"title": "Video Title", "uploader": "Channel Name", "upload_date": "20260426"})

    assert metadata.title == "Video Title"
    assert metadata.artist == ""
    assert metadata.date == ""
    assert not has_track_metadata({"title": "Video Title", "uploader": "Channel Name"})
    assert has_track_metadata({"track": "Song", "artist": "Artist"})


def test_cover_normalization_converts_webp_to_jpeg() -> None:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="WEBP")

    data, mime = normalize_cover_image(buffer.getvalue(), "image/webp")

    assert data is not None
    assert mime == "image/jpeg"
    assert data.startswith(b"\xff\xd8")
