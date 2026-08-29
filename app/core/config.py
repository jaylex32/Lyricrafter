from __future__ import annotations

from pathlib import Path

try:
    from platformdirs import user_cache_dir, user_config_dir, user_data_dir, user_downloads_dir
except ImportError:
    user_cache_dir = user_config_dir = user_data_dir = user_downloads_dir = None

APP_NAME = "Lyricrafter"
SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_NAME)) if user_data_dir else _fallback_app_dir("data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_NAME)) if user_config_dir else _fallback_app_dir("config")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = Path(user_cache_dir(APP_NAME, APP_NAME)) if user_cache_dir else _fallback_app_dir("cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_model_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    path = data_dir() / "runtimes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stems_cache_dir() -> Path:
    path = cache_dir() / "stems"
    path.mkdir(parents=True, exist_ok=True)
    return path


def youtube_download_dir() -> Path:
    path = default_online_download_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_online_download_dir() -> Path:
    if user_downloads_dir:
        base = Path(user_downloads_dir())
    else:
        downloads = Path.home() / "Downloads"
        base = downloads if downloads.exists() else Path.home()
    return base / APP_NAME


def _fallback_app_dir(kind: str) -> Path:
    base = Path.home() / "AppData" / "Local" if (Path.home() / "AppData").exists() else Path.home()
    return base / APP_NAME / kind
