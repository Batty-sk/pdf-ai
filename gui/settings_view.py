"""Model, retrieval, appearance, and storage preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from services.container import AppContext
from utils.security import stored_api_key


class SettingSlider(QWidget):
    """A named slider with the current value and a one-line explanation."""

    def __init__(self, title: str, description: str, minimum: int, maximum: int, step: int, format_value):
        super().__init__()
        self._format = format_value
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 12, 2, 14)
        root.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(16)
        name = QLabel(title)
        name.setStyleSheet("font-weight: 600;")
        self.value_label = QLabel()
        self.value_label.setObjectName("Muted")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(name, 1)
        header.addWidget(self.value_label, 0)
        root.addLayout(header)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(max(step, (maximum - minimum) // 10 or step))
        self.slider.setMinimumHeight(32)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.slider.valueChanged.connect(self._show_value)
        root.addWidget(self.slider)
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setObjectName("Muted")
        root.addWidget(detail)
        self._show_value(self.slider.value())

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(value))

    def setMaximum(self, maximum: int) -> None:
        self.slider.setMaximum(maximum)

    def _show_value(self, value: int) -> None:
        self.value_label.setText(self._format(value))


class SettingsView(QWidget):
    back = Signal()
    saved = Signal()
    theme_changed = Signal()
    clear_requested = Signal()
    reindex_requested = Signal()
    test_requested = Signal()

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("SettingsRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 16)
        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("PaneTitle")
        done = QPushButton("Done")
        done.setObjectName("PrimaryButton")
        done.clicked.connect(self._save_and_close)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(done)
        outer.addLayout(header)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll = scroll
        host = QWidget()
        host.setObjectName("SettingsForm")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form_root = QVBoxLayout(host)
        form_root.setSpacing(12)

        ai = QGroupBox("Model")
        ai_layout = QVBoxLayout(ai)
        ai_layout.setContentsMargins(16, 22, 16, 14)
        ai_layout.setSpacing(8)
        ai_form = QFormLayout()
        ai_form.setSpacing(10)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Leave blank to use the built-in Gemini key")
        self.api_key.setToolTip("A key you type is stored in the system keychain and replaces the built-in key.")
        self.show_key = QCheckBox("Show API key")
        self.show_key.toggled.connect(
            lambda checked: self.api_key.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        self.model = QLineEdit()
        self.model.setToolTip("Any model name your endpoint accepts.")
        self.base_url = QLineEdit()
        self.base_url.setToolTip("https://api.openai.com/v1, or a compatible server such as LM Studio.")
        self.temperature = SettingSlider(
            "How much the wording can vary",
            "Lower keeps the reply close to the pages. Higher lets the sentences change more.",
            0,
            20,
            1,
            lambda value: f"{value / 10:.1f}",
        )
        self.max_tokens = SettingSlider(
            "Longest reply",
            "The most the answer is allowed to write. A short limit can stop it mid-sentence.",
            64,
            8000,
            50,
            _reply_length,
        )
        ai_form.addRow("API key", self.api_key)
        ai_form.addRow("", self.show_key)
        ai_form.addRow("Model", self.model)
        ai_form.addRow("API endpoint", self.base_url)
        ai_layout.addLayout(ai_form)
        ai_layout.addWidget(self.temperature)
        ai_layout.addWidget(self.max_tokens)
        hint = QLabel(
            "Document files stay on this computer. A question sends the question and the "
            "matching excerpts to this endpoint. Local servers often accept any non-empty key, such as local."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        test = QPushButton("Test connection")
        test.setObjectName("GhostButton")
        test.setToolTip("Send a tiny request to check the key, model, and endpoint")
        test.clicked.connect(self._save_then_test)
        ai_layout.addWidget(hint)
        ai_layout.addWidget(test)

        rag = QGroupBox("Finding a page")
        rag_layout = QVBoxLayout(rag)
        rag_layout.setContentsMargins(16, 22, 16, 14)
        rag_layout.setSpacing(2)
        self.chunk_size = SettingSlider(
            "Passage length",
            "How much of the page stays together. Longer passages give an answer more surrounding context.",
            200,
            4000,
            50,
            lambda value: f"{value} characters",
        )
        self.chunk_overlap = SettingSlider(
            "Repeated edges",
            "Repeats the end of one passage at the start of the next, so a sentence is not cut in half.",
            0,
            1000,
            10,
            lambda value: f"{value} characters",
        )
        self.top_k = SettingSlider(
            "Passages per question",
            "How many excerpts are sent with a question. More can help a broad question, and can also pull in extra pages.",
            1,
            20,
            1,
            lambda value: "1 passage" if value == 1 else f"{value} passages",
        )
        self.threshold = SettingSlider(
            "How close a match must be",
            "A higher bar skips the answer when the pages are not really about the question.",
            0,
            100,
            5,
            lambda value: f"{value}%",
        )
        self.chunk_size.slider.valueChanged.connect(self._limit_overlap)
        self.hybrid = QCheckBox("Also look for the same words")
        self.hybrid.setToolTip("Finds names, dates, and phrases copied from the PDF, not only similar meaning.")
        hybrid_note = QLabel("Useful when the question uses a name, date, or phrase from the document.")
        hybrid_note.setWordWrap(True)
        hybrid_note.setObjectName("Muted")
        note = QLabel("Passage length and repeated edges apply the next time you add a PDF or reindex.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        for widget in (
            self.chunk_size,
            self.chunk_overlap,
            self.top_k,
            self.threshold,
            self.hybrid,
            hybrid_note,
            note,
        ):
            rag_layout.addWidget(widget)

        appearance = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance)
        self.theme = QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.currentTextChanged.connect(self._on_theme)
        appearance_form.addRow("Theme", self.theme)

        storage = QGroupBox("Storage")
        storage_layout = QVBoxLayout(storage)
        self.path_label = QLabel(str(ctx.data_dir))
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        open_folder = QPushButton("Open folder")
        open_folder.setObjectName("GhostButton")
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.data_dir)))
        )
        reindex = QPushButton("Reindex all documents")
        reindex.setObjectName("GhostButton")
        reindex.setToolTip("Rebuild the search index with the passage settings above")
        reindex.clicked.connect(self._save_then_reindex)
        clear = QPushButton("Clear indexed documents")
        clear.setObjectName("DangerButton")
        clear.setToolTip("Remove every PDF and its embeddings. Chats are kept.")
        clear.clicked.connect(self.clear_requested.emit)
        storage_layout.addWidget(QLabel("Vector index, chats, and PDF copies"))
        storage_layout.addWidget(self.path_label)
        storage_layout.addWidget(open_folder)
        storage_layout.addWidget(reindex)
        storage_layout.addWidget(clear)

        for box in (ai, rag, appearance, storage):
            form_root.addWidget(box)
        form_root.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self.load()

    def load(self) -> None:
        settings = self.ctx.settings
        self.api_key.setText(stored_api_key(self.ctx.data_dir))
        self.model.setText(settings.model)
        self.base_url.setText(settings.base_url)
        self.temperature.setValue(round(settings.temperature * 10))
        self.max_tokens.setValue(settings.max_tokens)
        self.chunk_size.setValue(settings.chunk_size)
        self._limit_overlap()
        self.chunk_overlap.setValue(settings.chunk_overlap)
        self.top_k.setValue(settings.top_k)
        self.threshold.setValue(round(settings.similarity_threshold * 100))
        self.hybrid.setChecked(settings.hybrid_search)
        theme = {"system": "System", "light": "Light", "dark": "Dark"}.get(settings.theme, "System")
        self.theme.blockSignals(True)
        self.theme.setCurrentText(theme)
        self.theme.blockSignals(False)
        self.path_label.setText(str(self.ctx.data_dir))

    def save(self) -> bool:
        url = self.base_url.text().strip()
        if not url.startswith(("http://", "https://")):
            self.status.setText("The API endpoint must start with http:// or https://.")
            return False
        if self.chunk_overlap.value() >= self.chunk_size.value():
            self.status.setText("Repeated edges must be shorter than the passage length.")
            return False
        settings = self.ctx.settings
        settings.set("model", self.model.text().strip() or "gpt-4o-mini")
        settings.set("base_url", url.rstrip("/"))
        settings.set("temperature", f"{self.temperature.value() / 10:.1f}")
        settings.set("max_tokens", str(self.max_tokens.value()))
        settings.set("chunk_size", str(self.chunk_size.value()))
        settings.set("chunk_overlap", str(self.chunk_overlap.value()))
        settings.set("top_k", str(self.top_k.value()))
        settings.set("similarity_threshold", f"{self.threshold.value() / 100:.2f}")
        settings.set("hybrid_search", "1" if self.hybrid.isChecked() else "0")
        from utils.security import set_api_key

        set_api_key(self.ctx.data_dir, self.api_key.text())
        self.status.setText("Settings saved.")
        self.saved.emit()
        return True

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _save_and_close(self) -> None:
        if self.save():
            self.back.emit()

    def _save_then_test(self) -> None:
        if self.save():
            self.test_requested.emit()

    def _save_then_reindex(self) -> None:
        if self.save():
            self.reindex_requested.emit()

    def _limit_overlap(self) -> None:
        cap = max(0, self.chunk_size.value() // 2)
        self.chunk_overlap.setMaximum(min(1000, cap))

    def _on_theme(self, text: str) -> None:
        self.ctx.settings.set("theme", text.lower())
        self.theme_changed.emit()


def _reply_length(value: int) -> str:
    words = max(1, round(value * 0.75))
    return f"about {words:,} words"
