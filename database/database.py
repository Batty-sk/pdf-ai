"""SQLite access for the library, chats, and evaluation set."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from database.models import Chat, ChunkRecord, Document, EvalCase, Message

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    indexed_at TEXT,
    error_message TEXT,
    ocr_used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    faiss_id INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_documents (
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (chat_id, document_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_json TEXT,
    warning TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_filename TEXT,
    expected_page INTEGER,
    expect_unsupported INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    results_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.fts_enabled = False
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._ensure_fts()
            self.conn.commit()

    def _ensure_fts(self) -> None:
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    body,
                    tokenize = 'porter unicode61'
                )
                """
            )
            self.fts_enabled = True
        except sqlite3.OperationalError:
            self.fts_enabled = False

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                yield
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.conn.commit()

    def find_by_hash(self, file_hash: str) -> Document | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM documents WHERE file_hash = ? ORDER BY indexed_at DESC",
                (file_hash,),
            ).fetchone()
        return _document(row) if row else None

    def insert_document(self, document: Document) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO documents (
                    id, filename, stored_path, page_count, status, file_hash,
                    indexed_at, error_message, ocr_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.filename,
                    document.stored_path,
                    document.page_count,
                    document.status,
                    document.file_hash,
                    document.indexed_at,
                    document.error_message,
                    int(document.ocr_used),
                ),
            )
            self.conn.commit()

    def update_document_status(
        self,
        document_id: str,
        *,
        status: str,
        page_count: int | None = None,
        indexed_at: str | None = None,
        error_message: str | None = None,
        ocr_used: bool | None = None,
    ) -> None:
        fields = ["status = ?", "error_message = ?"]
        values: list = [status, error_message]
        if page_count is not None:
            fields.append("page_count = ?")
            values.append(page_count)
        if indexed_at is not None:
            fields.append("indexed_at = ?")
            values.append(indexed_at)
        if ocr_used is not None:
            fields.append("ocr_used = ?")
            values.append(int(ocr_used))
        values.append(document_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE documents SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            self.conn.commit()

    def get_document(self, document_id: str) -> Document | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return _document(row) if row else None

    def list_documents(self) -> list[Document]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM documents ORDER BY filename COLLATE NOCASE"
            ).fetchall()
        return [_document(row) for row in rows]

    def next_faiss_id(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COALESCE(MAX(faiss_id), 0) + 1 AS next_id FROM chunks").fetchone()
        return int(row["next_id"])

    def insert_chunks(self, chunks: list[ChunkRecord]) -> None:
        with self._lock:
            for chunk in chunks:
                self.conn.execute(
                    """
                    INSERT INTO chunks (id, document_id, page, chunk_index, text, faiss_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.page,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.faiss_id,
                    ),
                )
                if self.fts_enabled:
                    self.conn.execute(
                        "INSERT INTO chunks_fts(chunk_id, body) VALUES (?, ?)",
                        (chunk.id, chunk.text),
                    )
            self.conn.commit()

    def faiss_ids_for_document(self, document_id: str) -> list[int]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT faiss_id FROM chunks WHERE document_id = ? AND faiss_id IS NOT NULL",
                (document_id,),
            ).fetchall()
        return [int(row["faiss_id"]) for row in rows]

    def all_faiss_ids(self) -> list[int]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT faiss_id FROM chunks WHERE faiss_id IS NOT NULL"
            ).fetchall()
        return [int(row["faiss_id"]) for row in rows]

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._delete_chunk_rows(document_id)
            self.conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            self.conn.commit()

    def delete_all_documents(self) -> None:
        with self._lock:
            if self.fts_enabled:
                self.conn.execute("DELETE FROM chunks_fts")
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM documents")
            self.conn.commit()

    def _delete_chunk_rows(self, document_id: str) -> None:
        if self.fts_enabled:
            ids = self.conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?",
                (document_id,),
            ).fetchall()
            for row in ids:
                self.conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (row["id"],))
        self.conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

    def list_chunks_for_document(self, document_id: str) -> list[ChunkRecord]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT c.*, d.filename, d.stored_path
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.document_id = ?
                ORDER BY c.page, c.chunk_index
                """,
                (document_id,),
            ).fetchall()
        return [_chunk(row) for row in rows]

    def get_chunks_by_faiss_ids(self, faiss_ids: list[int]) -> list[ChunkRecord]:
        if not faiss_ids:
            return []
        placeholders = ",".join("?" * len(faiss_ids))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT c.*, d.filename, d.stored_path
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.faiss_id IN ({placeholders})
                """,
                faiss_ids,
            ).fetchall()
        return [_chunk(row) for row in rows]

    def keyword_search(
        self,
        match: str,
        document_ids: list[str],
        limit: int,
    ) -> list[tuple[ChunkRecord, float]]:
        if not self.fts_enabled or not match or not document_ids:
            return []
        placeholders = ",".join("?" * len(document_ids))
        sql = f"""
            SELECT c.*, d.filename, d.stored_path, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH ?
              AND c.document_id IN ({placeholders})
            ORDER BY rank
            LIMIT ?
        """
        try:
            with self._lock:
                rows = self.conn.execute(sql, [match, *document_ids, limit]).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(_chunk(row), float(row["rank"])) for row in rows]

    def create_chat(self, title: str, document_ids: list[str]) -> Chat:
        chat_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (chat_id, title, now, now),
            )
            self._set_chat_documents(chat_id, document_ids)
            self.conn.commit()
        return Chat(chat_id, title, now, now)

    def rename_chat(self, chat_id: str, title: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
                (title, utc_now(), chat_id),
            )
            self.conn.commit()

    def touch_chat(self, chat_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (utc_now(), chat_id),
            )
            self.conn.commit()

    def delete_chat(self, chat_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            self.conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            self.conn.commit()

    def list_chats(self) -> list[Chat]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM chats ORDER BY updated_at DESC"
            ).fetchall()
        return [_chat(row) for row in rows]

    def get_chat(self, chat_id: str) -> Chat | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return _chat(row) if row else None

    def set_chat_documents(self, chat_id: str, document_ids: list[str]) -> None:
        with self._lock:
            self._set_chat_documents(chat_id, document_ids)
            self.conn.commit()

    def _set_chat_documents(self, chat_id: str, document_ids: list[str]) -> None:
        self.conn.execute("DELETE FROM chat_documents WHERE chat_id = ?", (chat_id,))
        for document_id in document_ids:
            self.conn.execute(
                "INSERT OR IGNORE INTO chat_documents (chat_id, document_id) VALUES (?, ?)",
                (chat_id, document_id),
            )

    def chat_document_ids(self, chat_id: str) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT document_id FROM chat_documents WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        return [row["document_id"] for row in rows]

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        sources: list[dict] | None,
        warning: str | None,
    ) -> Message:
        message_id = str(uuid.uuid4())
        now = utc_now()
        payload = json.dumps(sources or [])
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, sources_json, warning, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, chat_id, role, content, payload, warning, now),
            )
            self.conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )
            self.conn.commit()
        return Message(message_id, chat_id, role, content, sources or [], warning, now)

    def list_messages(self, chat_id: str) -> list[Message]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at, rowid",
                (chat_id,),
            ).fetchall()
        return [_message(row) for row in rows]

    def clear_messages(self, chat_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            self.conn.commit()

    def add_eval_case(self, case: EvalCase) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO eval_cases (
                    id, question, expected_answer, expected_filename,
                    expected_page, expect_unsupported, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.id,
                    case.question,
                    case.expected_answer,
                    case.expected_filename,
                    case.expected_page,
                    int(case.expect_unsupported),
                    utc_now(),
                ),
            )
            self.conn.commit()

    def delete_eval_case(self, case_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM eval_cases WHERE id = ?", (case_id,))
            self.conn.commit()

    def list_eval_cases(self) -> list[EvalCase]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM eval_cases ORDER BY created_at, rowid"
            ).fetchall()
        return [_eval_case(row) for row in rows]

    def replace_eval_cases(self, cases: list[EvalCase]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM eval_cases")
            now = utc_now()
            for case in cases:
                self.conn.execute(
                    """
                    INSERT INTO eval_cases (
                        id, question, expected_answer, expected_filename,
                        expected_page, expect_unsupported, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.id,
                        case.question,
                        case.expected_answer,
                        case.expected_filename,
                        case.expected_page,
                        int(case.expect_unsupported),
                        now,
                    ),
                )
            self.conn.commit()

    def save_eval_run(self, summary: dict, results: list[dict]) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO eval_runs (id, created_at, summary_json, results_json) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), utc_now(), json.dumps(summary), json.dumps(results)),
            )
            self.conn.commit()

    def latest_eval_run(self) -> tuple[dict, list[dict]] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT summary_json, results_json FROM eval_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return json.loads(row["summary_json"]), json.loads(row["results_json"])


def _document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        filename=row["filename"],
        stored_path=row["stored_path"],
        page_count=row["page_count"],
        status=row["status"],
        file_hash=row["file_hash"],
        indexed_at=row["indexed_at"],
        error_message=row["error_message"],
        ocr_used=bool(row["ocr_used"]),
    )


def _chunk(row: sqlite3.Row) -> ChunkRecord:
    keys = row.keys()
    return ChunkRecord(
        id=row["id"],
        document_id=row["document_id"],
        page=row["page"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        faiss_id=row["faiss_id"],
        filename=row["filename"] if "filename" in keys else "",
        stored_path=row["stored_path"] if "stored_path" in keys else "",
    )


def _chat(row: sqlite3.Row) -> Chat:
    return Chat(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(row: sqlite3.Row) -> Message:
    try:
        sources = json.loads(row["sources_json"] or "[]")
    except json.JSONDecodeError:
        sources = []
    if not isinstance(sources, list):
        sources = []
    return Message(
        id=row["id"],
        chat_id=row["chat_id"],
        role=row["role"],
        content=row["content"],
        sources=sources,
        warning=row["warning"],
        created_at=row["created_at"],
    )


def _eval_case(row: sqlite3.Row) -> EvalCase:
    page = row["expected_page"]
    return EvalCase(
        id=row["id"],
        question=row["question"],
        expected_answer=row["expected_answer"],
        expected_filename=row["expected_filename"] or "",
        expected_page=int(page) if page is not None else None,
        expect_unsupported=bool(row["expect_unsupported"]),
    )
