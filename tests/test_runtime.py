import os
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
    assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"


def test_windowed_runtime_replaces_unusable_output_streams(monkeypatch) -> None:
    class InvalidWindowsStream:
        def write(self, _value: str) -> int:
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(sys, "stdout", InvalidWindowsStream())
    monkeypatch.setattr(sys, "stderr", InvalidWindowsStream())

    ensure_output_streams()

    assert sys.stdout.write("test") == 4
    assert sys.stderr.write("test") == 4
