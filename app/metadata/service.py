from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.metadata.cover import normalize_cover_image

USER_AGENT = "Lyricrafter/0.1 (local desktop app; https://github.com/local/lyricrafter)"
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
COVER_ART_BASE = "https://coverartarchive.org"


@dataclass(frozen=True)
class TrackMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    date: str = ""
    track_number: str = ""
    musicbrainz_recording_id: str = ""
    musicbrainz_release_id: str = ""
    musicbrainz_release_group_id: str = ""
    cover_data: bytes | None = None
    cover_mime: str = "image/jpeg"


def lookup_metadata_for_file(path: Path) -> TrackMetadata | None:
    query = query_from_filename(path)
    if not query:
        return None
    recording = _search_recording(query)
    if not recording:
        return None
    metadata = _metadata_from_recording(recording)
    cover_data, cover_mime = _download_cover(metadata.musicbrainz_release_id, metadata.musicbrainz_release_group_id)
    return TrackMetadata(
        title=metadata.title,
        artist=metadata.artist,
        album=metadata.album,
        date=metadata.date,
        track_number=metadata.track_number,
        musicbrainz_recording_id=metadata.musicbrainz_recording_id,
        musicbrainz_release_id=metadata.musicbrainz_release_id,
        musicbrainz_release_group_id=metadata.musicbrainz_release_group_id,
        cover_data=cover_data,
        cover_mime=cover_mime,
    )


def metadata_from_source_info(info: dict, cover_data: bytes | None = None, cover_mime: str = "image/jpeg") -> TrackMetadata:
    date = _release_date_from_info(info)
    artist = str(info.get("artist") or "")
    album = str(info.get("album") or "")
    title = str(info.get("track") or info.get("title") or "")
    normalized_cover, normalized_mime = normalize_cover_image(cover_data, cover_mime)
    return TrackMetadata(
        title=title,
        artist=artist,
        album=album,
        date=date,
        track_number=str(info.get("track_number") or ""),
        cover_data=normalized_cover,
        cover_mime=normalized_mime,
    )


def has_track_metadata(info: dict) -> bool:
    return any(str(info.get(key) or "").strip() for key in ("track", "artist", "album", "release_date", "release_year", "year"))


def _release_date_from_info(info: dict) -> str:
    for key in ("release_date", "release_year", "year"):
        value = str(info.get(key) or "").strip()
        if not value:
            continue
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        return value
    return ""


def query_from_filename(path: Path) -> str:
    stem = re.sub(r"\s+", " ", path.stem).strip()
    stem = re.sub(r"\[[^\]]+\]|\([^)]+\)", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    if not stem:
        return ""
    parts = [part.strip() for part in re.split(r"\s+-\s+", stem, maxsplit=1)]
    if len(parts) == 2 and all(parts):
        artist, title = parts
        return f'artist:"{artist}" AND recording:"{title}"'
    return stem


def _search_recording(query: str) -> dict | None:
    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": "1"})
    data = _get_json(f"{MUSICBRAINZ_BASE}/recording/?{params}")
    recordings = data.get("recordings") or []
    return recordings[0] if recordings else None


def _metadata_from_recording(recording: dict) -> TrackMetadata:
    releases = recording.get("releases") or []
    release = releases[0] if releases else {}
    artist_credit = recording.get("artist-credit") or []
    artist = "".join(str(part.get("name", "")) + str(part.get("joinphrase", "")) for part in artist_credit).strip()
    track_number = ""
    media = release.get("media") or []
    if media and media[0].get("track-offset") is not None:
        track_number = str(int(media[0]["track-offset"]) + 1)
    return TrackMetadata(
        title=str(recording.get("title") or ""),
        artist=artist,
        album=str(release.get("title") or ""),
        date=str(release.get("date") or ""),
        track_number=track_number,
        musicbrainz_recording_id=str(recording.get("id") or ""),
        musicbrainz_release_id=str(release.get("id") or ""),
        musicbrainz_release_group_id=str((release.get("release-group") or {}).get("id") or ""),
    )


def _download_cover(release_id: str, release_group_id: str = "") -> tuple[bytes | None, str]:
    targets = []
    if release_id:
        targets.extend([f"{COVER_ART_BASE}/release/{release_id}/front-500", f"{COVER_ART_BASE}/release/{release_id}/front"])
    if release_group_id:
        targets.extend(
            [
                f"{COVER_ART_BASE}/release-group/{release_group_id}/front-500",
                f"{COVER_ART_BASE}/release-group/{release_group_id}/front",
            ]
        )
    for url in targets:
        try:
            response = _open_url(url, accept="image/*")
            content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
            return normalize_cover_image(response.read(), content_type)
        except Exception:
            continue
    return None, "image/jpeg"


def _get_json(url: str) -> dict:
    response = _open_url(url)
    return json.loads(response.read().decode("utf-8"))


def _open_url(url: str, accept: str = "application/json"):
    time.sleep(1.0)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=20)
