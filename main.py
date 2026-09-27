"""Launch PDF AI Assistant."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from gui.main_window import MainWindow
    from gui.styles import SANS, app_icon, load_fonts
    from services.container import build_context
    from utils.config import APP_NAME

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    load_fonts()
    app.setFont(QFont(SANS, 10))
    app.setWindowIcon(app_icon())
    window = MainWindow(build_context())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
