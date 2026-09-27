"""Split each page into overlapping passages without crossing pages.

Page-local chunks keep a citation pointed at the page the words actually
came from. Overlap stays inside that page so a sentence cut by the size
limit still appears in the next passage.
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.pdf_loader import PageText


@dataclass
class ChunkDraft:
    page: int
    chunk_index: int
    text: str


def chunk_pages(pages: list[PageText], size: int, overlap: int) -> list[ChunkDraft]:
    size = max(200, size)
    overlap = max(0, min(overlap, size // 2))
    drafts: list[ChunkDraft] = []
    for page in pages:
        text = page.text.strip()
        if len(text) < 15:
            continue
        pieces = _split(text, size, overlap)
        for index, piece in enumerate(pieces):
            drafts.append(ChunkDraft(page=page.number, chunk_index=index, text=piece))
    return drafts


def _split(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("? "), window.rfind("! "))
            if cut >= int(size * 0.4):
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return pieces
