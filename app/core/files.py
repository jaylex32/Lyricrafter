from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import SUPPORTED_AUDIO_EXTENSIONS


@dataclass(frozen=True)
class OutputPair:
    lrc: Path
    txt: Path
    srt: Path | None = None
    vtt: Path | None = None


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def discover_audio_files(folder: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [path for path in folder.glob(pattern) if is_audio_file(path)]
    return sorted(files, key=lambda item: str(item).casefold())


def next_versioned_path(path: Path, label: str = "Lyricrafter") -> Path:
    if not path.exists():
        return path

    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({label} {index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def output_pair_for_audio(source: Path, version_existing: bool = True) -> OutputPair:
    base = source.with_suffix("")
    if not version_existing:
        return OutputPair(
            lrc=base.with_suffix(".lrc"),
            txt=base.with_suffix(".txt"),
            srt=base.with_suffix(".srt"),
            vtt=base.with_suffix(".vtt"),
        )

    index = 1
    while True:
        suffix = "" if index == 1 else f" (Lyricrafter {index})"
        candidate_base = base.with_name(f"{base.name}{suffix}")
        lrc = candidate_base.with_suffix(".lrc")
        txt = candidate_base.with_suffix(".txt")
        srt = candidate_base.with_suffix(".srt")
        vtt = candidate_base.with_suffix(".vtt")
        if not lrc.exists() and not txt.exists() and not srt.exists() and not vtt.exists():
            return OutputPair(lrc=lrc, txt=txt, srt=srt, vtt=vtt)
        index += 1
