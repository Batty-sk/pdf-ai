"""Hybrid retrieval: cosine similarity blended with SQLite keyword search."""

from __future__ import annotations

import re

from database.database import Database
from database.models import Source
from rag.embeddings import EmbeddingModel
from rag.vector_store import VectorStore

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "what", "how", "when", "where", "who", "why", "which", "about", "into",
}


class Retriever:
    def __init__(self, db: Database, vectors: VectorStore, embedder: EmbeddingModel):
        self.db = db
        self.vectors = vectors
        self.embedder = embedder

    def search(
        self,
        question: str,
        document_ids: list[str],
        top_k: int,
        hybrid: bool,
    ) -> list[Source]:
        if not document_ids:
            return []
        allowed = set(document_ids)
        semantic = self._semantic(question, allowed)
        keyword = self._keyword(question, document_ids) if hybrid else []
        return _fuse(semantic, keyword, hybrid)[:top_k]

    def _semantic(self, question: str, allowed: set[str]) -> list[tuple[Source, float]]:
        total = 0 if self.vectors.index is None else self.vectors.index.ntotal
        if total == 0:
            return []
        limit = total if total <= 5000 else min(total, 400)
        try:
            hits = self.vectors.search(self.embedder.embed_query(question), limit)
        except ValueError:
            return []
        by_id = {chunk.faiss_id: chunk for chunk in self.db.get_chunks_by_faiss_ids([hit[0] for hit in hits])}
        found: list[tuple[Source, float]] = []
        for faiss_id, score in hits:
            chunk = by_id.get(faiss_id)
            if chunk is None or chunk.document_id not in allowed:
                continue
            source = Source(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                stored_path=chunk.stored_path,
                page=chunk.page,
                text=chunk.text,
                score=score,
                semantic_score=score,
            )
            found.append((source, score))
        return found

    def _keyword(self, question: str, document_ids: list[str]) -> list[Source]:
        match = fts_query(question)
        if not match:
            return []
        rows = self.db.keyword_search(match, document_ids, limit=30)
        sources: list[Source] = []
        for chunk, _rank in rows:
            sources.append(
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
            )
        return sources


def fts_query(text: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z]{2,}", text)
    kept = [token for token in tokens if token.lower() not in _STOP][:16]
    if not kept:
        return ""
    return " OR ".join(f'"{token}"' for token in kept)


def _fuse(semantic: list[tuple[Source, float]], keyword: list[Source], hybrid: bool) -> list[Source]:
    """Rank by a blend of cosine and keyword rank. The stored score stays the cosine."""
    pooled: dict[str, Source] = {}
    keyword_rank: dict[str, float] = {}
    for source, cosine in semantic:
        source.semantic_score = cosine
        source.score = cosine
        pooled[source.chunk_id] = source
    for rank, source in enumerate(keyword):
        keyword_rank[source.chunk_id] = 1.0 / (rank + 1)
        pooled.setdefault(source.chunk_id, source)

    if not hybrid:
        ordered = sorted(pooled.values(), key=lambda item: item.semantic_score, reverse=True)
        return ordered

    ranked: list[Source] = []
    for source in pooled.values():
        lexical = keyword_rank.get(source.chunk_id, 0.0)
        if source.semantic_score > 0 and lexical > 0:
            blend = 0.7 * source.semantic_score + 0.3 * lexical
        elif source.semantic_score > 0:
            blend = source.semantic_score
        else:
            blend = lexical * 0.2
        source.score = source.semantic_score if source.semantic_score > 0 else blend
        ranked.append((blend, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [source for _blend, source in ranked]
