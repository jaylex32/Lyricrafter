from pathlib import Path

from app.accuracy.hints import build_initial_prompt
from app.accuracy.profiles import profile_by_id
from app.core.engine import LyricrafterEngine
from app.core.jobs import AccuracyOptions, ProcessingOptions
from app.transcription.types import TranscriptSegment, TranscriptionResult


def test_profile_lookup_defaults_to_balanced() -> None:
    assert profile_by_id("studio_accurate").two_pass is True
    assert profile_by_id("missing").id == "balanced"
    assert profile_by_id("balanced").use_initial_prompt is False
    assert profile_by_id("balanced").condition_previous_text is None


def test_initial_prompt_includes_filename_and_user_hints(tmp_path: Path) -> None:
    source = tmp_path / "Artist - Song.flac"
    source.write_bytes(b"fake")

    prompt = build_initial_prompt(source, "special name")

    assert "sung lyrics" in prompt
    assert "Artist - Song" in prompt
    assert "special name" in prompt


class CountingTranscriber:
    def __init__(self) -> None:
        self.calls: list[ProcessingOptions] = []

    def transcribe(self, audio_path: Path, options: ProcessingOptions, progress=None) -> TranscriptionResult:
        self.calls.append(options)
        if progress:
            progress(100, "done")
        return TranscriptionResult(
            language="es",
            duration=1.0,
            segments=[TranscriptSegment(start=0.0, end=1.0, text="Hola mundo")],
        )


class NoopSeparator:
    def isolate_vocals(self, source_path: Path, options: ProcessingOptions, progress=None) -> Path:
        return source_path


def test_studio_accuracy_runs_two_pass_and_locks_language(tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.write_bytes(b"fake")
    transcriber = CountingTranscriber()
    engine = LyricrafterEngine(transcriber=transcriber, separator=NoopSeparator())

    result = engine.process(
        source,
        ProcessingOptions(
            version_existing=True,
            accuracy=AccuracyOptions(preset="studio_accurate"),
        ),
    )

    assert len(transcriber.calls) == 2
    assert transcriber.calls[1].language == "es"
    assert "First-pass lyric context" in transcriber.calls[1].accuracy.initial_prompt
    assert result.review_warnings == []


def test_balanced_accuracy_keeps_legacy_whisper_options(tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.write_bytes(b"fake")
    transcriber = CountingTranscriber()
    engine = LyricrafterEngine(transcriber=transcriber, separator=NoopSeparator())

    engine.process(source, ProcessingOptions(version_existing=True, accuracy=AccuracyOptions(preset="balanced")))

    assert len(transcriber.calls) == 1
    assert transcriber.calls[0].accuracy.initial_prompt is None
    assert transcriber.calls[0].accuracy.condition_previous_text is None
