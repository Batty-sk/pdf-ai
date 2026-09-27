"""Conversation pane. User messages sit on the right; answers sit on the left."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from database.models import Message, Source
from gui.styles import SERIF, Palette
from rag.rag_pipeline import NOT_FOUND
from services.chat_service import sources_from_message


class WrapLabel(QLabel):
    """A label that wraps inside the width it is given, instead of growing to one long line."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.fontMetrics().boundingRect(
            0, 0, max(width, 1), 100000, int(Qt.TextFlag.TextWordWrap), self.text()
        ).height() + 2

    def sizeHint(self) -> QSize:
        line = self.fontMetrics().height() + 4
        return QSize(280, line)

    def minimumSizeHint(self) -> QSize:
        line = self.fontMetrics().height() + 4
        return QSize(80, line)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_fitting", False):
            return
        needed = self.heightForWidth(max(self.width(), 1))
        if abs(self.minimumHeight() - needed) > 2:
            self._fitting = True
            self.setMinimumHeight(needed)
            self._fitting = False
            self.updateGeometry()


class FlowLayout(QLayout):
    """Wraps citation chips onto extra lines when the sheet is narrow."""

    def __init__(self):
        super().__init__()
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(width, False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect.width(), True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + QSize(4, 4)

    def _arrange(self, width: int, place: bool) -> int:
        x = y = row_height = 0
        for item in self._items:
            hint = item.sizeHint()
            if x and x + hint.width() > width:
                x = 0
                y += row_height + 6
                row_height = 0
            if place:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + 6
            row_height = max(row_height, hint.height())
        return y + row_height


class FlowHost(QWidget):
    def __init__(self):
        super().__init__()
        self.flow = FlowLayout()
        self.setLayout(self.flow)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(max(width, 1))

    def sizeHint(self) -> QSize:
        return QSize(280, max(self.heightForWidth(280), 28))

    def minimumSizeHint(self) -> QSize:
        return QSize(80, self.heightForWidth(180))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        needed = self.heightForWidth(max(self.width(), 1))
        if abs(self.minimumHeight() - needed) > 2:
            self.setMinimumHeight(needed)
            self.updateGeometry()


class EnterText(QPlainTextEdit):
    """Enter sends. Shift+Enter inserts a line break."""

    def __init__(self, submit):
        super().__init__()
        self._submit = submit

    def keyPressEvent(self, event):
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if enter and not shift:
            self._submit()
            return
        super().keyPressEvent(event)


class Composer(QWidget):
    submit = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("ComposerShell")
        row = QHBoxLayout(shell)
        row.setContentsMargins(18, 10, 10, 10)
        row.setSpacing(8)
        self.input = EnterText(self._emit)
        self.input.setObjectName("Composer")
        self.input.setPlaceholderText("Ask about these documents")
        self.input.setFixedHeight(52)
        self.send = QPushButton("Send")
        self.send.setObjectName("PrimaryButton")
        self.send.setFixedSize(84, 40)
        self.send.setToolTip("Send (Enter). Shift+Enter adds a line.")
        self.send.clicked.connect(self._emit)
        row.addWidget(self.input, 1)
        row.addWidget(self.send, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(shell)

    def _emit(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.submit.emit(text)

    def set_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send.setEnabled(enabled)
        self.send.setText("Send" if enabled else "Sending…")


class ChatView(QWidget):
    # sources, selected chunk id, note shown above the evidence cards
    citation_selected = Signal(object, str, str)
    notice_dismissed = Signal()
    export_text = Signal()
    export_pdf = Signal()
    toggle_evidence = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("CenterRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 22, 32, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.title = QLabel("New chat")
        self.title.setObjectName("PaneTitle")
        header.addWidget(self.title, 1)
        self.export_txt_btn = QPushButton("Export text")
        self.export_pdf_btn = QPushButton("Export PDF")
        self.evidence_btn = QPushButton("Hide evidence")
        for button in (self.export_txt_btn, self.export_pdf_btn, self.evidence_btn):
            button.setObjectName("GhostButton")
        self.export_txt_btn.clicked.connect(self.export_text.emit)
        self.export_pdf_btn.clicked.connect(self.export_pdf.emit)
        self.evidence_btn.clicked.connect(self.toggle_evidence.emit)
        self.export_txt_btn.setToolTip("Save this conversation as a text file")
        self.export_pdf_btn.setToolTip("Save this conversation as a PDF")
        self.evidence_btn.setToolTip("Show or hide the source panel")
        header.addWidget(self.export_txt_btn)
        header.addWidget(self.export_pdf_btn)
        header.addWidget(self.evidence_btn)
        root.addLayout(header)

        self.notice = QFrame()
        notice_layout = QHBoxLayout(self.notice)
        notice_text = WrapLabel(
            "A question sends that question and short excerpts to your AI service. The PDFs stay on this computer."
        )
        notice_text.setWordWrap(True)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("GhostButton")
        dismiss.clicked.connect(self.notice_dismissed.emit)
        notice_layout.addWidget(notice_text, 1)
        notice_layout.addWidget(dismiss)
        root.addWidget(self.notice)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.transcript_root = QWidget()
        self.transcript_root.setObjectName("TranscriptBody")
        self.transcript_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.transcript_layout = QVBoxLayout(self.transcript_root)
        self.transcript_layout.setContentsMargins(0, 0, 8, 0)
        self.transcript_layout.setSpacing(22)
        self.transcript_layout.addStretch(1)
        self.scroll.setWidget(self.transcript_root)
        root.addWidget(self.scroll, 1)

        self.loading = QWidget()
        loading_row = QHBoxLayout(self.loading)
        loading_row.setContentsMargins(0, 0, 0, 0)
        self.loading_label = QLabel("Reading the relevant pages…")
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedWidth(120)
        self.loading_bar.setFixedHeight(6)
        self.loading_bar.setTextVisible(False)
        loading_row.addWidget(self.loading_label)
        loading_row.addWidget(self.loading_bar)
        loading_row.addStretch(1)
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.composer = Composer()
        root.addWidget(self.composer)

    def set_notice_visible(self, visible: bool) -> None:
        self.notice.setVisible(visible)

    def set_evidence_open(self, open_: bool) -> None:
        self.evidence_btn.setText("Hide evidence" if open_ else "Show evidence")

    def set_title(self, title: str) -> None:
        self._full_title = title
        width = max(self.title.width(), 280)
        self.title.setText(self.title.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, width))

    def set_busy(self, busy: bool) -> None:
        self.composer.set_enabled(not busy)
        self.loading.setVisible(busy)

    def apply_surface(self, palette: Palette) -> None:
        color = palette.bg
        self.scroll.viewport().setStyleSheet(f"background: {color}; border: none;")
        self.transcript_root.setStyleSheet(f"background: {color};")
        self.notice.setObjectName("Notice")
        self.notice.setStyleSheet("QFrame#Notice { background: transparent; border: none; }")

    def set_messages(self, messages: list[Message], palette: Palette) -> None:
        self.apply_surface(palette)
        self._clear()
        if not messages:
            self.transcript_layout.insertWidget(0, _empty_state())
        last_sources: list[Source] = []
        last_note = ""
        for message in messages:
            sources = sources_from_message(message.sources)
            row = _Bubble(message.role, message.content, sources, message.warning, palette)
            row.citation_selected.connect(self._on_citation)
            self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, row)
            if message.role == "assistant" and sources:
                last_sources = sources
                last_note = _note_for(message.content)
        selected = last_sources[0].chunk_id if last_sources else ""
        self.citation_selected.emit(last_sources, selected, last_note)
        self._scroll_bottom()

    def show_pending(self, question: str, messages: list[Message], palette: Palette) -> None:
        self.set_messages(messages, palette)
        self._remove_empty()
        row = _Bubble("user", question, [], None, palette)
        self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, row)
        self.set_busy(True)
        self._scroll_bottom()

    def transcript(self) -> str:
        chunks = []
        for index in range(self.transcript_layout.count()):
            widget = self.transcript_layout.itemAt(index).widget()
            if isinstance(widget, _Bubble):
                chunks.append(widget.body.text())
        return "\n".join(chunks)

    def _on_citation(self, sources: list[Source], chunk_id: str) -> None:
        note = ""
        self.citation_selected.emit(sources, chunk_id, note)

    def _clear(self) -> None:
        while self.transcript_layout.count():
            item = self.transcript_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.transcript_layout.addStretch(1)

    def _remove_empty(self) -> None:
        for index in range(self.transcript_layout.count() - 1, -1, -1):
            widget = self.transcript_layout.itemAt(index).widget()
            if widget is not None and widget.objectName() == "EmptyState":
                self.transcript_layout.takeAt(index)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _scroll_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class _Bubble(QWidget):
    citation_selected = Signal(object, str)

    def __init__(
        self,
        role: str,
        content: str,
        sources: list[Source],
        warning: str | None,
        palette: Palette,
    ):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._sources = sources
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        self.body = WrapLabel(content)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if role == "user":
            outer.addStretch(1)
            outer.addWidget(card)
            card.setMaximumWidth(480)
            card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(16, 10, 16, 10)
            card.setObjectName("UserNote")
            card.setStyleSheet(
                f"QFrame#UserNote {{ background: {palette.user_bubble}; border: none; border-radius: 16px; }}"
            )
            self.body = _hug_label(content, palette.user_text)
            inner.addWidget(self.body)
            return

        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        outer.addWidget(card, 1)
        card.setObjectName("Sheet")
        if warning == "error":
            inner = QVBoxLayout(card)
            inner.setContentsMargins(4, 2, 4, 2)
            card.setStyleSheet("QFrame#Sheet { background: transparent; border: none; }")
            self.body.setStyleSheet(f"color: {palette.danger}; font-size: 15px;")
            inner.addWidget(self.body)
            return

        card.setStyleSheet(
            f"QFrame#Sheet {{ background: {palette.card}; border: 1px solid {palette.line}; border-radius: 18px; }}"
        )
        column = QVBoxLayout(card)
        column.setContentsMargins(22, 18, 22, 18)
        column.setSpacing(14)
        page = sources[0].page if sources else None
        if page:
            column.addWidget(_folio(page, palette))
        self.body.setFont(QFont(SERIF, 13))
        self.body.setStyleSheet(
            f'color: {palette.ink}; background: transparent; font-family: "{SERIF}"; font-size: 17px;'
        )
        column.addWidget(self.body)
        if warning:
            note = QLabel(warning)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {palette.warning_ink}; font-size: 13px;")
            column.addWidget(note)
        if sources:
            chips = FlowHost()
            seen: set[tuple[str, int]] = set()
            for source in sources:
                key = (source.filename, source.page)
                if key in seen:
                    continue
                seen.add(key)
                button = QPushButton(f"{source.filename}  ·  {source.page}")
                button.setObjectName("CitationChip")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip("Show this passage beside the answer")
                button.clicked.connect(
                    lambda _checked=False, cid=source.chunk_id: self.citation_selected.emit(self._sources, cid)
                )
                chips.flow.addWidget(button)
            column.addWidget(chips)


def _hug_label(text: str, color: str) -> QLabel:
    """A question only as wide as its words, wrapping once it passes the reading measure."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
    advance = label.fontMetrics().horizontalAdvance(text)
    width = 440 if advance > 440 or "\n" in text else max(advance + 2, 24)
    label.setFixedWidth(width)
    if width >= 440:
        label.setMinimumHeight(label.heightForWidth(width))
    return label


def _folio(page: int | None, palette: Palette) -> QWidget:
    """A large quiet page number, set above the answer like a gallery label."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    number = QLabel(str(page) if page else "")
    number.setStyleSheet(f'color: {palette.stamp}; font-family: "{SERIF}"; font-size: 34px;')
    mark = QLabel("page" if page else "")
    mark.setStyleSheet(f'color: {palette.muted}; font-size: 12px;')
    layout.addWidget(number, 0, Qt.AlignmentFlag.AlignBaseline)
    layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignBaseline)
    layout.addStretch(1)
    return row


def _empty_state() -> QWidget:
    box = QWidget()
    box.setObjectName("EmptyState")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(4, 36, 8, 8)
    layout.setSpacing(8)
    title = QLabel("What do the pages say?")
    title.setObjectName("PaneTitle")
    body = QLabel("Add a PDF, then ask in your own words. The answer names the page it came from.")
    body.setObjectName("Muted")
    body.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(body)
    return box


def _note_for(content: str) -> str:
    if content.strip() == NOT_FOUND:
        return "Closest passages. They were not enough to answer."
    return ""
