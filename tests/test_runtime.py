import sys

from app.core.runtime import ensure_output_streams


def test_windowed_runtime_creates_missing_output_streams(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    ensure_output_streams()

    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdout.write("test") == 4
    assert sys.stderr.write("test") == 4
