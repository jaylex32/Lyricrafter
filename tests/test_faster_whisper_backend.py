from pathlib import Path
import sys
import types

from app.core.jobs import ProcessingOptions
from app.models.catalog import ModelManager
from app.transcription import faster_whisper_backend
from app.transcription.faster_whisper_backend import FasterWhisperTranscriber


class FakeWord:
    start = 0.0
    end = 0.5
    word = "Hello"


class FakeSegment:
    start = 0.0
    end = 0.5
    text = "Hello"
    words = [FakeWord()]


class FakeInfo:
    language = "en"
    duration = 0.5


class FakeWhisperModel:
    last_kwargs = {}
    load_attempts = []

    def __init__(self, model_id: str, device: str, compute_type: str, cpu_threads: int) -> None:
        self.device = device
        self.cpu_threads = cpu_threads
        FakeWhisperModel.load_attempts.append((device, compute_type, cpu_threads))
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    def transcribe(self, *args, **kwargs):
        FakeWhisperModel.last_kwargs = kwargs
        return iter([FakeSegment()]), FakeInfo()


def test_cuda_cublas_failure_falls_back_to_cpu(tmp_path: Path) -> None:
    FakeWhisperModel.load_attempts = []
    transcriber = FasterWhisperTranscriber(model_factory=FakeWhisperModel)
    messages: list[str] = []
    percents: list[int] = []

    result = transcriber.transcribe(
        tmp_path / "song.wav",
        ProcessingOptions(device="cuda", compute_type="float16", cpu_threads=12),
        lambda percent, message: (percents.append(percent), messages.append(message)),
    )

    assert result.segments[0].text == "Hello"
    assert any("retrying Whisper on CPU" in message for message in messages)
    assert 85 in percents
    assert "initial_prompt" not in FakeWhisperModel.last_kwargs
    assert "condition_on_previous_text" not in FakeWhisperModel.last_kwargs
    assert FakeWhisperModel.load_attempts == [
        ("cuda", "float16", 0),
        ("cpu", "float32", 12),
    ]


def test_default_factory_uses_downloaded_model_storage(tmp_path: Path, monkeypatch) -> None:
    manager = ModelManager(tmp_path)
    snapshot = manager.installation_path("tiny", "faster-whisper") / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"model")
    captured = {}

    class RecordingModel:
        def __init__(self, model_source, **kwargs):
            captured["model_source"] = model_source
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=RecordingModel))
    transcriber = FasterWhisperTranscriber(model_manager=manager)

    transcriber._get_model_factory()("tiny", device="cpu", compute_type="int8", cpu_threads=12)

    assert captured["model_source"] == str(snapshot)
    assert captured["download_root"] == str(manager.faster_whisper_cache_dir())
    assert captured["cpu_threads"] == 12


def test_auto_device_uses_ctranslate2_cuda_detection(monkeypatch) -> None:
    monkeypatch.setattr(faster_whisper_backend, "ctranslate2_cuda_available", lambda: True)
    assert faster_whisper_backend._resolve_device("auto") == "cuda"

    monkeypatch.setattr(faster_whisper_backend, "ctranslate2_cuda_available", lambda: False)
    assert faster_whisper_backend._resolve_device("auto") == "cpu"


def test_auto_compute_preserves_quality_on_cpu_and_cuda() -> None:
    assert faster_whisper_backend._resolve_compute_type("auto", "cuda") == "float16"
    assert faster_whisper_backend._resolve_compute_type("auto", "cpu") == "float32"


def test_gpu_compute_types_have_quality_preserving_cpu_fallbacks() -> None:
    assert faster_whisper_backend._resolve_compute_type("float16", "cpu") == "float32"
    assert faster_whisper_backend._resolve_compute_type("int8_float16", "cpu") == "int8_float32"
    assert faster_whisper_backend._resolve_compute_type("int8", "cpu") == "int8"
