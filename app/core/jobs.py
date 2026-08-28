from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from app.export.lrc import LyricLine


class JobStatus(str, Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETE = "Complete"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class AccuracyOptions:
    preset: str = "balanced"
    user_hints: str = ""
    use_metadata_hints: bool = True
    two_pass: bool = False
    lock_language: bool = True
    condition_previous_text: bool | None = None
    initial_prompt: str | None = None


@dataclass
class ProcessingOptions:
    model_id: str = "large-v2"
    language: str | None = None
    device: str = "auto"
    compute_type: str = "auto"
    quality_preset: str = "Balanced"
    vad_filter: bool = False
    vocal_isolation: bool = False
    separation_model: str = "htdemucs"
    normalize_audio: bool = False
    version_existing: bool = True
    embed_lyrics: bool = False
    export_lrc: bool = True
    export_txt: bool = True
    export_srt: bool = False
    export_vtt: bool = False
    accuracy: AccuracyOptions = field(default_factory=AccuracyOptions)


@dataclass
class JobResult:
    lrc_path: Path
    txt_path: Path
    lines: list[LyricLine]
    plain_text: str
    srt_path: Path | None = None
    vtt_path: Path | None = None
    embedded: bool = False
    detected_language: str | None = None
    embed_error: str | None = None
    review_warnings: list[str] = field(default_factory=list)
    section_hints: list[dict[str, object]] = field(default_factory=list)


@dataclass
class LyricJob:
    source_path: Path
    id: str = field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    message: str = "Queued"
    result: JobResult | None = None
    error: str | None = None
