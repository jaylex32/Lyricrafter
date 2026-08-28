from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Any
import urllib.request

from app.core.config import youtube_download_dir
from app.core.media_tools import ffmpeg_location
from app.metadata.service import USER_AGENT, has_track_metadata, metadata_from_source_info
from app.metadata.tags import can_write_metadata, write_metadata

ProgressCallback = Callable[[int, str], None]
SUPPORTED_ONLINE_AUDIO_FORMATS = ("m4a", "mp3", "flac", "wav", "opus")
DEFAULT_ONLINE_AUDIO_FORMAT = "m4a"
DEFAULT_FILENAME_TEMPLATE = "{title} [{id}]"
FILENAME_PRESETS = {
    "Title + ID": DEFAULT_FILENAME_TEMPLATE,
    "Title Only": "{title}",
    "Artist - Title": "{uploader} - {title}",
    "Date - Title": "{upload_date} - {title}",
}

VIDEO_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:youtube\.com|youtu\.be|music\.youtube\.com|vimeo\.com|soundcloud\.com)/",
    re.IGNORECASE,
)
URL_TOKEN_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)


def looks_like_video_url(value: str) -> bool:
    return bool(VIDEO_URL_RE.match(value.strip()))


def parse_video_urls(value: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_TOKEN_RE.findall(value):
        url = match.rstrip(").,;")
        if looks_like_video_url(url) and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def download_url_audio(
    url: str,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    audio_format: str = DEFAULT_ONLINE_AUDIO_FORMAT,
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
) -> Path:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run setup again or install the yt-dlp package.") from exc

    target_dir = output_dir or youtube_download_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    audio_format = normalize_audio_format(audio_format)
    progress = progress or (lambda _percent, _message: None)
    downloaded_paths: list[Path] = []

    def hook(status: dict[str, Any]) -> None:
        state = status.get("status")
        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            downloaded = status.get("downloaded_bytes") or 0
            percent = int((downloaded / total) * 100) if total else 0
            speed = status.get("_speed_str", "").strip()
            eta = status.get("_eta_str", "").strip()
            detail = f"Downloading video audio ({percent}%)"
            if speed or eta:
                detail = f"{detail} {speed} ETA {eta}".strip()
            progress(max(0, min(99, percent)), detail)
        elif state == "finished":
            filename = status.get("filename")
            if filename:
                downloaded_paths.append(Path(filename))
            progress(99, "Preparing downloaded audio")

    options = {
        "format": _download_format_selector(audio_format),
        "outtmpl": str(target_dir / yt_dlp_filename_template(filename_template)),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "0",
            }
        ],
    }
    ffmpeg = ffmpeg_location()
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg

    progress(0, "Reading video metadata")
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)

    audio_path = _resolve_downloaded_audio_path(info, downloaded_paths, target_dir)
    _embed_source_metadata(audio_path, info, progress)
    progress(100, f"Downloaded {audio_path.name}")
    return audio_path


def normalize_audio_format(audio_format: str) -> str:
    normalized = audio_format.strip().lower()
    return normalized if normalized in SUPPORTED_ONLINE_AUDIO_FORMATS else DEFAULT_ONLINE_AUDIO_FORMAT


def yt_dlp_filename_template(template: str) -> str:
    cleaned = (template or DEFAULT_FILENAME_TEMPLATE).strip()
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", cleaned)
    replacements = {
        "{title}": "%(title).180s",
        "{id}": "%(id)s",
        "{uploader}": "%(uploader).80s",
        "{channel}": "%(channel).80s",
        "{upload_date}": "%(upload_date)s",
        "{playlist_index}": "%(playlist_index)s",
    }
    for token, value in replacements.items():
        cleaned = cleaned.replace(token, value)
    if "%(" not in cleaned:
        cleaned = DEFAULT_FILENAME_TEMPLATE
        for token, value in replacements.items():
            cleaned = cleaned.replace(token, value)
    if not cleaned.endswith(".%(ext)s"):
        cleaned = f"{cleaned}.%(ext)s"
    return cleaned


def _download_format_selector(audio_format: str) -> str:
    if audio_format == "m4a":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if audio_format == "opus":
        return "bestaudio[ext=webm]/bestaudio/best"
    return "bestaudio/best"


def _resolve_downloaded_audio_path(info: dict[str, Any], downloaded_paths: list[Path], target_dir: Path) -> Path:
    candidates: list[Path] = []
    for requested in info.get("requested_downloads") or []:
        for key in ("filepath", "filename"):
            value = requested.get(key)
            if value:
                candidates.append(Path(value))
    candidates.extend(downloaded_paths)
    if info.get("filepath"):
        candidates.append(Path(str(info["filepath"])))
    if info.get("_filename"):
        candidates.append(Path(str(info["_filename"])))

    expanded: list[Path] = []
    for candidate in candidates:
        expanded.append(candidate)
        for suffix in SUPPORTED_ONLINE_AUDIO_FORMATS:
            expanded.append(candidate.with_suffix(f".{suffix}"))
    for candidate in expanded:
        if candidate.exists():
            return candidate

    video_id = str(info.get("id") or "")
    if video_id:
        matches = sorted(
            (path for path in target_dir.glob("*") if f"[{video_id}]" in path.stem),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]

    audio_files = sorted(target_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in audio_files:
        if path.suffix.lower() in {".m4a", ".mp3", ".wav", ".opus", ".ogg", ".flac"}:
            return path
    raise RuntimeError("The video downloaded, but Lyricrafter could not locate the extracted audio file.")


def _embed_source_metadata(audio_path: Path, info: dict[str, Any], progress: ProgressCallback) -> None:
    if not can_write_metadata(audio_path):
        return
    if not has_track_metadata(info):
        return
    try:
        cover_data, cover_mime = _download_best_thumbnail(info)
        metadata = metadata_from_source_info(info, cover_data=cover_data, cover_mime=cover_mime)
        if not metadata.title and not metadata.artist and not metadata.album and not metadata.cover_data:
            return
        progress(99, "Embedding track metadata and cover")
        write_metadata(audio_path, metadata)
    except Exception as exc:
        progress(99, f"Downloaded audio; metadata embed skipped ({exc})")


def _download_best_thumbnail(info: dict[str, Any]) -> tuple[bytes | None, str]:
    candidates = []
    for thumbnail in info.get("thumbnails") or []:
        url = thumbnail.get("url")
        if url:
            candidates.append((int(thumbnail.get("preference") or 0), int(thumbnail.get("width") or 0), url))
    if info.get("thumbnail"):
        candidates.append((999, 0, str(info["thumbnail"])))
    for _preference, _width, url in sorted(candidates, reverse=True):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                mime = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
                return response.read(), mime
        except Exception:
            continue
    return None, "image/jpeg"
