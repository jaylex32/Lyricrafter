from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Callable

from app.core.config import default_model_dir

DownloadProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    family: str
    backend: str
    size: str = ""
    recommended: bool = False
    recommended_for: str = ""


class ModelCatalog:
    def __init__(self, manifest_path: Path | None = None) -> None:
        self.manifest_path = manifest_path
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        if self.manifest_path:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest = files("app.models").joinpath("manifest.json")
        return json.loads(manifest.read_text(encoding="utf-8"))

    def list_models(self, section: str = "whisper") -> list[ModelInfo]:
        return [
            ModelInfo(
                id=item["id"],
                name=item["name"],
                family=item.get("family", ""),
                backend=item.get("backend", ""),
                size=item.get("size", ""),
                recommended=bool(item.get("recommended", False)),
                recommended_for=item.get("recommended_for", ""),
            )
            for item in self._manifest.get(section, [])
        ]

    def ids(self, section: str = "whisper") -> list[str]:
        return [item.id for item in self.list_models(section)]

    def refresh_from_url(self, url: str) -> None:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = response.read().decode("utf-8")
        self._manifest = json.loads(payload)


class ModelManager:
    REPO_ALIASES = {
        "tiny.en": "Systran/faster-whisper-tiny.en",
        "tiny": "Systran/faster-whisper-tiny",
        "base.en": "Systran/faster-whisper-base.en",
        "base": "Systran/faster-whisper-base",
        "small.en": "Systran/faster-whisper-small.en",
        "small": "Systran/faster-whisper-small",
        "medium.en": "Systran/faster-whisper-medium.en",
        "medium": "Systran/faster-whisper-medium",
        "large-v1": "Systran/faster-whisper-large-v1",
        "large-v2": "Systran/faster-whisper-large-v2",
        "large-v3": "Systran/faster-whisper-large-v3",
        "large": "Systran/faster-whisper-large-v3",
        "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
        "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    }

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir or default_model_dir()
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def faster_whisper_cache_dir(self) -> Path:
        path = self.model_dir / "faster-whisper"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def installation_path(self, model_id: str, backend: str) -> Path:
        if backend == "whisper.cpp":
            return self.whisper_cpp_model_path(model_id)
        repo_id = self.REPO_ALIASES.get(
            model_id,
            model_id if "/" in model_id else f"Systran/faster-whisper-{model_id}",
        )
        repo_folder = "models--" + repo_id.replace("/", "--")
        return self.faster_whisper_cache_dir() / repo_folder

    def is_installed(self, model_id: str, backend: str) -> bool:
        path = self.installation_path(model_id, backend)
        if backend == "whisper.cpp":
            return path.is_file() and path.stat().st_size > 0
        snapshots = path / "snapshots"
        if not snapshots.is_dir():
            return False
        return any(candidate.is_file() for candidate in snapshots.rglob("*"))

    def installed_faster_whisper_path(self, model_id: str) -> Path | None:
        return _latest_model_snapshot(self.installation_path(model_id, "faster-whisper"))

    def resolved_faster_whisper_path(self, model_id: str) -> Path | None:
        installed = self.installed_faster_whisper_path(model_id)
        if installed is not None:
            return installed
        repo_id = self.REPO_ALIASES.get(
            model_id,
            model_id if "/" in model_id else f"Systran/faster-whisper-{model_id}",
        )
        repo_folder = "models--" + repo_id.replace("/", "--")
        return _latest_model_snapshot(_legacy_hugging_face_hub() / repo_folder)

    def delete_model(self, model_id: str, backend: str) -> bool:
        target = self.installation_path(model_id, backend)
        model_root = self.model_dir.resolve()
        resolved = target.resolve(strict=False)
        if resolved == model_root or not resolved.is_relative_to(model_root):
            raise ValueError("Refusing to delete a model path outside Lyricrafter model storage.")
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return True

    def download_faster_whisper(
        self,
        model_id: str,
        progress: DownloadProgressCallback | None = None,
    ) -> Path:
        repo_id = self.REPO_ALIASES.get(
            model_id,
            model_id if "/" in model_id else f"Systran/faster-whisper-{model_id}",
        )
        if progress:
            return self._snapshot_download_with_progress(repo_id, model_id, progress)

        try:
            from faster_whisper.utils import download_model

            return Path(download_model(model_id, cache_dir=str(self.faster_whisper_cache_dir())))
        except ImportError:
            pass

        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError("faster-whisper or huggingface-hub is required for model downloads.") from exc

        return Path(
            snapshot_download(
                repo_id=repo_id,
                cache_dir=str(self.faster_whisper_cache_dir()),
                local_files_only=False,
            )
        )

    def _snapshot_download_with_progress(
        self,
        repo_id: str,
        model_id: str,
        progress: DownloadProgressCallback,
    ) -> Path:
        try:
            from huggingface_hub import snapshot_download
            from tqdm.auto import tqdm
        except ImportError as exc:
            raise RuntimeError("huggingface-hub and tqdm are required for model downloads.") from exc

        progress(0, f"{model_id}: preparing download")
        cache_dir = self.faster_whisper_cache_dir()
        expected_bytes = _expected_snapshot_bytes(repo_id, cache_dir, [
            "config.json",
            "preprocessor_config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
        ])
        stop_monitor = threading.Event()
        monitor = _start_size_monitor(
            cache_dir,
            expected_bytes,
            stop_monitor,
            lambda percent: progress(percent, f"{model_id}: downloading ({percent}%)"),
        )

        class ProgressTqdm(tqdm):
            def __init__(self, *args, **kwargs):
                self._last_percent = -1
                if kwargs.get("file") is None:
                    kwargs["file"] = _ProgressOutputSink()
                super().__init__(*args, **kwargs)

            def update(self, n=1):
                super().update(n)
                if not self.total:
                    return
                percent = max(0, min(100, int((self.n / self.total) * 100)))
                if percent == self._last_percent:
                    return
                self._last_percent = percent
                description = self.desc or "downloading"
                progress(percent, f"{model_id}: {description} ({percent}%)")

        try:
            path = Path(
                snapshot_download(
                    repo_id=repo_id,
                    cache_dir=str(cache_dir),
                    local_files_only=False,
                    allow_patterns=[
                        "config.json",
                        "preprocessor_config.json",
                        "model.bin",
                        "tokenizer.json",
                        "vocabulary.*",
                    ],
                    tqdm_class=ProgressTqdm,
                )
            )
        finally:
            stop_monitor.set()
            monitor.join(timeout=1)
        progress(100, f"{model_id}: download complete")
        return path

    def whisper_cpp_model_path(self, model_id: str) -> Path:
        return self.model_dir / "whisper.cpp" / f"ggml-{model_id}.bin"

    def download_whisper_cpp(
        self,
        model_id: str,
        progress: DownloadProgressCallback | None = None,
    ) -> Path:
        target = self.whisper_cpp_model_path(model_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model_id}.bin"
        if progress:
            progress(0, f"{model_id}: preparing download")

            def reporthook(block_count: int, block_size: int, total_size: int) -> None:
                if total_size <= 0:
                    return
                downloaded = min(block_count * block_size, total_size)
                percent = max(0, min(100, int((downloaded / total_size) * 100)))
                progress(percent, f"{model_id}: downloading ({percent}%)")

            urllib.request.urlretrieve(url, target, reporthook=reporthook)
            progress(100, f"{model_id}: download complete")
        else:
            urllib.request.urlretrieve(url, target)
        return target


def _expected_snapshot_bytes(repo_id: str, cache_dir: Path, allow_patterns: list[str]) -> int:
    try:
        from huggingface_hub import snapshot_download

        files = snapshot_download(
            repo_id=repo_id,
            cache_dir=str(cache_dir),
            local_files_only=False,
            allow_patterns=allow_patterns,
            dry_run=True,
        )
    except Exception:
        return 0
    total = 0
    for file_info in files if isinstance(files, list) else []:
        total += int(getattr(file_info, "size", None) or getattr(file_info, "file_size", 0) or 0)
    return total


def _start_size_monitor(
    folder: Path,
    expected_bytes: int,
    stop_event: threading.Event,
    progress: Callable[[int], None],
) -> threading.Thread:
    start_bytes = _directory_size(folder)

    def monitor() -> None:
        last_percent = -1
        while not stop_event.wait(0.35):
            if expected_bytes <= 0:
                continue
            current = max(0, _directory_size(folder) - start_bytes)
            percent = max(1, min(99, int((current / expected_bytes) * 100)))
            if percent != last_percent:
                last_percent = percent
                progress(percent)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    return thread


def _directory_size(folder: Path) -> int:
    if not folder.exists():
        return 0
    total = 0
    for path in folder.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _latest_model_snapshot(repo_folder: Path) -> Path | None:
    snapshots = repo_folder / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = [
        path
        for path in snapshots.iterdir()
        if path.is_dir() and (path / "model.bin").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _legacy_hugging_face_hub() -> Path:
    explicit_cache = os.environ.get("HF_HUB_CACHE", "").strip()
    if explicit_cache:
        return Path(explicit_cache).expanduser()
    hf_home = os.environ.get("HF_HOME", "").strip()
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


class _ProgressOutputSink:
    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False
