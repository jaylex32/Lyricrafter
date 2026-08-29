from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from app.core.cuda import add_cuda_dll_directories, ctranslate2_cuda_available
from app.core.jobs import ProcessingOptions
from app.models.catalog import ModelManager
from app.transcription.types import TranscriptSegment, TranscriptionResult, WordTiming

ProgressCallback = Callable[[int, str], None]


class WhisperModelFactory(Protocol):
    def __call__(self, model_id: str, device: str, compute_type: str):
        ...


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_factory: WhisperModelFactory | None = None,
        model_manager: ModelManager | None = None,
    ) -> None:
        self._model_key: tuple[str, str, str] | None = None
        self._model = None
        self._model_factory = model_factory
        self._model_manager = model_manager or ModelManager()

    def set_model_manager(self, model_manager: ModelManager) -> None:
        if self._model_manager.model_dir == model_manager.model_dir:
            return
        self._model_manager = model_manager
        self._model_key = None
        self._model = None

    def transcribe(
        self,
        audio_path: Path,
        options: ProcessingOptions,
        progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        device = _resolve_device(options.device)
        compute_type = _resolve_compute_type(options.compute_type, device)
        attempts = [(device, compute_type)]
        if device == "cuda":
            attempts.append(("cpu", "int8"))

        last_error: Exception | None = None
        for attempt_index, (attempt_device, attempt_compute_type) in enumerate(attempts):
            try:
                return self._transcribe_with_device(
                    audio_path,
                    options,
                    attempt_device,
                    attempt_compute_type,
                    progress,
                )
            except Exception as exc:
                last_error = exc
                is_last_attempt = attempt_index == len(attempts) - 1
                if is_last_attempt or not _is_cuda_runtime_error(exc):
                    raise
                self._model_key = None
                self._model = None
                if progress:
                    progress(10, "CUDA runtime unavailable; retrying Whisper on CPU (int8)")

        raise RuntimeError(str(last_error) if last_error else "Transcription failed")

    def _transcribe_with_device(
        self,
        audio_path: Path,
        options: ProcessingOptions,
        device: str,
        compute_type: str,
        progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        model_factory = self._get_model_factory()
        model_key = (options.model_id, device, compute_type)
        if self._model_key != model_key:
            if progress:
                progress(8, f"Loading Whisper model: {options.model_id} on {device}")
            self._model = model_factory(options.model_id, device=device, compute_type=compute_type)
            self._model_key = model_key

        if progress:
            progress(20, "Transcribing audio")

        transcribe_kwargs = {
            "language": options.language or None,
            "vad_filter": options.vad_filter,
            "word_timestamps": True,
            "beam_size": 5,
        }
        if options.accuracy.initial_prompt:
            transcribe_kwargs["initial_prompt"] = options.accuracy.initial_prompt
        if options.accuracy.condition_previous_text is not None:
            transcribe_kwargs["condition_on_previous_text"] = options.accuracy.condition_previous_text
        segments_iter, info = self._model.transcribe(str(audio_path), **transcribe_kwargs)

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        segments: list[TranscriptSegment] = []
        for index, segment in enumerate(segments_iter):
            segment_end = float(segment.end)
            words = [
                WordTiming(start=float(word.start), end=float(word.end), text=str(word.word))
                for word in (segment.words or [])
                if word.start is not None and word.end is not None
            ]
            segments.append(
                TranscriptSegment(
                    start=float(segment.start),
                    end=segment_end,
                    text=str(segment.text),
                    words=words,
                )
            )
            if progress:
                if duration > 0:
                    transcribe_percent = int(20 + (min(segment_end, duration) / duration) * 65)
                else:
                    transcribe_percent = min(85, 20 + index)
                progress(
                    max(20, min(85, transcribe_percent)),
                    f"Transcribing audio {segment_end:.1f}s / {duration:.1f}s",
                )

        return TranscriptionResult(
            language=getattr(info, "language", None),
            duration=duration or getattr(info, "duration", None),
            segments=segments,
        )

    def _get_model_factory(self) -> WhisperModelFactory:
        if self._model_factory:
            return self._model_factory
        add_cuda_dll_directories()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: python -m pip install -e ."
            ) from exc
        manager = self._model_manager

        def create_model(model_id: str, device: str, compute_type: str):
            installed_path = manager.resolved_faster_whisper_path(model_id)
            model_source = str(installed_path) if installed_path else model_id
            return WhisperModel(
                model_source,
                device=device,
                compute_type=compute_type,
                download_root=str(manager.faster_whisper_cache_dir()),
            )

        return create_model


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    return "cuda" if ctranslate2_cuda_available() else "cpu"


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        if device == "cpu" and compute_type in {"float16", "int8_float16"}:
            return "int8"
        return compute_type
    return "float16" if device == "cuda" else "int8"


def _is_cuda_runtime_error(exc: Exception) -> bool:
    message = str(exc).lower()
    cuda_terms = ("cuda", "cublas", "cudnn", "cublas64_12", "cudart")
    load_terms = ("not found", "cannot be loaded", "could not load", "dll", "library")
    return any(term in message for term in cuda_terms) and any(term in message for term in load_terms)
