from pathlib import Path

from app.core.files import discover_audio_files, output_pair_for_audio


def test_output_pair_uses_source_basename(tmp_path: Path) -> None:
    source = tmp_path / "mario.flac"
    source.write_bytes(b"fake")

    outputs = output_pair_for_audio(source)

    assert outputs.lrc == tmp_path / "mario.lrc"
    assert outputs.txt == tmp_path / "mario.txt"


def test_output_pair_versions_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "mario.flac"
    source.write_bytes(b"fake")
    (tmp_path / "mario.lrc").write_text("old", encoding="utf-8")
    (tmp_path / "mario.txt").write_text("old", encoding="utf-8")

    outputs = output_pair_for_audio(source)

    assert outputs.lrc == tmp_path / "mario (Lyricrafter 2).lrc"
    assert outputs.txt == tmp_path / "mario (Lyricrafter 2).txt"


def test_output_pair_versions_both_files_when_only_one_exists(tmp_path: Path) -> None:
    source = tmp_path / "mario.flac"
    source.write_bytes(b"fake")
    (tmp_path / "mario.lrc").write_text("old", encoding="utf-8")

    outputs = output_pair_for_audio(source)

    assert outputs.lrc == tmp_path / "mario (Lyricrafter 2).lrc"
    assert outputs.txt == tmp_path / "mario (Lyricrafter 2).txt"


def test_discover_audio_files_filters_and_sorts(tmp_path: Path) -> None:
    (tmp_path / "b.wav").write_bytes(b"")
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("skip", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.flac").write_bytes(b"")

    assert [path.name for path in discover_audio_files(tmp_path)] == ["a.mp3", "b.wav"]
    assert [path.name for path in discover_audio_files(tmp_path, recursive=True)] == [
        "a.mp3",
        "b.wav",
        "c.flac",
    ]
