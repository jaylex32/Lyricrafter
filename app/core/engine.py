from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from app.accuracy.hints import build_initial_prompt
from app.accuracy.profiles import profile_by_id
from app.core.jobs import JobResult, ProcessingOptions
from app.core.quality import check_lyrics_quality, format_quality_report
from app.export.embed import embed_lyrics
from app.export.writer import write_outputs
from app.models.catalog import ModelManager
from app.separation.demucs_backend import DemucsSeparator
from app.transcription.faster_whisper_backend import FasterWhisperTranscriber
from app.transcription.lyrics import transcript_to_lyric_lines

ProgressCallback = Callable[[int, str], None]


class LyricrafterEngine:
    def __init__(
        self,
        transcriber: FasterWhisperTranscriber | None = None,
        separator: DemucsSeparator | None = None,
        model_manager: ModelManager | None = None,
    ) -> None:
        self.transcriber = transcriber or FasterWhisperTranscriber(model_manager=model_manager)
        self.separator = separator or DemucsSeparator()

    def set_model_manager(self, model_manager: ModelManager) -> None:
        self.transcriber.set_model_manager(model_manager)

    def process(
        self,
        source_path: Path,
        options: ProcessingOptions,
        progress: ProgressCallback | None = None,
    ) -> JobResult:
        options = self._apply_accuracy_profile(source_path, options)
        audio_for_transcription = source_path
        if options.vocal_isolation:
            try:
                audio_for_transcription = self.separator.isolate_vocals(source_path, options, progress)
            except Exception as exc:
                if progress:
                    progress(16, f"Vocal isolation failed; using original audio ({exc})")
                audio_for_transcription = source_path

        if progress:
            progress(18, "Preparing transcription")
        if options.accuracy.two_pass:
            first_options = replace(options, accuracy=replace(options.accuracy, two_pass=False))
            transcript = self.transcriber.transcribe(
                audio_for_transcription,
                first_options,
                _scaled_progress(progress, 18, 52, "First pass: ") if progress else None,
            )
            language = transcript.language if options.accuracy.lock_language else options.language
            second_prompt = _two_pass_prompt(options.accuracy.initial_prompt, transcript)
            second_accuracy = replace(options.accuracy, initial_prompt=second_prompt, two_pass=False)
            second_options = replace(options, language=language, accuracy=second_accuracy)
            if progress:
                progress(54, "Second pass with lyric context")
            transcript = self.transcriber.transcribe(
                audio_for_transcription,
                second_options,
                _scaled_progress(progress, 54, 86, "Second pass: ") if progress else None,
            )
        else:
            transcript = self.transcriber.transcribe(audio_for_transcription, options, progress)

        if progress:
            progress(88, "Building lyric lines")
        lines = transcript_to_lyric_lines(transcript.segments)
        review_warnings = [
            warning
            for warning in format_quality_report(check_lyrics_quality(lines)).splitlines()
            if not warning.startswith("Pass:")
        ]
        outputs = write_outputs(
            source_path,
            lines,
            version_existing=options.version_existing,
            export_lrc=options.export_lrc,
            export_txt=options.export_txt,
            export_srt=options.export_srt,
            export_vtt=options.export_vtt,
        )
        embedded = False
        embed_error = None
        if options.embed_lyrics:
            if progress:
                progress(94, "Embedding lyrics in audio metadata")
            try:
                embedded = embed_lyrics(source_path, lines)
            except PermissionError as exc:
                embed_error = f"Could not embed lyrics: permission denied for {source_path}"
                if progress:
                    progress(96, f"{embed_error}. Sidecar files were created.")
            except OSError as exc:
                embed_error = f"Could not embed lyrics: {exc}"
                if progress:
                    progress(96, f"{embed_error}. Sidecar files were created.")

        if progress:
            progress(100, "Finished" if not embed_error else "Finished with embed warning")
        return JobResult(
            lrc_path=outputs.lrc,
            txt_path=outputs.txt,
            lines=lines,
            plain_text=outputs.txt.read_text(encoding="utf-8") if outputs.txt.exists() else "",
            srt_path=outputs.srt if options.export_srt else None,
            vtt_path=outputs.vtt if options.export_vtt else None,
            embedded=embedded,
            detected_language=transcript.language,
            embed_error=embed_error,
            review_warnings=review_warnings,
        )

    def _apply_accuracy_profile(self, source_path: Path, options: ProcessingOptions) -> ProcessingOptions:
        profile = profile_by_id(options.accuracy.preset)
        accuracy = replace(
            options.accuracy,
            use_metadata_hints=options.accuracy.use_metadata_hints and profile.use_metadata_hints,
            two_pass=options.accuracy.two_pass or profile.two_pass,
            lock_language=options.accuracy.lock_language and profile.lock_language,
            condition_previous_text=(
                options.accuracy.condition_previous_text
                if options.accuracy.condition_previous_text is not None
                else profile.condition_previous_text
            ),
        )
        prompt = (
            build_initial_prompt(source_path, accuracy.user_hints, accuracy.use_metadata_hints)
            if profile.use_initial_prompt or accuracy.user_hints.strip()
            else None
        )
        accuracy = replace(accuracy, initial_prompt=prompt)
        return replace(
            options,
            vad_filter=options.vad_filter or profile.vad_filter,
            vocal_isolation=options.vocal_isolation or profile.prefer_vocal_isolation,
            accuracy=accuracy,
        )


def _scaled_progress(
    progress: ProgressCallback,
    start: int,
    end: int,
    prefix: str = "",
) -> ProgressCallback:
    span = max(1, end - start)

    def emit(percent: int, message: str) -> None:
        scaled = start + int((max(0, min(100, percent)) / 100) * span)
        progress(max(start, min(end, scaled)), f"{prefix}{message}")

    return emit


def _two_pass_prompt(initial_prompt: str, transcript) -> str:
    preview = " ".join(segment.text.strip() for segment in transcript.segments[:8] if segment.text.strip())
    if not preview:
        return initial_prompt
    return f"{initial_prompt} First-pass lyric context: {preview}"[:1200]
