from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.cuda import add_cuda_dll_directories
from app.core.resources import app_icon_path
from app.core.runtime import ensure_output_streams
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def main() -> int:
    ensure_output_streams()
    if "--package-smoke-test" in sys.argv:
        from app.release_smoke import run_package_smoke_test

        return run_package_smoke_test()
    ui_smoke = "--ui-smoke-test" in sys.argv
    add_cuda_dll_directories()
    app = QApplication(sys.argv)
    app.setApplicationName("Lyricrafter")
    app.setOrganizationName("Lyricrafter")
    icon = QIcon(str(app_icon_path()))
    app.setWindowIcon(icon)
    apply_theme(app)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    if ui_smoke:
        QTimer.singleShot(900, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
