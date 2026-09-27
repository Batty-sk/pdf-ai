"""Left sidebar: chats, the PDF library, and navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database.models import Chat, Document


class Sidebar(QWidget):
    new_chat = Signal()
    chat_selected = Signal(str)
    rename_chat = Signal(str)
    delete_chat = Signal(str)
    clear_chat = Signal(str)
    add_pdfs = Signal()
    remove_document = Signal()
    clear_documents = Signal()
    documents_changed = Signal(list)
    files_dropped = Signal(list)
    open_compare = Signal()
    open_settings = Signal()
    open_about = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(250)
        self.setMaximumWidth(320)
        self.setAcceptDrops(True)
        self._loading_docs = False
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 22, 18, 18)
        root.setSpacing(10)

        brand = QLabel("PDF AI Assistant")
        brand.setObjectName("Brand")
        mark = QLabel("The page comes with the answer")
        mark.setObjectName("Muted")
        root.addWidget(brand)
        root.addWidget(mark)

        self.new_button = QPushButton("New chat")
        self.new_button.setObjectName("PrimaryButton")
        self.new_button.setToolTip("Start a chat with the checked documents")
        self.new_button.clicked.connect(self.new_chat.emit)
        root.addWidget(self.new_button)

        chats_label = QLabel("Chats")
        chats_label.setObjectName("Section")
        root.addWidget(chats_label)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("ChatList")
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._chat_menu)
        self.chat_list.currentItemChanged.connect(self._on_chat)
        root.addWidget(self.chat_list, 2)

        docs_label = QLabel("Library")
        docs_label.setObjectName("Section")
        root.addWidget(docs_label)
        self.doc_list = QListWidget()
        self.doc_list.setObjectName("DocList")
        self.doc_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.doc_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.doc_list.itemChanged.connect(self._on_docs)
        root.addWidget(self.doc_list, 3)
        self.empty_docs = QLabel("Drop a PDF here, or use Add PDF.")
        self.empty_docs.setObjectName("Muted")
        self.empty_docs.setWordWrap(True)
        root.addWidget(self.empty_docs)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.add_button = QPushButton("Add PDF")
        self.remove_button = QPushButton("Remove")
        self.add_button.setObjectName("LibraryAdd")
        self.remove_button.setObjectName("LibraryRemove")
        self.add_button.setToolTip("Add one or more PDFs")
        self.remove_button.setToolTip("Remove the selected PDF from the library")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_pdfs.emit)
        self.remove_button.clicked.connect(self.remove_document.emit)
        for button in (self.add_button, self.remove_button):
            button.setIconSize(QSize(16, 16))
            button.setMinimumHeight(36)
        add_row.addWidget(self.add_button)
        add_row.addWidget(self.remove_button)
        root.addLayout(add_row)

        self.clear_button = QPushButton("Clear all PDFs")
        self.clear_button.setObjectName("LibraryClear")
        self.clear_button.setIconSize(QSize(16, 16))
        self.clear_button.setMinimumHeight(36)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip("Remove every PDF and its search index")
        self.clear_button.clicked.connect(self.clear_documents.emit)
        root.addWidget(self.clear_button)

        root.addStretch(1)
        self.compare_button = QPushButton("Compare documents")
        self.settings_button = QPushButton("Settings")
        self.about_button = QPushButton("About")
        for button, signal, tip in (
            (self.compare_button, self.open_compare, "Compare two PDFs side by side"),
            (self.settings_button, self.open_settings, "Model, retrieval, and appearance"),
            (self.about_button, self.open_about, "What this application does"),
        ):
            button.setCheckable(True)
            button.setToolTip(tip)
            button.clicked.connect(signal.emit)
            root.addWidget(button)

        self.progress = QLabel("")
        self.progress.setObjectName("Muted")
        self.progress.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        root.addWidget(self.progress)
        root.addWidget(self.bar)

    def apply_palette(self, palette) -> None:
        self.add_button.setIcon(_line_icon("add", palette.plate_text))
        self.remove_button.setIcon(_line_icon("remove", palette.ink))
        self.clear_button.setIcon(_line_icon("clear", palette.danger))

    def set_progress(self, text: str, busy: bool) -> None:
        self.progress.setText(text)
        self.bar.setVisible(busy)

    def set_nav(self, which: str) -> None:
        mapping = {
            "compare": self.compare_button,
            "settings": self.settings_button,
            "about": self.about_button,
        }
        for key, button in mapping.items():
            button.setChecked(key == which)

    def set_chats(self, chats: list[Chat], current_id: str) -> None:
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        selected = None
        for chat in chats:
            item = QListWidgetItem(chat.title)
            item.setData(Qt.ItemDataRole.UserRole, chat.id)
            item.setToolTip(chat.title)
            self.chat_list.addItem(item)
            if chat.id == current_id:
                selected = item
        if selected is not None:
            self.chat_list.setCurrentItem(selected)
        self.chat_list.blockSignals(False)

    def set_documents(self, documents: list[Document], checked_ids: set[str]) -> None:
        self._loading_docs = True
        self.doc_list.blockSignals(True)
        self.doc_list.clear()
        for document in documents:
            label = document.filename
            if document.status == "ready" and document.page_count:
                label = f"{document.filename}  ·  {document.page_count} pages"
            elif document.status == "error":
                label = f"{document.filename}  ·  failed"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, document.id)
            item.setToolTip(document.error_message or document.filename)
            if document.ocr_used:
                item.setToolTip(f"{document.filename}\nText was read with OCR. Check the excerpts.")
            if document.status == "ready":
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if document.id in checked_ids else Qt.CheckState.Unchecked
                )
            self.doc_list.addItem(item)
        self.doc_list.blockSignals(False)
        self._loading_docs = False
        self.empty_docs.setVisible(not documents)

    def selected_document_id(self) -> str:
        item = self.doc_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def checked_document_ids(self) -> list[str]:
        ids = []
        for index in range(self.doc_list.count()):
            item = self.doc_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def dragEnterEvent(self, event):
        if _pdf_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = _pdf_paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def _on_chat(self, current, _previous):
        if current is None:
            return
        chat_id = current.data(Qt.ItemDataRole.UserRole)
        if chat_id:
            self.chat_selected.emit(str(chat_id))

    def _on_docs(self, _item):
        if self._loading_docs:
            return
        self.documents_changed.emit(self.checked_document_ids())

    def _chat_menu(self, position):
        item = self.chat_list.itemAt(position)
        if item is None:
            return
        chat_id = str(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        rename = QAction("Rename", self)
        clear = QAction("Clear conversation", self)
        delete = QAction("Delete", self)
        rename.triggered.connect(lambda: self.rename_chat.emit(chat_id))
        clear.triggered.connect(lambda: self.clear_chat.emit(chat_id))
        delete.triggered.connect(lambda: self.delete_chat.emit(chat_id))
        menu.addAction(rename)
        menu.addAction(clear)
        menu.addAction(delete)
        menu.exec(self.chat_list.mapToGlobal(position))


def _line_icon(kind: str, color: str) -> QIcon:
    """A 16px line icon drawn at 2x so it stays sharp on a retina screen."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "add":
        painter.drawRoundedRect(7, 4, 14, 18, 2, 2)
        painter.drawLine(11, 8, 17, 8)
        painter.drawLine(22, 18, 22, 28)
        painter.drawLine(17, 23, 27, 23)
    elif kind == "remove":
        painter.drawRoundedRect(7, 4, 14, 18, 2, 2)
        painter.drawLine(16, 20, 26, 30)
        painter.drawLine(26, 20, 16, 30)
    else:
        painter.drawRoundedRect(8, 8, 16, 16, 2, 2)
        painter.drawLine(6, 8, 26, 8)
        painter.drawLine(13, 8, 14, 5)
        painter.drawLine(14, 5, 18, 5)
        painter.drawLine(18, 5, 19, 8)
        painter.drawLine(13, 13, 13, 20)
        painter.drawLine(19, 13, 19, 20)
    painter.end()
    return QIcon(pixmap)


def _pdf_paths(event) -> list[str]:
    if not event.mimeData().hasUrls():
        return []
    paths = []
    for url in event.mimeData().urls():
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
            paths.append(url.toLocalFile())
    return paths
