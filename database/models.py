"""Plain records passed between the database, retrieval, and the interface."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Document:
    id: str
    filename: str
    stored_path: str
    page_count: int
    status: str
    file_hash: str
    indexed_at: str | None
    error_message: str | None
    ocr_used: bool


@dataclass
class ChunkRecord:
    id: str
    document_id: str
    page: int
    chunk_index: int
    text: str
    faiss_id: int | None
    filename: str = ""
    stored_path: str = ""


@dataclass
class Chat:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: str
    chat_id: str
    role: str
    content: str
    sources: list[dict]
    warning: str | None
    created_at: str


@dataclass
class Source:
    chunk_id: str
    document_id: str
    filename: str
    stored_path: str
    page: int
    text: str
    score: float
    semantic_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "stored_path": self.stored_path,
            "page": self.page,
            "text": self.text,
            "score": self.score,
            "semantic_score": self.semantic_score,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Source":
        return cls(
            chunk_id=str(payload.get("chunk_id", "")),
            document_id=str(payload.get("document_id", "")),
            filename=str(payload.get("filename", "")),
            stored_path=str(payload.get("stored_path", "")),
            page=int(payload.get("page") or 0),
            text=str(payload.get("text", "")),
            score=float(payload.get("score") or 0),
            semantic_score=float(payload.get("semantic_score") or payload.get("score") or 0),
        )


@dataclass
class RagAnswer:
    answer: str
    sources: list[Source]
    retrieved: list[Source]
    refused: bool
    warning: str | None
    grounded: bool


@dataclass
class IndexResult:
    document: Document | None
    error: str | None = None
    warning: str | None = None


@dataclass
class CompareRow:
    topic: str
    left: str
    right: str
    left_pages: list[int] = field(default_factory=list)
    right_pages: list[int] = field(default_factory=list)


@dataclass
class CompareResult:
    summary: str
    rows: list[CompareRow]
    left_name: str
    right_name: str
    sources: list[Source]
    error: str | None = None


@dataclass
class EvalCase:
    id: str
    question: str
    expected_answer: str
    expected_filename: str
    expected_page: int | None
    expect_unsupported: bool


@dataclass
class CaseScore:
    case_id: str
    question: str
    answer: str
    retrieval_hit: bool | None
    citation_hit: bool | None
    answer_score: float | None
    unsupported_correct: bool | None
    latency_ms: int


@dataclass
class EvalSummary:
    retrieval_accuracy: float | None
    citation_accuracy: float | None
    answer_accuracy: float | None
    unsupported_detection: float | None
    mean_latency_ms: float
    results: list[CaseScore]
