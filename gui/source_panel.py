"""Evidence rail: filename, page, relevance, and the retrieved passage."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from database.models import Source
from gui.chat_view import WrapLabel
from gui.styles import MONO, SERIF, Palette


class RelevanceBar(QWidget):
    def __init__(self):
        super().__init__()
        self._value = 0.0
        self._track = QColor("#E4E0D4")
        self._fill = QColor("#5C6C74")
        self.setFixedHeight(3)

    def set_colors(self, track: str, fill: str) -> None:
        self._track = QColor(track)
        self._fill = QColor(fill)
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track)
        painter.drawRect(self.rect())
        width = int(self.width() * self._value)
        if width > 0:
            painter.setBrush(self._fill)
            painter.drawRect(0, 0, max(width, 4), self.height())
        painter.end()


class SourcePanel(QWidget):
    open_page = Signal(object)

    def __init__(self):
        super().__init__()
        self.setObjectName("EvidenceRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(420)
        self._palette: Palette | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(8)
        title = QLabel("Sources")
        title.setObjectName("PaneTitle")
        self.note = QLabel("The passages behind this answer.")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setObjectName("EvidenceBody")
        self.host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cards = QVBoxLayout(self.host)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(10)
        self.cards.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

    def show_sources(self, sources: list[Source], selected_id: str, note: str, palette: Palette) -> None:
        self._palette = palette
        self.scroll.viewport().setStyleSheet(f"background: {palette.bg}; border: none;")
        self.host.setStyleSheet(f"background: {palette.bg};")
        self.note.setText(note or "Passages behind the selected answer.")
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not sources:
            self.note.setText("The passages behind this answer.")
            return
        for source in sources:
            card = _card(source, source.chunk_id == selected_id, palette, self.open_page.emit)
            self.cards.insertWidget(self.cards.count() - 1, card)

    def evidence_text(self) -> str:
        parts = [self.note.text()]
        for index in range(self.cards.count()):
            widget = self.cards.itemAt(index).widget()
            if widget is not None:
                parts.append(widget.property("evidence") or "")
        return "\n".join(part for part in parts if part)


def _card(source: Source, selected: bool, palette: Palette, open_page) -> QFrame:
    frame = QFrame()
    frame.setProperty("evidence", f"{source.filename}\nPage {source.page}\n{source.text}")
    border = palette.ink if selected else palette.line
    frame.setObjectName("Slip")
    frame.setStyleSheet(
        f"QFrame#Slip {{ background: {palette.card}; border: 1px solid {border}; border-radius: 16px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 14)
    layout.setSpacing(8)
    number = QLabel(str(source.page))
    number.setStyleSheet(f'color: {palette.stamp}; font-family: "{SERIF}"; font-size: 28px;')
    layout.addWidget(number)
    name = WrapLabel(source.filename)
    name.setStyleSheet("font-weight: 600;")
    layout.addWidget(name)

    excerpt = WrapLabel(source.text)
    excerpt.setFont(QFont(SERIF, 10))
    excerpt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    excerpt.setStyleSheet(f'font-family: "{SERIF}"; font-size: 14px; color: {palette.ink};')
    layout.addWidget(excerpt)

    bar = RelevanceBar()
    bar.set_colors(palette.track, palette.muted)
    bar.set_value(source.semantic_score if source.semantic_score else source.score)
    layout.addWidget(bar)
    score = source.semantic_score if source.semantic_score else source.score
    score_label = QLabel(f"{score:.0%} match")
    score_label.setStyleSheet(f'color: {palette.muted}; font-family: "{MONO}"; font-size: 11px;')
    layout.addWidget(score_label)

    button = QPushButton("Open page")
    button.setObjectName("GhostButton")
    button.setToolTip("Show this PDF page next to the extracted text")
    button.clicked.connect(lambda: open_page(source))
    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
    return frame
