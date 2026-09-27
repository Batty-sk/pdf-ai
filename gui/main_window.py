"""Three-pane window: library, conversation, and evidence."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
)

from gui.chat_view import ChatView
from gui.compare_view import CompareView
from gui.document_panel import Sidebar, _pdf_paths
from gui.export_chat import write_pdf, write_text
from gui.page_preview import PagePreviewDialog
from gui.settings_view import SettingsView
from gui.source_panel import SourcePanel
from gui.styles import resolve_palette, stylesheet
from gui.workers import AnswerWorker, CompareWorker, IndexWorker, ProbeWorker, ReindexWorker
from services.container import AppContext
from utils.config import APP_NAME, VERSION
from utils.errors import PdfError
from utils.security import validate_upload


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.current_chat_id = ""
        self._busy = False
        self._worker = None
        self.palette = resolve_palette(ctx.settings.theme)

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)

        self.sidebar = Sidebar()
        self.chat_view = ChatView()
        self.compare_view = CompareView()
        self.settings_view = SettingsView(ctx)
        self.source_panel = SourcePanel()
        self.stack = QStackedWidget()
        for page in (self.chat_view, self.compare_view, self.settings_view):
            self.stack.addWidget(page)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.source_panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 680, 320])
        self._splitter_sizes: list[int] | None = None
        self.setCentralWidget(self.splitter)

        self._connect()
        self._ensure_chat()
        self.apply_theme()
        self.reload_library()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_theme)
        self._shortcuts = [
            QShortcut(QKeySequence(QKeySequence.StandardKey.New), self),
            QShortcut(QKeySequence("Ctrl+,"), self),
        ]
        self._shortcuts[0].activated.connect(self.new_chat)
        self._shortcuts[1].activated.connect(self.show_settings)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def apply_theme(self) -> None:
        self.palette = resolve_palette(self.ctx.settings.theme)
        self.setStyleSheet(stylesheet(self.palette))
        self.sidebar.apply_palette(self.palette)
        color = self.palette.bg
        self.settings_view.scroll.viewport().setStyleSheet(f"background: {color}; border: none;")
        if self.current_chat_id and not self._busy:
            self._load_chat()

    def reload_library(self) -> None:
        documents = self.ctx.db.list_documents()
        self.sidebar.set_chats(self.ctx.db.list_chats(), self.current_chat_id)
        checked: set[str] = set()
        if self.current_chat_id:
            checked = set(self.ctx.db.chat_document_ids(self.current_chat_id))
        self.sidebar.set_documents(documents, checked)
        self.compare_view.set_documents(documents)
        if not self._busy:
            self._load_chat()

    def new_chat(self) -> None:
        if self._busy:
            return
        checked = self.sidebar.checked_document_ids()
        if not checked:
            checked = [doc.id for doc in self.ctx.db.list_documents() if doc.status == "ready"]
        self.current_chat_id = self.ctx.chat.create_chat(checked)
        self.ctx.settings.set("last_chat_id", self.current_chat_id)
        self.stack.setCurrentWidget(self.chat_view)
        self.sidebar.set_nav("")
        self.reload_library()

    def submit_question(self, text: str) -> None:
        text = text.strip()
        if not text or self._busy:
            return
        if not self.current_chat_id:
            self.new_chat()
        self._busy = True
        prior = self.ctx.db.list_messages(self.current_chat_id)
        self.chat_view.show_pending(text, prior, self.palette)
        self.sidebar.set_progress("Reading the relevant pages…", True)
        worker = AnswerWorker(self.ctx.chat, self.current_chat_id, text)
        worker.succeeded.connect(self._finish_turn)
        worker.failed.connect(self._fail_turn)
        self._worker = worker
        worker.start()

    def add_pdfs(self, paths: list[str]) -> None:
        if self._busy:
            self.statusBar().showMessage("Wait for the current task to finish.", 4000)
            return
        jobs: list[tuple[Path, str | None]] = []
        for raw in paths:
            path = Path(raw)
            try:
                validate_upload(path)
            except PdfError as exc:
                QMessageBox.warning(self, "Could not add file", f"{path.name}: {exc}")
                continue
            password = self._password_for(path)
            if password is False:
                continue
            jobs.append((path, password))
        if not jobs:
            return
        self._busy = True
        self.sidebar.set_progress(f"Processing document 1 of {len(jobs)}…", True)
        worker = IndexWorker(self.ctx.documents, jobs)
        worker.progress.connect(lambda message: self.sidebar.set_progress(message, True))
        worker.batch_done.connect(self._on_indexed)
        self._worker = worker
        worker.start()

    def dragEnterEvent(self, event):
        if _pdf_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = _pdf_paths(event)
        if paths:
            self.add_pdfs(paths)
            event.acceptProposedAction()

    def _connect(self) -> None:
        self.sidebar.new_chat.connect(self.new_chat)
        self.sidebar.chat_selected.connect(self._open_chat)
        self.sidebar.rename_chat.connect(self._rename_chat)
        self.sidebar.delete_chat.connect(self._delete_chat)
        self.sidebar.clear_chat.connect(self._clear_chat)
        self.sidebar.add_pdfs.connect(self._pick_pdfs)
        self.sidebar.remove_document.connect(self._remove_document)
        self.sidebar.clear_documents.connect(self._clear_documents)
        self.sidebar.documents_changed.connect(self._set_chat_documents)
        self.sidebar.files_dropped.connect(self.add_pdfs)
        self.sidebar.open_compare.connect(self.show_compare)
        self.sidebar.open_settings.connect(self.show_settings)
        self.sidebar.open_about.connect(self.show_about)
        self.chat_view.composer.submit.connect(self.submit_question)
        self.chat_view.citation_selected.connect(self._show_sources)
        self.chat_view.notice_dismissed.connect(self._dismiss_notice)
        self.chat_view.export_text.connect(self._export_text)
        self.chat_view.export_pdf.connect(self._export_pdf)
        self.chat_view.toggle_evidence.connect(self._toggle_evidence)
        self.source_panel.open_page.connect(self._open_page)
        self.compare_view.back.connect(self._show_chat)
        self.compare_view.compare_requested.connect(self._compare)
        self.settings_view.back.connect(self._show_chat)
        self.settings_view.theme_changed.connect(self.apply_theme)
        self.settings_view.clear_requested.connect(self._clear_documents)
        self.settings_view.reindex_requested.connect(self._reindex)
        self.settings_view.test_requested.connect(self._probe)

    def _ensure_chat(self) -> None:
        chats = self.ctx.db.list_chats()
        last = self.ctx.settings.last_chat_id
        if last and any(chat.id == last for chat in chats):
            self.current_chat_id = last
        elif chats:
            self.current_chat_id = chats[0].id
        else:
            ready = [doc.id for doc in self.ctx.db.list_documents() if doc.status == "ready"]
            self.current_chat_id = self.ctx.chat.create_chat(ready)
        self.ctx.settings.set("last_chat_id", self.current_chat_id)

    def _load_chat(self) -> None:
        chat = self.ctx.db.get_chat(self.current_chat_id) if self.current_chat_id else None
        if chat is None:
            return
        self.chat_view.set_title(chat.title)
        self.chat_view.set_notice_visible(not self.ctx.settings.notice_dismissed)
        self.chat_view.set_messages(self.ctx.db.list_messages(self.current_chat_id), self.palette)

    def _open_chat(self, chat_id: str) -> None:
        if self._busy:
            return
        self.current_chat_id = chat_id
        self.ctx.settings.set("last_chat_id", chat_id)
        self._show_chat()

    def _show_chat(self) -> None:
        self._set_sources_visible(True)
        self.stack.setCurrentWidget(self.chat_view)
        self.sidebar.set_nav("")
        if not self._busy:
            self._load_chat()

    def show_compare(self) -> None:
        self.compare_view.set_documents(self.ctx.db.list_documents())
        self.stack.setCurrentWidget(self.compare_view)
        self.sidebar.set_nav("compare")

    def show_settings(self) -> None:
        self.settings_view.load()
        self._set_sources_visible(False)
        self.stack.setCurrentWidget(self.settings_view)
        self.sidebar.set_nav("settings")

    def _set_sources_visible(self, visible: bool) -> None:
        if visible == self.source_panel.isVisible():
            return
        if visible:
            self.source_panel.show()
            if self._splitter_sizes:
                self.splitter.setSizes(self._splitter_sizes)
            return
        self._splitter_sizes = self.splitter.sizes()
        self.source_panel.hide()

    def show_about(self) -> None:
        self.sidebar.set_nav("about")
        QMessageBox.about(
            self,
            "About PDF AI Assistant",
            (
                f"{APP_NAME} {VERSION}\n\n"
                "Ask questions about your PDFs. Passages are embedded on this computer. "
                "An answer is written only from the passages that match the question, and each "
                "answer keeps the file name and page it came from.\n\n"
                "When you ask a question, the question and those short excerpts are sent to the "
                "AI service in Settings. The PDF files stay on this computer.\n\n"
                "If the documents do not contain the answer, the assistant says so instead of guessing."
            ),
        )
        self.sidebar.set_nav("")

    def _show_sources(self, sources, chunk_id: str, note: str) -> None:
        self.source_panel.show_sources(list(sources or []), chunk_id, note, self.palette)

    def _toggle_evidence(self) -> None:
        visible = not self.source_panel.isVisible()
        self.source_panel.setVisible(visible)
        self.chat_view.set_evidence_open(visible)

    def _open_page(self, source) -> None:
        PagePreviewDialog(source, self).exec()

    def _dismiss_notice(self) -> None:
        self.ctx.settings.set("notice_dismissed", "1")
        self.chat_view.set_notice_visible(False)

    def _set_chat_documents(self, document_ids: list) -> None:
        if self.current_chat_id:
            self.ctx.chat.set_documents(self.current_chat_id, list(document_ids))

    def _pick_pdfs(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF files (*.pdf)")
        if paths:
            self.add_pdfs(paths)

    def _password_for(self, path: Path):
        import pymupdf

        try:
            document = pymupdf.open(path)
        except Exception:
            return None
        try:
            if not document.is_encrypted:
                return None
            while True:
                password, ok = QInputDialog.getText(
                    self,
                    "Password required",
                    f"{path.name} is protected. Enter the password.",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return False
                if document.authenticate(password):
                    return password
                QMessageBox.warning(self, "Password", "That password did not open the PDF.")
        finally:
            document.close()

    def _on_indexed(self, results) -> None:
        self._busy = False
        self.sidebar.set_progress("", False)
        added = []
        notes = []
        for result in results:
            if result.document and result.document.status == "ready":
                added.append(result.document.id)
            if result.error:
                notes.append(result.error)
            elif result.warning and result.document:
                notes.append(f"{result.document.filename}: {result.warning}")
        if self.current_chat_id and added:
            current = set(self.ctx.db.chat_document_ids(self.current_chat_id))
            current.update(added)
            self.ctx.chat.set_documents(self.current_chat_id, list(current))
        self.reload_library()
        if notes:
            QMessageBox.information(self, "Documents", "\n".join(notes))
        elif added:
            self.statusBar().showMessage(f"Added {len(added)} PDF(s).", 5000)

    def _remove_document(self) -> None:
        document_id = self.sidebar.selected_document_id()
        if not document_id:
            QMessageBox.information(self, "Remove document", "Select a document first.")
            return
        document = self.ctx.db.get_document(document_id)
        name = document.filename if document else "this document"
        answer = QMessageBox.question(self, "Remove document", f"Remove {name} from the library?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.documents.remove(document_id)
        self.reload_library()

    def _clear_documents(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear indexed documents",
            "Remove all PDFs and their search index? Chat history is kept, but those chats will have no documents.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.documents.clear_all()
        self.reload_library()
        self.statusBar().showMessage("Indexed documents cleared.", 5000)

    def _rename_chat(self, chat_id: str) -> None:
        chat = self.ctx.db.get_chat(chat_id)
        current = chat.title if chat else ""
        title, ok = QInputDialog.getText(self, "Rename chat", "Chat name", text=current)
        if ok:
            self.ctx.chat.rename(chat_id, title)
            self.reload_library()

    def _delete_chat(self, chat_id: str) -> None:
        answer = QMessageBox.question(self, "Delete chat", "Delete this chat and its messages?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.chat.delete(chat_id)
        if chat_id == self.current_chat_id:
            self.current_chat_id = ""
            self._ensure_chat()
        self.reload_library()

    def _clear_chat(self, chat_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Clear conversation",
            "Remove every message in this chat? The documents stay attached.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.chat.clear(chat_id)
        self.reload_library()

    def _export_text(self) -> None:
        if not self.current_chat_id:
            return
        path, _selected = QFileDialog.getSaveFileName(self, "Export chat", "conversation.txt", "Text (*.txt)")
        if not path:
            return
        write_text(path, self.ctx.chat.export_text(self.current_chat_id))
        self.statusBar().showMessage("Conversation exported.", 4000)

    def _export_pdf(self) -> None:
        if not self.current_chat_id:
            return
        path, _selected = QFileDialog.getSaveFileName(self, "Export chat", "conversation.pdf", "PDF (*.pdf)")
        if not path:
            return
        chat = self.ctx.db.get_chat(self.current_chat_id)
        title = chat.title if chat else "Chat"
        write_pdf(path, title, self.ctx.db.list_messages(self.current_chat_id))
        self.statusBar().showMessage("Conversation exported.", 4000)

    def _compare(self, left_id: str, right_id: str, question: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.compare_view.set_busy(True)
        worker = CompareWorker(self.ctx.compare, left_id, right_id, question)
        worker.succeeded.connect(self._on_compare)
        worker.failed.connect(self._fail_compare)
        self._worker = worker
        worker.start()

    def _on_compare(self, result) -> None:
        self._busy = False
        self.compare_view.set_busy(False)
        self.compare_view.show_result(result)

    def _fail_compare(self, message: str) -> None:
        self._busy = False
        self.compare_view.set_busy(False)
        self.compare_view.status.setText(message)

    def _reindex(self) -> None:
        if self._busy:
            return
        answer = QMessageBox.question(
            self,
            "Reindex documents",
            "Rebuild the search index with the current chunk settings?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self.sidebar.set_progress("Reindexing documents…", True)
        worker = ReindexWorker(self.ctx.documents)
        worker.progress.connect(lambda message: self.sidebar.set_progress(message, True))
        worker.batch_done.connect(self._on_indexed)
        self._worker = worker
        worker.start()

    def _probe(self) -> None:
        self.settings_view.set_status("Contacting the AI service…")
        worker = ProbeWorker(self.ctx.settings, self.ctx.data_dir)
        worker.succeeded.connect(lambda: self.settings_view.set_status("Connection succeeded."))
        worker.failed.connect(self.settings_view.set_status)
        self._worker = worker
        worker.start()

    def _finish_turn(self, _result=None) -> None:
        self._busy = False
        self.chat_view.set_busy(False)
        self.sidebar.set_progress("", False)
        self.reload_library()

    def _fail_turn(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        self._finish_turn()

    def _system_theme(self, _scheme) -> None:
        if self.ctx.settings.theme == "system":
            self.apply_theme()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
