from pathlib import Path

from app.core.jobs import JobResult, LyricJob
from app.core.project import default_project_path, load_project, save_project
from app.export.lrc import LyricLine


def test_default_project_path_uses_audio_stem() -> None:
    assert default_project_path(Path("mario.flac")).name == "mario.lyricrafter.json"


def test_save_and_load_project_roundtrip(tmp_path) -> None:
    source = tmp_path / "song.flac"
    job = LyricJob(
        source_path=source,
        result=JobResult(
            lrc_path=tmp_path / "song.lrc",
            txt_path=tmp_path / "song.txt",
            lines=[LyricLine(1.2, "Hola", "Hello")],
            plain_text="Hola",
            detected_language="es",
            section_hints=[{"start_row": 0, "end_row": 0, "kind": "Verse", "source": "manual"}],
        ),
    )

    project_path = save_project(job)
    loaded = load_project(project_path)

    assert project_path.name == "song.lyricrafter.json"
    assert loaded.source_path == source
    assert loaded.result is not None
    assert loaded.result.lines == [LyricLine(1.2, "Hola", "Hello")]
    assert loaded.result.detected_language == "es"
    assert loaded.result.section_hints == [
        {"start_row": 0, "end_row": 0, "kind": "Verse", "source": "manual"}
    ]
