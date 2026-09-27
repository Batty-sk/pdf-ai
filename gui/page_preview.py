"""Show one PDF page beside the passage that was retrieved from it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database.models import Source
from gui.styles import MONO, SERIF
from rag.pdf_loader import render_page_image


class PagePreviewDialog(QDialog):
    def __init__(self, source: Source, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{source.filename} — page {source.page}")
        self.resize(920, 680)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        pixmap = _page_pixmap(source)
        if pixmap is None:
            image_label.setWordWrap(True)
            image_label.setText("The page image is unavailable. The extracted text is on the right.")
        else:
            image_label.setPixmap(pixmap)
        image_scroll.setWidget(image_label)
        layout.addWidget(image_scroll, 3)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        title = QLabel(f"{source.filename}")
        title.setWordWrap(True)
        title.setStyleSheet(f'font-family: "{SERIF}"; font-size: 20px;')
        page = QLabel(f"p. {source.page}")
        page.setStyleSheet(f'font-family: "{MONO}"; font-size: 12px;')
        excerpt = QLabel(source.text)
        excerpt.setWordWrap(True)
        excerpt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        excerpt.setFont(self.font())
        excerpt.setStyleSheet(f'font-family: "{SERIF}"; font-size: 15px;')
        side_layout.addWidget(title)
        side_layout.addWidget(page)
        side_layout.addWidget(excerpt)
        side_layout.addStretch(1)
        layout.addWidget(side, 2)


def _page_pixmap(source: Source) -> QPixmap | None:
    if not source.stored_path:
        return None
    rendered = render_page_image(source.stored_path, source.page)
    if rendered is None:
        return None
    image = QImage(
        rendered.samples,
        rendered.width,
        rendered.height,
        rendered.stride,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(image.copy())
