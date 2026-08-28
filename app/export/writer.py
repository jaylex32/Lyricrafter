from __future__ import annotations

from pathlib import Path

from app.core.files import OutputPair, output_pair_for_audio
from app.export.lrc import LyricLine, render_lrc, render_srt, render_txt, render_vtt


def write_outputs(
    source: Path,
    lines: list[LyricLine],
    version_existing: bool = True,
    export_lrc: bool = True,
    export_txt: bool = True,
    export_srt: bool = False,
    export_vtt: bool = False,
) -> OutputPair:
    outputs = output_pair_for_audio(source, version_existing=version_existing)
    if export_lrc:
        outputs.lrc.write_text(render_lrc(lines), encoding="utf-8")
    if export_txt:
        outputs.txt.write_text(render_txt(lines), encoding="utf-8")
    if export_srt and outputs.srt:
        outputs.srt.write_text(render_srt(lines), encoding="utf-8")
    if export_vtt and outputs.vtt:
        outputs.vtt.write_text(render_vtt(lines), encoding="utf-8")
    return outputs
