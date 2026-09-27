"""Upload, retrieve, answer, cite, and follow up without an external API."""

from pathlib import Path

from rag.rag_pipeline import NOT_FOUND, parse_model_json
from services.container import build_context
from tests.fakes import BrokenProvider, CompareProvider, HashEmbedder, ScriptedProvider
from tests.pdfutil import write_text_pdf


def _context(tmp_path: Path, provider):
    embedder = HashEmbedder()
    ctx = build_context(tmp_path, embedder=embedder, provider_factory=lambda: provider)
    ctx.settings.set("similarity_threshold", "0.15")
    return ctx, embedder


def _index(ctx, path: Path, name: str | None = None):
    result = ctx.documents.index_file(path, None, lambda _message: None, display_name=name)
    assert result.error is None, result.error
    assert result.document is not None
    return result.document


def test_answer_cites_the_matching_pdf_and_follow_up_reuses_context(tmp_path: Path):
    policy = tmp_path / "Employee_Policy.pdf"
    other = tmp_path / "Holiday_Calendar.pdf"
    write_text_pdf(policy, ["Employees are entitled to 20 days of annual leave."])
    write_text_pdf(other, ["The office closes on public holidays."])

    provider = ScriptedProvider()
    ctx, embedder = _context(tmp_path / "data", provider)
    leave = _index(ctx, policy, "Employee_Policy.pdf")
    _index(ctx, other, "Holiday_Calendar.pdf")
    chat_id = ctx.chat.create_chat([leave.id])

    first = ctx.chat.ask(chat_id, "How many days of annual leave are employees entitled to?")
    assert first.refused is False
    assert "20 days" in first.answer
    assert first.sources
    assert first.sources[0].filename == "Employee_Policy.pdf"
    assert first.sources[0].page == 1
    assert provider.calls

    second = ctx.chat.ask(chat_id, "What about that policy?")
    assert "How many days" in embedder.queries[-1]
    assert "What about that policy?" in embedder.queries[-1]
    assert second.sources
    assert second.sources[0].filename == "Employee_Policy.pdf"

    exported = ctx.chat.export_text(chat_id)
    assert "Employee_Policy.pdf, page 1" in exported
    messages = ctx.db.list_messages(chat_id)
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]
    assert ctx.db.get_chat(chat_id).title.startswith("How many days")


def test_low_similarity_does_not_call_the_model(tmp_path: Path):
    path = tmp_path / "Policy.pdf"
    write_text_pdf(path, ["Employees are entitled to 20 days of annual leave."])
    provider = ScriptedProvider()
    ctx, _embedder = _context(tmp_path / "data", provider)
    ctx.settings.set("similarity_threshold", "0.99")
    document = _index(ctx, path, "Policy.pdf")
    answer = ctx.pipeline.answer("zzzz unrelated telescope", [], [document.id])
    assert answer.refused is True
    assert answer.answer == NOT_FOUND
    assert provider.calls == []


def test_unreadable_model_output_is_refused(tmp_path: Path):
    path = tmp_path / "Policy.pdf"
    write_text_pdf(path, ["Employees are entitled to 20 days of annual leave."])
    ctx, _embedder = _context(tmp_path / "data", BrokenProvider())
    document = _index(ctx, path, "Policy.pdf")
    answer = ctx.pipeline.answer("How many days of annual leave are employees entitled to?", [], [document.id])
    assert answer.grounded is False
    assert answer.answer == NOT_FOUND


def test_parse_rejects_non_json():
    answer, _cited, grounded = parse_model_json("sure, twenty days", [])
    assert grounded is False
    assert answer == NOT_FOUND


def test_compare_names_each_document(tmp_path: Path):
    first = tmp_path / "Leave_A.pdf"
    second = tmp_path / "Leave_B.pdf"
    write_text_pdf(first, ["Annual leave is 20 days."])
    write_text_pdf(second, ["Annual leave is 24 days."])
    ctx, _embedder = _context(tmp_path / "data", CompareProvider())
    left = _index(ctx, first, "Leave_A.pdf")
    right = _index(ctx, second, "Leave_B.pdf")
    result = ctx.compare.compare(left.id, right.id, "What changed between these documents?")
    assert result.error is None
    assert result.rows[0].topic == "Annual leave"
    assert result.rows[0].left == "20 days"
    assert result.rows[0].right == "24 days"
    assert result.left_name == "Leave_A.pdf"
    assert result.right_name == "Leave_B.pdf"


def test_remove_document_drops_it_from_search(tmp_path: Path):
    path = tmp_path / "Policy.pdf"
    write_text_pdf(path, ["Employees are entitled to 20 days of annual leave."])
    ctx, _embedder = _context(tmp_path / "data", ScriptedProvider())
    document = _index(ctx, path, "Policy.pdf")
    ctx.documents.remove(document.id)
    assert ctx.db.list_documents() == []
    assert ctx.db.all_faiss_ids() == []
    assert ctx.pipeline.retriever.search("annual leave", [document.id], top_k=5, hybrid=True) == []
