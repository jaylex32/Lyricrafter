from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import traceback
import urllib.request

from app.core.config import default_model_dir
from app.core.database import AppDatabase
from app.core.media_tools import bundled_ffmpeg_exe
from app.core.resources import app_icon_path
from app.models.catalog import ModelCatalog, ModelManager


REQUIRED_MODULES = (
    "PySide6",
    "av",
    "ctranslate2",
    "demucs",
    "demucs.separate",
    "faster_whisper",
    "huggingface_hub",
    "imageio_ffmpeg",
    "mutagen",
    "PIL",
    "sentencepiece",
    "syncedlyrics",
    "torch",
    "transformers",
    "yt_dlp",
)


def run_package_smoke_test(report_path: Path | None = None) -> int:
    checks: dict[str, object] = {}
    errors: list[str] = []

    def check(name: str, operation) -> None:
        try:
            checks[name] = operation()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            checks[name] = {"error": str(exc), "traceback": traceback.format_exc()}

    for module_name in REQUIRED_MODULES:
        check(f"import:{module_name}", lambda name=module_name: importlib.import_module(name).__name__)

    check("app_icon", lambda: _existing_path(app_icon_path()))
    check("ffmpeg", lambda: _existing_path(bundled_ffmpeg_exe()))
    check("model_catalog", lambda: len(ModelCatalog().list_models("whisper")))
    check("model_recommendations", _check_model_recommendations)
    check("translation_runtime", _check_translation_runtime)
    check("writable_model_storage", _check_default_model_storage)
    check("model_lifecycle", _check_model_lifecycle)
    check("database", _check_database)
    if os.environ.get("LYRICRAFTER_SMOKE_NETWORK") == "1":
        check("model_download_endpoints", _check_model_download_endpoints)
    if os.environ.get("LYRICRAFTER_SMOKE_MODEL_DOWNLOAD") == "1":
        check("model_download_delete", _check_real_model_download_delete)

    payload = {
        "ok": not errors,
        "frozen": bool(getattr(__import__("sys"), "frozen", False)),
        "checks": checks,
        "errors": errors,
    }
    output = report_path or _report_path_from_environment()
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if not errors else 1


def _existing_path(path: Path | None) -> str:
    if path is None or not path.exists():
        raise RuntimeError("Required packaged resource was not found.")
    return str(path)


def _check_default_model_storage() -> str:
    folder = default_model_dir()
    folder.mkdir(parents=True, exist_ok=True)
    sentinel = folder / ".lyricrafter-package-smoke"
    sentinel.write_text("ok", encoding="utf-8")
    sentinel.unlink()
    return str(folder)


def _check_model_lifecycle() -> bool:
    with tempfile.TemporaryDirectory(prefix="lyricrafter-model-smoke-") as temp:
        manager = ModelManager(Path(temp))
        install = manager.installation_path("tiny", "faster-whisper")
        snapshot = install / "snapshots" / "smoke"
        snapshot.mkdir(parents=True)
        (snapshot / "model.bin").write_bytes(b"smoke")
        if not manager.is_installed("tiny", "faster-whisper"):
            raise RuntimeError("Created model was not detected.")
        if not manager.delete_model("tiny", "faster-whisper") or install.exists():
            raise RuntimeError("Created model was not deleted.")
    return True


def _check_model_recommendations() -> dict[str, str]:
    from app.core.jobs import ProcessingOptions

    recommendations = {
        model.id: model.recommended_for
        for model in ModelCatalog().list_models("whisper")
        if model.recommended
    }
    expected = {
        "small": "Small systems",
        "medium": "Medium systems",
        "large-v2": "Large / Default",
    }
    if recommendations != expected:
        raise RuntimeError(f"Unexpected model recommendations: {recommendations}")
    if ProcessingOptions().model_id != "large-v2":
        raise RuntimeError("large-v2 is not the default transcription model.")
    return recommendations


def _check_translation_runtime() -> str:
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from transformers.models.m2m_100 import modeling_m2m_100
    from transformers.models.nllb import tokenization_nllb

    if AutoModelForSeq2SeqLM is None or AutoTokenizer is None:
        raise RuntimeError("Transformers auto classes were not loaded.")
    return f"{modeling_m2m_100.__name__};{tokenization_nllb.__name__}"


def _check_database() -> bool:
    with tempfile.TemporaryDirectory(prefix="lyricrafter-db-smoke-") as temp:
        database = AppDatabase(Path(temp) / "smoke.sqlite3")
        database.set_setting("package_smoke", "ok")
        if database.get_setting("package_smoke") != "ok":
            raise RuntimeError("SQLite setting round trip failed.")
    return True


def _check_model_download_endpoints() -> dict[str, object]:
    from huggingface_hub import HfApi

    whisper_repo = ModelManager.REPO_ALIASES["tiny"]
    info = HfApi().model_info(whisper_repo)
    cpp_url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny-q5_1.bin"
    request = urllib.request.Request(cpp_url, method="HEAD", headers={"User-Agent": "Lyricrafter"})
    with urllib.request.urlopen(request, timeout=30) as response:
        cpp_status = response.status
    if cpp_status >= 400:
        raise RuntimeError(f"whisper.cpp endpoint returned HTTP {cpp_status}")
    return {"faster_whisper": info.id, "whisper_cpp_http": cpp_status}


def _check_real_model_download_delete() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="lyricrafter-model-download-") as temp:
        manager = ModelManager(Path(temp))
        downloaded = manager.download_faster_whisper("tiny")
        installed = manager.installed_faster_whisper_path("tiny")
        if installed is None or not (installed / "model.bin").is_file():
            raise RuntimeError("The downloaded tiny model was not resolved for transcription.")
        size = (installed / "model.bin").stat().st_size
        audio_path = Path(temp) / "silence.wav"
        _write_silent_wave(audio_path)
        from app.core.jobs import ProcessingOptions
        from app.transcription.faster_whisper_backend import FasterWhisperTranscriber

        result = FasterWhisperTranscriber(model_manager=manager).transcribe(
            audio_path,
            ProcessingOptions(
                model_id="tiny",
                device="cpu",
                compute_type="int8",
                language="en",
            ),
        )
        if not manager.delete_model("tiny", "faster-whisper"):
            raise RuntimeError("The downloaded tiny model could not be deleted.")
        if manager.is_installed("tiny", "faster-whisper"):
            raise RuntimeError("The tiny model remained installed after deletion.")
        return {
            "downloaded": str(downloaded),
            "model_bytes": size,
            "decoded_seconds": result.duration,
            "segments": len(result.segments),
            "deleted": True,
        }


def _write_silent_wave(path: Path, seconds: int = 1) -> None:
    import wave

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 16_000 * seconds)


def _report_path_from_environment() -> Path | None:
    value = os.environ.get("LYRICRAFTER_SMOKE_REPORT", "").strip()
    return Path(value) if value else None
