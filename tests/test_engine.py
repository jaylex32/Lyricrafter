from pathlib import Path

from app.core.engine import LyricrafterEngine
from app.core.jobs import ProcessingOptions
from app.export import embed as embed_module
from app.transcription.types import TranscriptSegment, TranscriptionResult, WordTiming


class FakeTranscriber:
    def transcribe(self, audio_path: Path, options: ProcessingOptions, progress=None) -> TranscriptionResult:
        if progress:
            progress(50, "fake")
        return TranscriptionResult(
            language="en",
            duration=3.0,
            segments=[
                TranscriptSegment(
                    start=0.0,
                    end=2.0,
                    text="Hello world",
                    words=[
                        WordTiming(0.0, 0.4, "Hello"),
                        WordTiming(0.5, 1.0, "world"),
                    ],
                )
            ],
        )


def test_engine_writes_lrc_and_txt(tmp_path: Path) -> None:
    source = tmp_path / "song.flac"
    source.write_bytes(b"fake audio")
    engine = LyricrafterEngine(transcriber=FakeTranscriber())

    result = engine.process(source, ProcessingOptions(version_existing=True))

    assert result.lrc_path == tmp_path / "song.lrc"
    assert result.txt_path == tmp_path / "song.txt"
    assert result.lrc_path.read_text(encoding="utf-8") == "[00:00.00] Hello world\n"
    assert result.txt_path.read_text(encoding="utf-8") == "Hello world\n"


def test_engine_keeps_sidecars_when_embedding_permission_fails(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "song.flac"
    source.write_bytes(b"fake audio")

    def fail_embed(path, lines):
        raise PermissionError("locked")

    monkeypatch.setattr(embed_module, "embed_lyrics", fail_embed)
    monkeypatch.setattr("app.core.engine.embed_lyrics", fail_embed)
    engine = LyricrafterEngine(transcriber=FakeTranscriber())

    result = engine.process(source, ProcessingOptions(version_existing=True, embed_lyrics=True))

    assert result.lrc_path.exists()
    assert result.txt_path.exists()
    assert result.embedded is False
    assert result.embed_error is not None


def test_engine_respects_optional_output_formats(tmp_path: Path) -> None:
    source = tmp_path / "song.flac"
    source.write_bytes(b"fake audio")
    engine = LyricrafterEngine(transcriber=FakeTranscriber())

    result = engine.process(
        source,
        ProcessingOptions(version_existing=True, export_lrc=False, export_txt=True, export_srt=True, export_vtt=False),
    )

    assert not result.lrc_path.exists()
    assert result.txt_path.exists()
    assert result.srt_path is not None
    assert result.srt_path.exists()
    assert result.vtt_path is None
