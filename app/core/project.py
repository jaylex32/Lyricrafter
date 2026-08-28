from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.jobs import JobResult, LyricJob
from app.export.lrc import LyricLine

PROJECT_VERSION = 1


def default_project_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}.lyricrafter.json")


def save_project(job: LyricJob, path: Path | None = None) -> Path:
    if not job.result:
        raise ValueError("Cannot save a project without generated lyrics.")
    target = path or default_project_path(job.source_path)
    target.write_text(json.dumps(_project_payload(job), indent=2), encoding="utf-8")
    return target


def load_project(path: Path) -> LyricJob:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("app") != "Lyricrafter":
        raise ValueError("This is not a Lyricrafter project file.")
    source_path = Path(str(payload["source_path"]))
    lines = [
        LyricLine(
            start=float(line.get("start", 0.0)),
            text=str(line.get("text", "")),
            translation=str(line["translation"]) if line.get("translation") is not None else None,
        )
        for line in payload.get("lines", [])
    ]
    result = JobResult(
        lrc_path=Path(str(payload.get("lrc_path") or source_path.with_suffix(".lrc"))),
        txt_path=Path(str(payload.get("txt_path") or source_path.with_suffix(".txt"))),
        lines=lines,
        plain_text="\n".join(line.text for line in lines),
        srt_path=Path(str(payload["srt_path"])) if payload.get("srt_path") else None,
        vtt_path=Path(str(payload["vtt_path"])) if payload.get("vtt_path") else None,
        embedded=bool(payload.get("embedded", False)),
        detected_language=payload.get("detected_language"),
        embed_error=payload.get("embed_error"),
        review_warnings=[str(item) for item in payload.get("review_warnings", [])],
        section_hints=[dict(item) for item in payload.get("section_hints", []) if isinstance(item, dict)],
    )
    return LyricJob(source_path=source_path, result=result, progress=100, message="Project reopened")


def _project_payload(job: LyricJob) -> dict[str, Any]:
    assert job.result is not None
    return {
        "app": "Lyricrafter",
        "version": PROJECT_VERSION,
        "source_path": str(job.source_path),
        "lrc_path": str(job.result.lrc_path),
        "txt_path": str(job.result.txt_path),
        "srt_path": str(job.result.srt_path) if job.result.srt_path else None,
        "vtt_path": str(job.result.vtt_path) if job.result.vtt_path else None,
        "detected_language": job.result.detected_language,
        "embedded": job.result.embedded,
        "embed_error": job.result.embed_error,
        "review_warnings": job.result.review_warnings,
        "section_hints": job.result.section_hints,
        "lines": [
            {
                "start": line.start,
                "text": line.text,
                "translation": line.translation,
            }
            for line in job.result.lines
        ],
    }
