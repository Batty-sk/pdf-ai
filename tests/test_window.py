"""Construct the window and run upload → question → citation → follow-up."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from gui.export_chat import write_pdf
from gui.main_window import MainWindow
from gui.styles import load_fonts
from services.container import build_context
from tests.fakes import ScriptedProvider
from tests.pdfutil import write_text_pdf


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    load_fonts()
    return app


def _wait(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_chat_flow_shows_answer_and_page(qapp, tmp_path):
    provider = ScriptedProvider()
    ctx = build_context(
        tmp_path / "data",
        embedder=__import__("tests.fakes", fromlist=["HashEmbedder"]).HashEmbedder(),
        provider_factory=lambda: provider,
    )
    ctx.settings.set("similarity_threshold", "0.15")
    window = MainWindow(ctx)
    window.show()
    qapp.processEvents()

    pdf = tmp_path / "Employee_Policy.pdf"
    write_text_pdf(pdf, ["Employees are entitled to 20 days of annual leave."])
    result = ctx.documents.index_file(pdf, None, lambda _message: None, display_name="Employee_Policy.pdf")
    assert result.document is not None
    ctx.chat.set_documents(window.current_chat_id, [result.document.id])
    window.reload_library()
    qapp.processEvents()

    window.show_settings()
    window.show_compare()
    window._show_chat()
    qapp.processEvents()

    window.submit_question("How many days of annual leave are employees entitled to?")
    assert _wait(qapp, lambda: not window.is_busy)
    transcript = window.chat_view.transcript()
    assert "20 days" in transcript
    evidence = window.source_panel.evidence_text()
    assert "Employee_Policy.pdf" in evidence
    assert "Page 1" in evidence

    window.submit_question("What about that policy?")
    assert _wait(qapp, lambda: not window.is_busy)
    assert "20 days" in window.chat_view.transcript()

    export_path = tmp_path / "chat.pdf"
    chat = ctx.db.get_chat(window.current_chat_id)
    write_pdf(str(export_path), chat.title, ctx.db.list_messages(window.current_chat_id))
    assert export_path.stat().st_size > 100

    shot = tmp_path / "window.png"
    window.grab().save(str(shot))
    assert shot.exists() and shot.stat().st_size > 1000
    window.close()
