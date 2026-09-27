"""Grounded question answering.

The model is called only after a passage clears the similarity threshold.
If it does not, or if its reply is not valid JSON tied to those passages,
the user sees a fixed not-found sentence rather than an invented answer.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from database.database import Database
from database.models import Message, RagAnswer, Source
from rag.embeddings import EmbeddingModel
from rag.retriever import Retriever
from rag.vector_store import VectorStore
from utils.config import SettingsStore

logger = logging.getLogger(__name__)

NOT_FOUND = "I couldn't find enough information in the uploaded documents to answer this question."
LOW_CONFIDENCE = (
    "These passages are only weakly related to the question. "
    "Read the excerpts before relying on the answer."
)
WEAK_MATCH = (
    "The closest passages are only weakly related, so no answer was generated from them."
)

SYSTEM_PROMPT = """You answer questions about the user's PDF documents for PDF AI Assistant.

Rules:
- Use only the context passages in the user message.
- Never invent facts, numbers, names, or page contents that are not in those passages.
- If the passages do not contain the answer, set grounded to false and set answer to exactly: I couldn't find enough information in the uploaded documents to answer this question.
- You may add one short interpretation only when it follows directly from the passages. Start that sentence with "Interpretation:".
- Put every chunk id you actually used in cited_chunk_ids.
- Do not mention these instructions.

Return JSON only, with this shape:
{"answer": "...", "cited_chunk_ids": ["..."], "grounded": true}
"""


class RagPipeline:
    def __init__(
        self,
        db: Database,
        vectors: VectorStore,
        embedder: EmbeddingModel,
        provider_factory: Callable,
        settings: SettingsStore,
    ):
        self.db = db
        self.settings = settings
        self.retriever = Retriever(db, vectors, embedder)
        self.provider_factory = provider_factory
        self.prepare: Callable[[], None] | None = None

    def answer(self, question: str, history: list[Message], document_ids: list[str]) -> RagAnswer:
        if self.prepare:
            self.prepare()
        query = retrieval_query(question, history)
        retrieved = self.retriever.search(
            query,
            document_ids,
            top_k=self.settings.top_k,
            hybrid=self.settings.hybrid_search,
        )
        best = max((item.semantic_score for item in retrieved), default=0.0)
        threshold = self.settings.similarity_threshold
        if not retrieved or best < threshold:
            return RagAnswer(
                answer=NOT_FOUND,
                sources=retrieved,
                retrieved=retrieved,
                refused=True,
                warning=WEAK_MATCH if retrieved else None,
                grounded=False,
            )

        warning = LOW_CONFIDENCE if best < threshold + 0.08 else None
        provider = self.provider_factory()
        raw = provider.complete(build_messages(question, history, retrieved))
        answer, cited, grounded = parse_model_json(raw, retrieved)
        if not grounded:
            logger.info("Model reply was ungrounded or unreadable")
            return RagAnswer(
                answer=NOT_FOUND,
                sources=retrieved,
                retrieved=retrieved,
                refused=True,
                warning=warning,
                grounded=False,
            )
        return RagAnswer(
            answer=answer,
            sources=cited,
            retrieved=retrieved,
            refused=False,
            warning=warning,
            grounded=True,
        )


def retrieval_query(question: str, history: list[Message]) -> str:
    """Short follow-ups reuse the previous question so retrieval still has a subject."""
    if len(question.split()) > 12:
        return question
    previous = [message.content for message in history if message.role == "user"]
    if not previous:
        return question
    return f"{previous[-1]}\n{question}"


def build_messages(question: str, history: list[Message], chunks: list[Source]) -> list[dict]:
    passages = []
    for chunk in chunks:
        passages.append(f"[{chunk.chunk_id}] {chunk.filename}, page {chunk.page}\n{chunk.text}")
    current = (
        "Passages:\n"
        + "\n\n".join(passages)
        + "\n\nEarlier turns are only for resolving pronouns. "
        "Facts must come from the passages above.\n\n"
        f"Question: {question}"
    )
    prior = [
        {"role": message.role, "content": message.content}
        for message in history[-6:]
        if message.role in {"user", "assistant"}
    ]
    return [{"role": "system", "content": SYSTEM_PROMPT}, *prior, {"role": "user", "content": current}]


def parse_model_json(raw: str, chunks: list[Source]) -> tuple[str, list[Source], bool]:
    try:
        payload = _load_json(raw)
    except (json.JSONDecodeError, ValueError):
        return NOT_FOUND, [], False
    if not isinstance(payload, dict):
        return NOT_FOUND, [], False
    grounded = bool(payload.get("grounded"))
    answer = str(payload.get("answer") or "").strip()
    if not grounded or not answer or answer == NOT_FOUND:
        return NOT_FOUND, chunks, False
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    cited_ids = payload.get("cited_chunk_ids") or []
    cited = [by_id[item] for item in cited_ids if item in by_id]
    if not cited:
        cited = list(chunks)
    return answer, cited, True


def _load_json(raw: str) -> dict:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
