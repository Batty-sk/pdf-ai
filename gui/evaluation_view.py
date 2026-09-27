"""Labelled questions and the metrics used to study the assistant."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.models import EvalCase, EvalSummary

try:
    from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis

    HAS_CHARTS = True
except ImportError:
    HAS_CHARTS = False


class EvaluationView(QWidget):
    back = Signal()
    case_added = Signal(str, str, str, object, bool)
    case_deleted = Signal(str)
    run_requested = Signal()
    imported = Signal(str)
    export_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("EvalRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._case_ids: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Check answers")
        title.setObjectName("PaneTitle")
        back = QPushButton("Back to chat")
        back.setObjectName("GhostButton")
        back.clicked.connect(self.back.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(back)
        root.addLayout(header)

        intro = QLabel(
            "Add questions with the answer and page you expect. "
            "Answer accuracy is token overlap with the expected answer, not a second human rating. "
            "Unsupported questions are scored only on whether the assistant refuses."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        root.addWidget(intro)

        form = QFormLayout()
        self.question = QLineEdit()
        self.expected = QLineEdit()
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("Policy.pdf")
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("Any page")
        self.unsupported = QCheckBox("This question should be unanswerable from the PDFs")
        form.addRow("Question", self.question)
        form.addRow("Expected answer", self.expected)
        form.addRow("Expected file", self.filename)
        form.addRow("Expected page", self.page)
        form.addRow("", self.unsupported)
        root.addLayout(form)

        actions = QHBoxLayout()
        add = QPushButton("Add question")
        add.setObjectName("PrimaryButton")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove selected")
        remove.setObjectName("GhostButton")
        remove.clicked.connect(self._remove)
        import_btn = QPushButton("Import JSON")
        export_btn = QPushButton("Export JSON")
        import_btn.setObjectName("GhostButton")
        export_btn.setObjectName("GhostButton")
        import_btn.clicked.connect(self._import)
        export_btn.clicked.connect(self._export)
        self.run_button = QPushButton("Run evaluation")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.run_requested.emit)
        for button in (add, remove, import_btn, export_btn, self.run_button):
            actions.addWidget(button)
        root.addLayout(actions)

        self.cases = QTableWidget(0, 4)
        self.cases.setHorizontalHeaderLabels(["Question", "Expected answer", "Source", "Unsupported"])
        self.cases.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cases.verticalHeader().setVisible(False)
        self.cases.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cases.setMaximumHeight(180)
        root.addWidget(self.cases)

        self.metrics = QLabel("No run yet.")
        self.metrics.setWordWrap(True)
        root.addWidget(self.metrics)

        self.chart_host = QVBoxLayout()
        root.addLayout(self.chart_host)
        self._chart_view = None

        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(
            ["Question", "Retrieval", "Citation", "Answer overlap", "Unsupported", "Latency"]
        )
        self.results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.verticalHeader().setVisible(False)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.results, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def set_cases(self, cases: list[EvalCase]) -> None:
        self._case_ids = [case.id for case in cases]
        self.cases.setRowCount(len(cases))
        for index, case in enumerate(cases):
            source = case.expected_filename
            if case.expected_page:
                source = f"{source} p.{case.expected_page}"
            self.cases.setItem(index, 0, QTableWidgetItem(case.question))
            self.cases.setItem(index, 1, QTableWidgetItem(case.expected_answer))
            self.cases.setItem(index, 2, QTableWidgetItem(source))
            self.cases.setItem(index, 3, QTableWidgetItem("Yes" if case.expect_unsupported else ""))

    def show_summary(self, summary: EvalSummary) -> None:
        self.metrics.setText(
            "  ·  ".join(
                [
                    f"Retrieval {_pct(summary.retrieval_accuracy)}",
                    f"Citation {_pct(summary.citation_accuracy)}",
                    f"Answer overlap {_pct(summary.answer_accuracy)}",
                    f"Unsupported detection {_pct(summary.unsupported_detection)}",
                    f"Mean latency {summary.mean_latency_ms:.0f} ms",
                ]
            )
        )
        self.results.setRowCount(len(summary.results))
        for index, item in enumerate(summary.results):
            values = [
                item.question,
                _flag(item.retrieval_hit),
                _flag(item.citation_hit),
                "—" if item.answer_score is None else f"{item.answer_score * 100:.0f}%",
                _flag(item.unsupported_correct),
                f"{item.latency_ms} ms",
            ]
            for column, value in enumerate(values):
                self.results.setItem(index, column, QTableWidgetItem(value))
        self._draw_chart(summary)

    def set_busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy)
        self.run_button.setText("Running…" if busy else "Run evaluation")

    def _add(self) -> None:
        question = self.question.text().strip()
        if not question:
            self.status.setText("Enter a question first.")
            return
        page = self.page.value() or None
        self.case_added.emit(
            question,
            self.expected.text().strip(),
            self.filename.text().strip(),
            page,
            self.unsupported.isChecked(),
        )
        self.question.clear()
        self.expected.clear()
        self.status.setText("Question added.")

    def _remove(self) -> None:
        row = self.cases.currentRow()
        if row < 0 or row >= len(self._case_ids):
            self.status.setText("Select a question to remove.")
            return
        self.case_deleted.emit(self._case_ids[row])

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import questions", "", "JSON (*.json)")
        if path:
            self.imported.emit(path)

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export questions", "evaluation.json", "JSON (*.json)")
        if path:
            self.export_requested.emit(path)

    def _draw_chart(self, summary: EvalSummary) -> None:
        if not HAS_CHARTS:
            return
        if self._chart_view is not None:
            self.chart_host.removeWidget(self._chart_view)
            self._chart_view.deleteLater()
        series = QBarSeries()
        bars = QBarSet("Score")
        labels = []
        for label, value in (
            ("Retrieval", summary.retrieval_accuracy),
            ("Citation", summary.citation_accuracy),
            ("Answer", summary.answer_accuracy),
            ("Unsupported", summary.unsupported_detection),
        ):
            if value is None:
                continue
            labels.append(label)
            bars.append(round(value * 100, 1))
        if not labels:
            self._chart_view = None
            return
        series.append(bars)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Latest run")
        chart.legend().setVisible(False)
        chart.setBackgroundVisible(False)
        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setTitleText("%")
        chart.addAxis(axis_x, Qt_align_bottom())
        chart.addAxis(axis_y, Qt_align_left())
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        self._chart_view = QChartView(chart)
        self._chart_view.setMinimumHeight(220)
        self.chart_host.addWidget(self._chart_view)


def Qt_align_bottom():
    from PySide6.QtCore import Qt

    return Qt.AlignmentFlag.AlignBottom


def Qt_align_left():
    from PySide6.QtCore import Qt

    return Qt.AlignmentFlag.AlignLeft


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


def _flag(value: bool | None) -> str:
    if value is None:
        return "—"
    return "Yes" if value else "No"


def read_import_error(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "That file is not valid JSON."
    return str(exc)
