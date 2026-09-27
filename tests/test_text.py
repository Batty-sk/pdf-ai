from rag.chunker import chunk_pages
from rag.pdf_loader import PageText
from rag.text_cleaner import clean_text


def test_cleaner_joins_hyphenation_and_blank_lines():
    raw = "employ-\nees   receive\n\n\nleave"
    assert clean_text(raw) == "employees receive\n\nleave"


def test_chunks_stay_on_their_page_and_overlap():
    sentence = "Employees are entitled to twenty days of annual leave each year."
    text = " ".join(sentence for _ in range(40))
    chunks = chunk_pages([PageText(4, text)], size=220, overlap=40)
    assert len(chunks) > 1
    assert {chunk.page for chunk in chunks} == {4}
    assert chunks[0].text[-25:] in text
    shared = False
    for earlier, later in zip(chunks, chunks[1:]):
        if earlier.text[-20:] in later.text or later.text[:20] in earlier.text:
            shared = True
    assert shared
