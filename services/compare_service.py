"""Compare two PDFs using passages from each document."""

from __future__ import annotations

import json
import logging

from database.database import Database
from database.models import CompareResult, CompareRow, Source
from rag.rag_pipeline import NOT_FOUND, _load_json
from rag.rag_pipeline import RagPipeline
from utils.config import SettingsStore
from utils.errors import LlmError

logger = logging.getLogger(__name__)

COMPARE_PROMPT = """You compare two PDF documents using only the passages given to you.

Return JSON only:
{"summary": "...", "rows": [{"topic": "...", "document_1": "...", "document_2": "...", "doc1_pages": [1], "doc2_pages": [2]}]}

Rules:
- Every statement must come from the passages.
- document_1 is the first document and document_2 is the second.
- If a document does not mention the topic, write "Not stated in the retrieved passages".
- Do not invent numbers, dates, or policy names.
- Include at most 8 rows, and only topics that the passages support.
"""


class CompareService:
    def __init__(self, db: Database, pipeline: RagPipeline, settings: SettingsStore):
        self.db = db
        self.pipeline = pipeline
        self.settings = settings

    def compare(self, left_id: str, right_id: str, question: str) -> CompareResult:
        left = self.db.get_document(left_id)
        right = self.db.get_document(right_id)
        if left is None or right is None:
            return CompareResult("", [], "", "", [], "Choose two indexed PDFs.")
        if left.id == right.id:
            return CompareResult("", [], left.filename, right.filename, [], "Choose two different PDFs.")

        if self.pipeline.prepare:
            self.pipeline.prepare()
        question = question.strip() or "What changed between these documents?"
        top_k = self.settings.top_k
        left_chunks = self._passages(question, left.id, top_k)
        right_chunks = self._passages(question, right.id, top_k)
        if not left_chunks and not right_chunks:
            return CompareResult(
                NOT_FOUND,
                [],
                left.filename,
                right.filename,
                [],
                NOT_FOUND,
            )
        try:
            raw = self.pipeline.provider_factory().complete(
                [
                    {"role": "system", "content": COMPARE_PROMPT},
                    {
                        "role": "user",
                        "content": _user_prompt(left.filename, right.filename, question, left_chunks, right_chunks),
                    },
                ]
            )
        except LlmError as exc:
            return CompareResult("", [], left.filename, right.filename, left_chunks + right_chunks, str(exc))

        try:
            payload = _load_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.info("Comparison reply was not valid JSON")
            return CompareResult(
                "",
                [],
                left.filename,
                right.filename,
                left_chunks + right_chunks,
                "The comparison could not be read. Try again.",
            )
        rows = []
        for item in (payload.get("rows") or [])[:8]:
            if not isinstance(item, dict):
                continue
            rows.append(
                CompareRow(
                    topic=str(item.get("topic") or "Topic"),
                    left=str(item.get("document_1") or "Not stated in the retrieved passages"),
                    right=str(item.get("document_2") or "Not stated in the retrieved passages"),
                    left_pages=_pages(item.get("doc1_pages")),
                    right_pages=_pages(item.get("doc2_pages")),
                )
            )
        summary = str(payload.get("summary") or "").strip()
        if not rows and not summary:
            return CompareResult(
                "",
                [],
                left.filename,
                right.filename,
                left_chunks + right_chunks,
                NOT_FOUND,
            )
        return CompareResult(summary, rows, left.filename, right.filename, left_chunks + right_chunks, None)

    def _passages(self, question: str, document_id: str, top_k: int) -> list[Source]:
        semantic = self.pipeline.retriever.search(
            question,
            [document_id],
            top_k=top_k,
            hybrid=self.settings.hybrid_search,
        )
        sampled = _sample(self.db, document_id, limit=6)
        merged: dict[str, Source] = {item.chunk_id: item for item in semantic}
        for item in sampled:
            merged.setdefault(item.chunk_id, item)
        return list(merged.values())[:10]


def _sample(db: Database, document_id: str, limit: int) -> list[Source]:
    chunks = db.list_chunks_for_document(document_id)
    if not chunks:
        return []
    if len(chunks) <= limit:
        chosen = chunks
    else:
        step = len(chunks) / limit
        chosen = [chunks[int(index * step)] for index in range(limit)]
    return [
        Source(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=chunk.filename,
            stored_path=chunk.stored_path,
            page=chunk.page,
            text=chunk.text,
            score=0.0,
            semantic_score=0.0,
        )
        for chunk in chosen
    ]


def _user_prompt(left: str, right: str, question: str, left_chunks: list[Source], right_chunks: list[Source]) -> str:
    return (
        f"Document 1: {left}\n{_format(left_chunks)}\n\n"
        f"Document 2: {right}\n{_format(right_chunks)}\n\n"
        f"Question: {question}"
    )


def _format(chunks: list[Source]) -> str:
    if not chunks:
        return "(no passages retrieved)"
    blocks = [f"[{chunk.chunk_id}] page {chunk.page}\n{chunk.text}" for chunk in chunks]
    return "\n\n".join(blocks)


def _pages(value) -> list[int]:
    if not isinstance(value, list):
        return []
    pages = []
    for item in value:
        try:
            pages.append(int(item))
        except (TypeError, ValueError):
            continue
    return pages
