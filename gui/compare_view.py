"""Ask what changed between two PDFs and show a topic table."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.models import CompareResult, Document


class CompareView(QWidget):
    back = Signal()
    compare_requested = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("CompareRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("Compare documents")
        title.setObjectName("PaneTitle")
        back = QPushButton("Back to chat")
        back.setObjectName("GhostButton")
        back.clicked.connect(self.back.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(back)
        root.addLayout(header)

        intro = QLabel(
            "Pick two PDFs. Each statement in the table is drawn from that document's passages, "
            "and those passages are sent to your AI service."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        root.addWidget(intro)

        row = QHBoxLayout()
        self.left = QComboBox()
        self.right = QComboBox()
        self.left.setToolTip("First document")
        self.right.setToolTip("Second document")
        row.addWidget(self.left, 1)
        row.addWidget(self.right, 1)
        root.addLayout(row)

        ask = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("What changed between these documents?")
        self.run = QPushButton("Compare")
        self.run.setObjectName("PrimaryButton")
        self.run.clicked.connect(self._emit)
        ask.addWidget(self.question, 1)
        ask.addWidget(self.run)
        root.addLayout(ask)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Topic", "Document 1", "Document 2"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def set_documents(self, documents: list[Document]) -> None:
        current_left = self.left.currentData()
        current_right = self.right.currentData()
        self.left.clear()
        self.right.clear()
        ready = [document for document in documents if document.status == "ready"]
        for document in ready:
            self.left.addItem(document.filename, document.id)
            self.right.addItem(document.filename, document.id)
        if current_left:
            index = self.left.findData(current_left)
            if index >= 0:
                self.left.setCurrentIndex(index)
        if current_right:
            index = self.right.findData(current_right)
            if index >= 0:
                self.right.setCurrentIndex(index)
        elif self.right.count() > 1:
            self.right.setCurrentIndex(1)

    def show_result(self, result: CompareResult) -> None:
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Topic", result.left_name or "Document 1", result.right_name or "Document 2"])
        self.summary.setText(result.summary)
        self.status.setText(result.error or "")
        self.table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
            left = row.left
            right = row.right
            if row.left_pages:
                left = f"{left}\n({result.left_name}, p. {', '.join(map(str, row.left_pages))})"
            if row.right_pages:
                right = f"{right}\n({result.right_name}, p. {', '.join(map(str, row.right_pages))})"
            self.table.setItem(row_index, 0, QTableWidgetItem(row.topic))
            self.table.setItem(row_index, 1, QTableWidgetItem(left))
            self.table.setItem(row_index, 2, QTableWidgetItem(right))
        self.table.resizeRowsToContents()

    def set_busy(self, busy: bool) -> None:
        self.run.setEnabled(not busy)
        self.run.setText("Comparing…" if busy else "Compare")

    def _emit(self) -> None:
        left = self.left.currentData()
        right = self.right.currentData()
        if not left or not right:
            self.status.setText("Add two PDFs before comparing.")
            return
        question = self.question.text().strip() or "What changed between these documents?"
        self.compare_requested.emit(str(left), str(right), question)
