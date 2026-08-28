from __future__ import annotations

from array import array
import math
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QPointF, QRectF, QThread, Signal, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QListWidget, QTableWidget, QWidget

from app.core.media_tools import ffmpeg_location
from app.export.lrc import LyricLine
from app.lyrics.structure import LyricSection


class DropSourceList(QListWidget):
    paths_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class DropQueueTable(QTableWidget):
    paths_dropped = Signal(object)

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class SongMap(QWidget):
    section_selected = Signal(int)

    _COLORS = {
        "Intro": QColor("#55728f"),
        "Verse": QColor("#315f89"),
        "Pre-Chorus": QColor("#6f5b9a"),
        "Chorus": QColor("#237f78"),
        "Post-Chorus": QColor("#8a5e87"),
        "Hook": QColor("#a36d35"),
        "Bridge": QColor("#9b7540"),
        "Outro": QColor("#59616c"),
    }

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SongMap")
        self.setMinimumHeight(40)
        self.setMaximumHeight(44)
        self.setMouseTracking(True)
        self._sections: list[LyricSection] = []
        self._duration = 0.0
        self._active_index = -1

    def set_sections(self, sections: list[LyricSection], duration: float) -> None:
        self._sections = list(sections)
        self._duration = max(float(duration), max((section.end for section in sections), default=0.0))
        if self._active_index >= len(self._sections):
            self._active_index = -1
        self.update()

    def set_active_section(self, index: int) -> None:
        if index != self._active_index:
            self._active_index = index
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0d1319"))
        content = QRectF(6, 5, max(1, self.width() - 12), max(1, self.height() - 10))
        painter.setPen(QPen(QColor("#283541"), 1))
        painter.setBrush(QColor("#111a22"))
        painter.drawRoundedRect(content, 5, 5)
        if not self._sections or self._duration <= 0:
            painter.setPen(QColor("#718399"))
            painter.drawText(content, Qt.AlignCenter, "Load lyrics to build a song map")
            return

        for index, section in enumerate(self._sections):
            left = content.left() + (section.start / self._duration) * content.width()
            right = content.left() + (section.end / self._duration) * content.width()
            segment = QRectF(left + 1, content.top() + 1, max(3.0, right - left - 2), content.height() - 2)
            color = self._COLORS.get(section.kind, QColor("#45627b"))
            painter.setBrush(color)
            if index == self._active_index:
                painter.setPen(QPen(QColor("#ffffff"), 2))
            elif section.source == "manual":
                painter.setPen(QPen(QColor("#c3e0ff"), 1.4))
            else:
                painter.setPen(QPen(color.lighter(125), 1))
            painter.drawRoundedRect(segment, 4, 4)
            if segment.width() >= 52:
                painter.setPen(QColor("#f7fbff"))
                painter.drawText(segment.adjusted(5, 0, -5, 0), Qt.AlignCenter, section.label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            index = self._section_at_x(event.position().x())
            if index >= 0:
                self.section_selected.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        index = self._section_at_x(event.position().x())
        if index >= 0:
            section = self._sections[index]
            confidence = round(section.confidence * 100)
            self.setToolTip(
                f"{section.label}: {section.line_count} lines, {confidence}% confidence. Click to select."
            )
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def _section_at_x(self, x: float) -> int:
        if not self._sections or self._duration <= 0 or self.width() <= 12:
            return -1
        seconds = max(0.0, min(self._duration, ((x - 6) / max(1, self.width() - 12)) * self._duration))
        for index, section in enumerate(self._sections):
            if section.start <= seconds < section.end:
                return index
        return -1


class WaveformWorker(QThread):
    loaded = Signal(str, object, float)
    failed = Signal(str, str)

    def __init__(self, path: Path, bins: int = 3200) -> None:
        super().__init__()
        self.path = path
        self.bins = max(400, bins)

    def run(self) -> None:
        ffmpeg = ffmpeg_location()
        if not ffmpeg:
            self.failed.emit(str(self.path), "FFmpeg is required to draw the waveform.")
            return
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self.path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "4000",
            "-f",
            "f32le",
            "pipe:1",
        ]
        kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                **kwargs,
            )
        except Exception as exc:
            self.failed.emit(str(self.path), str(exc))
            return
        if result.returncode != 0 or not result.stdout:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            self.failed.emit(str(self.path), detail or "Could not decode waveform audio.")
            return

        samples = array("f")
        samples.frombytes(result.stdout)
        if sys.byteorder != "little":
            samples.byteswap()
        duration = len(samples) / 4000.0
        stride = max(1, math.ceil(len(samples) / self.bins))
        peaks: list[float] = []
        for start in range(0, len(samples), stride):
            stop = min(len(samples), start + stride)
            peak = 0.0
            for value in samples[start:stop]:
                peak = max(peak, abs(value))
            peaks.append(peak)
        nonzero = sorted(value for value in peaks if value > 0)
        reference = nonzero[min(len(nonzero) - 1, int(len(nonzero) * 0.98))] if nonzero else 1.0
        normalized = [min(1.0, value / max(0.0001, reference)) for value in peaks]
        self.loaded.emit(str(self.path), normalized, duration)


class LyricWaveform(QWidget):
    seek_requested = Signal(float)
    line_selected = Signal(int)
    timing_drag_started = Signal()
    timing_changed = Signal(int, float)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LyricWaveform")
        self.setMinimumHeight(72)
        self.setMouseTracking(True)
        self._peaks: list[float] = []
        self._lines: list[LyricLine] = []
        self._duration = 0.0
        self._playhead = 0.0
        self._zoom = 1.0
        self._view_start = 0.0
        self._active_row = -1
        self._selected_rows: set[int] = set()
        self._drag_row = -1

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(118)
        return hint

    def set_waveform(self, peaks: list[float], duration: float) -> None:
        self._peaks = list(peaks)
        self._duration = max(0.0, duration)
        self._view_start = 0.0
        self.update()

    def clear_waveform(self) -> None:
        self._peaks = []
        self._duration = 0.0
        self._view_start = 0.0
        self.update()

    def set_lines(self, lines: list[LyricLine]) -> None:
        self._lines = list(lines)
        self.update()

    def set_selected_rows(self, rows: set[int]) -> None:
        self._selected_rows = set(rows)
        self.update()

    def set_active_row(self, row: int) -> None:
        if row != self._active_row:
            self._active_row = row
            self.update()

    def set_playhead(self, seconds: float) -> None:
        self._playhead = max(0.0, seconds)
        if self._duration > 0 and self._zoom > 1:
            view_duration = self._view_duration()
            left_guard = self._view_start + view_duration * 0.12
            right_guard = self._view_start + view_duration * 0.88
            if self._playhead < left_guard or self._playhead > right_guard:
                self._view_start = self._clamp_view_start(self._playhead - view_duration * 0.32)
        self.update()

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * 1.6)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / 1.6)

    def fit(self) -> None:
        self._zoom = 1.0
        self._view_start = 0.0
        self.update()

    def _set_zoom(self, zoom: float) -> None:
        if self._duration <= 0:
            return
        center = self._view_start + self._view_duration() / 2
        self._zoom = max(1.0, min(16.0, zoom))
        self._view_start = self._clamp_view_start(center - self._view_duration() / 2)
        self.update()

    def _view_duration(self) -> float:
        return self._duration / max(1.0, self._zoom) if self._duration > 0 else 1.0

    def _clamp_view_start(self, start: float) -> float:
        return max(0.0, min(start, max(0.0, self._duration - self._view_duration())))

    def _time_to_x(self, seconds: float) -> float:
        content = self._content_rect()
        return content.left() + ((seconds - self._view_start) / self._view_duration()) * content.width()

    def _x_to_time(self, x: float) -> float:
        content = self._content_rect()
        ratio = (x - content.left()) / max(1.0, content.width())
        return max(0.0, min(self._duration, self._view_start + ratio * self._view_duration()))

    def _content_rect(self) -> QRectF:
        return QRectF(12, 20, max(1, self.width() - 24), max(1, self.height() - 34))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1118"))
        content = self._content_rect()
        painter.setPen(QPen(QColor("#243344"), 1))
        painter.drawRoundedRect(content, 7, 7)
        self._paint_grid(painter, content)
        self._paint_waveform(painter, content)
        self._paint_markers(painter, content)
        if self._duration <= 0:
            painter.setPen(QColor("#718399"))
            painter.drawText(content, Qt.AlignCenter, "Load a track to inspect its waveform and timing")

    def _paint_grid(self, painter: QPainter, content: QRectF) -> None:
        view_duration = self._view_duration()
        rough = max(0.1, view_duration / 8)
        power = 10 ** math.floor(math.log10(rough))
        step = next(value * power for value in (1, 2, 5, 10) if value * power >= rough)
        first = math.ceil(self._view_start / step) * step
        painter.setFont(self.font())
        value = first
        while value <= self._view_start + view_duration + 0.001:
            x = self._time_to_x(value)
            painter.setPen(QPen(QColor("#1d2a38"), 1))
            painter.drawLine(QPointF(x, content.top()), QPointF(x, content.bottom()))
            painter.setPen(QColor("#718399"))
            painter.drawText(QRectF(x + 4, 2, 70, 16), Qt.AlignLeft | Qt.AlignVCenter, _short_time(value))
            value += step

    def _paint_waveform(self, painter: QPainter, content: QRectF) -> None:
        if not self._peaks or self._duration <= 0:
            return
        start_ratio = self._view_start / self._duration
        end_ratio = (self._view_start + self._view_duration()) / self._duration
        first = max(0, int(start_ratio * len(self._peaks)))
        last = min(len(self._peaks), max(first + 1, int(math.ceil(end_ratio * len(self._peaks)))))
        visible = self._peaks[first:last]
        center = content.center().y()
        amplitude = content.height() * 0.36
        top_points: list[QPointF] = []
        bottom_points: list[QPointF] = []
        for index, peak in enumerate(visible):
            x = content.left() + (index / max(1, len(visible) - 1)) * content.width()
            top_points.append(QPointF(x, center - peak * amplitude))
            bottom_points.append(QPointF(x, center + peak * amplitude))
        polygon = QPolygonF(top_points + list(reversed(bottom_points)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#315f89"))
        painter.drawPolygon(polygon)
        painter.setPen(QPen(QColor("#62b0ff"), 1))
        painter.drawPolyline(QPolygonF(top_points))

    def _paint_markers(self, painter: QPainter, content: QRectF) -> None:
        right_time = self._view_start + self._view_duration()
        for row, line in enumerate(self._lines):
            if line.start < self._view_start or line.start > right_time:
                continue
            x = self._time_to_x(line.start)
            if row == self._active_row:
                color = QColor("#ffffff")
                width = 2.2
            elif row in self._selected_rows:
                color = QColor("#75bcff")
                width = 1.8
            else:
                color = QColor("#6d7f92")
                width = 1.0
            painter.setPen(QPen(color, width))
            painter.drawLine(QPointF(x, content.top() + 3), QPointF(x, content.bottom() - 3))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, content.top() + 8), 3.5, 3.5)
        if self._duration > 0 and self._view_start <= self._playhead <= right_time:
            x = self._time_to_x(self._playhead)
            painter.setPen(QPen(QColor("#4fa3ff"), 2))
            painter.drawLine(QPointF(x, content.top()), QPointF(x, content.bottom()))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4fa3ff"))
            painter.drawPolygon(QPolygonF([QPointF(x - 5, content.top()), QPointF(x + 5, content.top()), QPointF(x, content.top() + 7)]))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._duration <= 0:
            return super().mousePressEvent(event)
        nearest = self._nearest_marker(event.position().x())
        if nearest >= 0:
            self._drag_row = nearest
            self.timing_drag_started.emit()
            self.line_selected.emit(nearest)
        else:
            self.seek_requested.emit(self._x_to_time(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_row < 0 or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        start = self._constrained_start(self._drag_row, self._x_to_time(event.position().x()))
        line = self._lines[self._drag_row]
        self._lines[self._drag_row] = LyricLine(start=start, text=line.text, translation=line.translation)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_row >= 0:
            row = self._drag_row
            self._drag_row = -1
            self.timing_changed.emit(row, self._lines[row].start)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if self._duration <= 0:
            return super().wheelEvent(event)
        if event.modifiers() & Qt.ControlModifier:
            self._set_zoom(self._zoom * (1.25 if event.angleDelta().y() > 0 else 0.8))
        elif self._zoom > 1:
            shift = -event.angleDelta().y() / 120 * self._view_duration() * 0.12
            self._view_start = self._clamp_view_start(self._view_start + shift)
            self.update()
        event.accept()

    def _nearest_marker(self, x: float) -> int:
        best_row = -1
        best_distance = 8.0
        right_time = self._view_start + self._view_duration()
        for row, line in enumerate(self._lines):
            if self._view_start <= line.start <= right_time:
                distance = abs(self._time_to_x(line.start) - x)
                if distance < best_distance:
                    best_distance = distance
                    best_row = row
        return best_row

    def _constrained_start(self, row: int, start: float) -> float:
        lower = self._lines[row - 1].start + 0.05 if row > 0 else 0.0
        upper = self._lines[row + 1].start - 0.05 if row + 1 < len(self._lines) else self._duration
        if upper < lower:
            return lower
        return max(lower, min(upper, start))


def _short_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:d}:{minute:02d}:{second:02d}" if hours else f"{minute:02d}:{second:02d}"


class LyricrafterMark(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(42, 42)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(1, 1, 40, 40)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#66b7ff"))
        gradient.setColorAt(1.0, QColor("#2f88ff"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#78c4ff"), 1.2))
        painter.drawRoundedRect(rect, 10, 10)

        painter.setPen(QPen(QColor("#07111d"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        base_x = 10
        center_y = 22
        heights = [8, 15, 23, 13, 19, 10]
        for index, height in enumerate(heights):
            x = base_x + index * 4
            painter.drawLine(x, center_y - height / 2, x, center_y + height / 2)

        path = QPainterPath()
        path.moveTo(11, 31)
        path.cubicTo(17, 27, 23, 35, 31, 28)
        painter.setPen(QPen(QColor("#07111d"), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

        painter.setBrush(QColor("#07111d"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(28.5, 10.5, 5.5, 5.5))
