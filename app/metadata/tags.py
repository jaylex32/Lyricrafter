from __future__ import annotations

import base64
from pathlib import Path

from app.metadata.service import TrackMetadata

SUPPORTED_METADATA_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"}


def can_write_metadata(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_METADATA_EXTENSIONS


def write_metadata(path: Path, metadata: TrackMetadata) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return _write_mp3(path, metadata)
    if suffix == ".flac":
        return _write_flac(path, metadata)
    if suffix in {".ogg", ".opus"}:
        return _write_vorbis(path, metadata)
    if suffix in {".m4a", ".mp4"}:
        return _write_mp4(path, metadata)
    return False


def _write_mp3(path: Path, metadata: TrackMetadata) -> bool:
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TRCK, TXXX

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    _id3_text(tags, TIT2, metadata.title)
    _id3_text(tags, TPE1, metadata.artist)
    _id3_text(tags, TALB, metadata.album)
    _id3_text(tags, TDRC, metadata.date)
    _id3_text(tags, TRCK, metadata.track_number)
    if metadata.musicbrainz_recording_id:
        tags.delall("TXXX:MusicBrainz Recording Id")
        tags.add(TXXX(encoding=3, desc="MusicBrainz Recording Id", text=[metadata.musicbrainz_recording_id]))
    if metadata.cover_data:
        tags.add(APIC(encoding=3, mime=metadata.cover_mime, type=3, desc="Cover", data=metadata.cover_data))
    tags.save(path)
    return True


def _id3_text(tags, frame_cls, value: str) -> None:
    if value:
        tags.delall(frame_cls.__name__)
        tags.add(frame_cls(encoding=3, text=[value]))


def _write_flac(path: Path, metadata: TrackMetadata) -> bool:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(path)
    _vorbis_values(audio, metadata)
    if metadata.cover_data:
        audio.clear_pictures()
        picture = Picture()
        picture.type = 3
        picture.mime = metadata.cover_mime
        picture.desc = "Cover"
        picture.data = metadata.cover_data
        audio.add_picture(picture)
    audio.save()
    return True


def _write_vorbis(path: Path, metadata: TrackMetadata) -> bool:
    from mutagen import File
    from mutagen.flac import Picture

    audio = File(path)
    if audio is None:
        return False
    _vorbis_values(audio, metadata)
    if metadata.cover_data:
        picture = Picture()
        picture.type = 3
        picture.mime = metadata.cover_mime
        picture.desc = "Cover"
        picture.data = metadata.cover_data
        audio["METADATA_BLOCK_PICTURE"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save()
    return True


def _vorbis_values(audio, metadata: TrackMetadata) -> None:
    values = {
        "TITLE": metadata.title,
        "ARTIST": metadata.artist,
        "ALBUM": metadata.album,
        "DATE": metadata.date,
        "TRACKNUMBER": metadata.track_number,
        "MUSICBRAINZ_TRACKID": metadata.musicbrainz_recording_id,
        "MUSICBRAINZ_ALBUMID": metadata.musicbrainz_release_id,
        "MUSICBRAINZ_RELEASEGROUPID": metadata.musicbrainz_release_group_id,
    }
    for key, value in values.items():
        if value:
            audio[key] = value


def _write_mp4(path: Path, metadata: TrackMetadata) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    _mp4_value(audio, "\xa9nam", metadata.title)
    _mp4_value(audio, "\xa9ART", metadata.artist)
    _mp4_value(audio, "\xa9alb", metadata.album)
    _mp4_value(audio, "\xa9day", metadata.date)
    if metadata.track_number.isdigit():
        audio["trkn"] = [(int(metadata.track_number), 0)]
    if metadata.musicbrainz_recording_id:
        audio["----:com.apple.iTunes:MusicBrainz Recording Id"] = [metadata.musicbrainz_recording_id.encode("utf-8")]
    if metadata.cover_data:
        image_format = MP4Cover.FORMAT_PNG if metadata.cover_mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(metadata.cover_data, imageformat=image_format)]
    audio.save()
    return True


def _mp4_value(audio, key: str, value: str) -> None:
    if value:
        audio[key] = [value]
