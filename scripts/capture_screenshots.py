from __future__ import annotations

import os
from pathlib import Path
import tempfile
import wave


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "screenshots"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lyricrafter-screenshots-", ignore_cleanup_errors=True) as temp:
        os.environ["LOCALAPPDATA"] = str(Path(temp) / "AppData")

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from app.core.jobs import JobResult, JobStatus, LyricJob
        from app.core.resources import app_icon_path
        from app.export.lrc import LyricLine, render_lrc, render_txt
        from app.ui.main_window import MainWindow
        from app.ui.theme import apply_theme

        app = QApplication([])
        app.setApplicationName("Lyricrafter")
        app.setOrganizationName("Lyricrafter")
        app.setWindowIcon(QIcon(str(app_icon_path())))
        apply_theme(app)

        workspace = Path(temp) / "Music"
        workspace.mkdir(parents=True)
        source = workspace / "Midnight Signal.flac"
        _write_silent_wave(source)
        lines = _demo_lines(LyricLine)
        lrc_path = source.with_suffix(".lrc")
        txt_path = source.with_suffix(".txt")
        lrc_path.write_text(render_lrc(lines), encoding="utf-8")
        txt_path.write_text(render_txt(lines), encoding="utf-8")
        result = JobResult(
            lrc_path=lrc_path,
            txt_path=txt_path,
            lines=lines,
            plain_text=render_txt(lines),
            detected_language="en",
            section_hints=[
                {"start_row": 0, "end_row": 3, "kind": "Intro", "source": "manual"},
                {"start_row": 4, "end_row": 9, "kind": "Verse", "source": "manual"},
                {"start_row": 10, "end_row": 13, "kind": "Chorus", "source": "manual"},
                {"start_row": 14, "end_row": 19, "kind": "Verse", "source": "manual"},
                {"start_row": 20, "end_row": 23, "kind": "Chorus", "source": "manual"},
            ],
        )
        complete = LyricJob(
            source_path=source,
            status=JobStatus.COMPLETE,
            progress=100,
            message="Lyrics synchronized",
            result=result,
        )
        running = LyricJob(
            source_path=workspace / "Afterglow Avenue.mp3",
            status=JobStatus.RUNNING,
            progress=68,
            message="Transcribing audio 148.2s / 218.4s",
        )
        queued = LyricJob(
            source_path=workspace / "Neon Skyline.wav",
            status=JobStatus.PENDING,
            progress=0,
            message="Ready",
        )

        window = MainWindow()
        window.resize(1500, 920)
        window._load_editor_waveform = lambda _path: None
        window.jobs = [complete, running, queued]
        window._refresh_queue()
        window.show()
        _capture(app, window, "queue.png")

        window.load_job_in_editor(complete)
        window.editor_title.setText(r"D:\Music\Midnight Signal.flac")
        window.waveform.set_waveform(_demo_peaks(), 96.0)
        window.waveform.set_lines(lines)
        window.lyric_table.selectRow(10)
        _capture(app, window, "editor.png")

        window._set_workspace_page(2)
        window._refresh_model_table()
        window.model_table.selectRow(9)
        _capture(app, window, "models.png")

        window.player.stop()
        window.player.setSource(QUrl())
        window.close()
        app.processEvents()
    return 0


def _capture(app, window, filename: str) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        app.processEvents()
    target = SCREENSHOTS / filename
    if not window.grab().save(str(target), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {target}")


def _write_silent_wave(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 16_000)


def _demo_lines(line_type):
    originals = [
        "The city hums beneath a silver sky",
        "Every window keeps a different light",
        "I trace the rhythm running through the street",
        "Waiting for the signal in the night",
        "We carried sparks inside our open hands",
        "Turned every shadow into something bright",
        "The radio was fading in and out",
        "But every word arrived at just the right time",
        "No map could tell us where the road would bend",
        "Still we followed every pulse of blue",
        "Send the midnight signal through the dark",
        "Let it find me wherever you are",
        "Every beat is pulling us in time",
        "Your voice is written in the skyline",
        "Morning found us miles beyond the signs",
        "With yesterday dissolving in the rain",
        "We learned the quiet has a melody",
        "And every ending starts the song again",
        "I hear the distant echo drawing near",
        "Clearer than it ever sounded before",
        "Send the midnight signal through the dark",
        "Let it find me wherever you are",
        "Every beat is pulling us in time",
        "Your voice is written in the skyline",
    ]
    translations = [
        "La ciudad vibra bajo un cielo plateado",
        "Cada ventana guarda una luz diferente",
        "Sigo el ritmo que recorre la calle",
        "Esperando la señal en la noche",
        "Llevamos chispas en las manos abiertas",
        "Convertimos cada sombra en algo brillante",
        "La radio se desvanecía poco a poco",
        "Pero cada palabra llegó justo a tiempo",
        "Ningún mapa mostraba la curva del camino",
        "Aun así seguimos cada pulso azul",
        "Envía la señal de medianoche por la oscuridad",
        "Deja que me encuentre donde quiera que estés",
        "Cada latido nos mantiene en el tiempo",
        "Tu voz está escrita en el horizonte",
        "La mañana nos encontró más allá de las señales",
        "Mientras el ayer se disolvía en la lluvia",
        "Aprendimos que el silencio tiene melodía",
        "Y cada final comienza la canción otra vez",
        "Escucho el eco distante acercándose",
        "Más claro de lo que había sonado antes",
        "Envía la señal de medianoche por la oscuridad",
        "Deja que me encuentre donde quiera que estés",
        "Cada latido nos mantiene en el tiempo",
        "Tu voz está escrita en el horizonte",
    ]
    return [
        line_type(
            start=4.0 + index * 3.75,
            text=text,
            translation=translations[index],
        )
        for index, text in enumerate(originals)
    ]


def _demo_peaks() -> list[float]:
    pattern = [0.16, 0.31, 0.22, 0.58, 0.37, 0.72, 0.44, 0.86, 0.53, 0.68, 0.29, 0.48]
    return [pattern[index % len(pattern)] * (0.82 + (index % 7) * 0.03) for index in range(900)]


if __name__ == "__main__":
    raise SystemExit(main())
