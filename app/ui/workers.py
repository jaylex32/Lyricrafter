from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.core.engine import LyricrafterEngine
from app.core.jobs import JobResult, JobStatus, LyricJob, ProcessingOptions
from app.core.youtube import DEFAULT_FILENAME_TEMPLATE, download_url_audio
from app.lyrics.service import LyricsSourceService
from app.lyrics.types import LyricCandidate
from app.metadata.service import lookup_metadata_for_file
from app.metadata.tags import can_write_metadata, write_metadata
from app.models.catalog import ModelManager
from app.translation.nllb import NllbTranslator


class ProcessWorker(QThread):
    job_changed = Signal(object)
    progress_changed = Signal(str, int, str)
    job_finished = Signal(str, object)
    job_failed = Signal(str, str)
    all_finished = Signal()

    def __init__(
        self,
        jobs: list[LyricJob],
        options: ProcessingOptions,
        engine: LyricrafterEngine | None = None,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.options = options
        self.engine = engine or LyricrafterEngine()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self.jobs)
        for index, job in enumerate(self.jobs, start=1):
            if self._cancelled:
                job.status = JobStatus.CANCELLED
                job.message = "Cancelled"
                self.job_changed.emit(job)
                continue

            job.status = JobStatus.RUNNING
            job.progress = 0
            job.message = f"Starting file {index}/{total}"
            self.job_changed.emit(job)
            try:
                result = self.engine.process(
                    job.source_path,
                    self.options,
                    lambda progress, message, job_id=job.id, item_index=index, item_total=total: self.progress_changed.emit(
                        job_id,
                        progress,
                        f"File {item_index}/{item_total}: {message}",
                    ),
                )
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.message = str(exc)
                self.job_failed.emit(job.id, str(exc))
                self.job_changed.emit(job)
                continue

            job.status = JobStatus.COMPLETE
            job.progress = 100
            job.message = "Complete"
            job.result = result
            self.job_finished.emit(job.id, result)
            self.job_changed.emit(job)

        self.all_finished.emit()


class ModelDownloadWorker(QThread):
    progress = Signal(int, str)
    failed = Signal(str)
    finished_path = Signal(str)
    all_finished = Signal()

    def __init__(
        self,
        model_ids: list[str],
        backend: str = "faster-whisper",
        manager: ModelManager | None = None,
    ) -> None:
        super().__init__()
        self.model_ids = model_ids
        self.backend = backend
        self.manager = manager or ModelManager()

    def run(self) -> None:
        for index, model_id in enumerate(self.model_ids, start=1):
            try:
                self.progress.emit(0, f"Downloading {model_id} ({index}/{len(self.model_ids)})")
                if self.backend == "whisper.cpp":
                    path: Path = self.manager.download_whisper_cpp(
                        model_id,
                        lambda percent, message: self.progress.emit(
                            percent,
                            f"{message} - model {index}/{len(self.model_ids)}",
                        ),
                    )
                else:
                    path = self.manager.download_faster_whisper(
                        model_id,
                        lambda percent, message: self.progress.emit(
                            percent,
                            f"{message} - model {index}/{len(self.model_ids)}",
                        ),
                    )
            except Exception as exc:
                self.failed.emit(f"{model_id}: {exc}")
                return
            self.finished_path.emit(str(path))
        self.progress.emit(100, "All selected model downloads completed")
        self.all_finished.emit()


class TranslationWorker(QThread):
    progress = Signal(int, str)
    failed = Signal(str)
    finished_translations = Signal(object)

    def __init__(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model_id: str = "facebook/nllb-200-distilled-600M",
        translator: NllbTranslator | None = None,
        manager: ModelManager | None = None,
    ) -> None:
        super().__init__()
        self.texts = texts
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.translator = translator or NllbTranslator(
            model_id=model_id,
            model_dir=(manager or ModelManager()).model_dir,
        )

    def run(self) -> None:
        try:
            translations = self.translator.translate_lines(
                self.texts,
                self.source_lang,
                self.target_lang,
                lambda percent, message: self.progress.emit(percent, message),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_translations.emit(translations)


class UrlDownloadWorker(QThread):
    progress = Signal(int, str)
    failed = Signal(str)
    finished_path = Signal(str)
    all_finished = Signal(int)

    def __init__(
        self,
        urls: list[str],
        output_dir: Path | None = None,
        audio_format: str = "m4a",
        filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    ) -> None:
        super().__init__()
        self.urls = urls
        self.output_dir = output_dir
        self.audio_format = audio_format
        self.filename_template = filename_template

    def run(self) -> None:
        completed = 0
        total = len(self.urls)
        for index, url in enumerate(self.urls, start=1):
            try:
                path = download_url_audio(
                    url,
                    output_dir=self.output_dir,
                    audio_format=self.audio_format,
                    filename_template=self.filename_template,
                    progress=lambda percent, message, item_index=index, item_total=total: self.progress.emit(
                        _batch_percent(item_index, item_total, percent),
                        f"URL {item_index}/{item_total}: {message}",
                    ),
                )
            except Exception as exc:
                self.failed.emit(f"URL {index}/{total}: {exc}")
                return
            completed += 1
            self.finished_path.emit(str(path))
        self.all_finished.emit(completed)


class MetadataWorker(QThread):
    progress = Signal(int, str)
    file_finished = Signal(str, str)
    failed = Signal(str)
    all_finished = Signal(int)

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        completed = 0
        total = len(self.paths)
        for index, path in enumerate(self.paths, start=1):
            try:
                self.progress.emit(_batch_percent(index, total, 5), f"Looking up metadata for {path.name}")
                if not can_write_metadata(path):
                    self.file_finished.emit(str(path), "Metadata unsupported for this file type")
                    continue
                metadata = lookup_metadata_for_file(path)
                if metadata is None:
                    self.file_finished.emit(str(path), "No metadata match found")
                    continue
                self.progress.emit(_batch_percent(index, total, 75), f"Embedding metadata and cover for {path.name}")
                write_metadata(path, metadata)
                completed += 1
                label = metadata.title or path.name
                self.file_finished.emit(str(path), f"Metadata embedded: {label}")
            except Exception as exc:
                self.failed.emit(f"{path.name}: {exc}")
                self.file_finished.emit(str(path), f"Metadata failed: {exc}")
        self.all_finished.emit(completed)


class LyricsSourceWorker(QThread):
    progress = Signal(int, str)
    found = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        path: Path,
        enabled_sources: dict[str, bool],
        manual_search: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.path = path
        self.enabled_sources = enabled_sources
        self.manual_search = manual_search or {}

    def run(self) -> None:
        try:
            service = LyricsSourceService(self.enabled_sources)
            self.progress.emit(10, "Reading tags")
            query = service.build_query(self.path)
            if any(value.strip() for value in self.manual_search.values()):
                query = replace(
                    query,
                    title=self.manual_search.get("title", "").strip() or query.title,
                    artist=self.manual_search.get("artist", "").strip() or query.artist,
                    album=self.manual_search.get("album", "").strip() or query.album,
                )
            self.progress.emit(35, "Searching sources")
            candidates: list[LyricCandidate] = service.search(query)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.progress.emit(100, f"Found {len(candidates)} candidate(s)")
        self.found.emit(candidates)


class BatchLyricsSourceWorker(QThread):
    progress = Signal(int, str)
    item_found = Signal(str, object)
    failed = Signal(str)
    all_finished = Signal()

    def __init__(
        self,
        jobs: list[LyricJob],
        enabled_sources: dict[str, bool],
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.enabled_sources = enabled_sources
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self.jobs)
        service = LyricsSourceService(self.enabled_sources)
        for index, job in enumerate(self.jobs, start=1):
            if self._cancelled:
                break
            try:
                self.progress.emit(_batch_percent(index, total, 15), f"Reading tags for {job.source_path.name}")
                query = service.build_query(job.source_path)
                self.progress.emit(_batch_percent(index, total, 45), f"Searching sources for {job.source_path.name}")
                candidates = service.search(query)
                self.item_found.emit(job.id, candidates)
                self.progress.emit(_batch_percent(index, total, 100), f"Found {len(candidates)} source match(es)")
            except Exception as exc:
                self.failed.emit(f"{job.source_path.name}: {exc}")
                self.item_found.emit(job.id, [])
        self.all_finished.emit()


def _batch_percent(index: int, total: int, item_percent: int) -> int:
    if total <= 0:
        return 0
    completed_before = index - 1
    return int(((completed_before + (max(0, min(100, item_percent)) / 100)) / total) * 100)
