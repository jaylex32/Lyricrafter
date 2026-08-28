from pathlib import Path
import sys
import types

from app.core.jobs import ProcessingOptions
from app.models.catalog import ModelManager
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

    def __init__(self, model_id: str, device: str, compute_type: str) -> None:
        self.device = device
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    def transcribe(self, *args, **kwargs):
        FakeWhisperModel.last_kwargs = kwargs
        return iter([FakeSegment()]), FakeInfo()


def test_cuda_cublas_failure_falls_back_to_cpu(tmp_path: Path) -> None:
    transcriber = FasterWhisperTranscriber(model_factory=FakeWhisperModel)
    messages: list[str] = []
    percents: list[int] = []

    result = transcriber.transcribe(
        tmp_path / "song.wav",
        ProcessingOptions(device="cuda", compute_type="float16"),
        lambda percent, message: (percents.append(percent), messages.append(message)),
    )

    assert result.segments[0].text == "Hello"
    assert any("retrying Whisper on CPU" in message for message in messages)
    assert 85 in percents
    assert "initial_prompt" not in FakeWhisperModel.last_kwargs
    assert "condition_on_previous_text" not in FakeWhisperModel.last_kwargs


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

    transcriber._get_model_factory()("tiny", device="cpu", compute_type="int8")

    assert captured["model_source"] == str(snapshot)
    assert captured["download_root"] == str(manager.faster_whisper_cache_dir())
