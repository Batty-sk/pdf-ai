"""Copy, index, and remove PDFs. The GUI never talks to FAISS directly."""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from database.database import Database, utc_now
from database.models import ChunkRecord, Document, IndexResult
from rag.chunker import chunk_pages
from rag.embeddings import EmbeddingModel
from rag.pdf_loader import PageText, load_pdf
from rag.text_cleaner import clean_text
from rag.vector_store import VectorStore
from utils.config import SettingsStore
from utils.errors import PdfError
from utils.security import sanitize_filename, validate_upload

logger = logging.getLogger(__name__)

Progress = Callable[[str], None]


def _store_pdf(source: Path, dest: Path, password: str | None) -> None:
    """Save an unencrypted working copy so page preview does not need the password again."""
    import pymupdf

    from utils.errors import PasswordProtectedError

    document = pymupdf.open(source)
    try:
        if document.is_encrypted and not document.authenticate(password or ""):
            raise PasswordProtectedError("This PDF is password-protected.")
        document.save(str(dest), encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3)
    finally:
        document.close()


class DocumentService:
    def __init__(
        self,
        db: Database,
        vectors: VectorStore,
        embedder: EmbeddingModel,
        settings: SettingsStore,
        files_dir: Path,
    ):
        self.db = db
        self.vectors = vectors
        self.embedder = embedder
        self.settings = settings
        self.files_dir = files_dir
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._synced = False

    def index_file(
        self,
        path: Path,
        password: str | None,
        progress: Progress,
        display_name: str | None = None,
    ) -> IndexResult:
        try:
            validate_upload(path)
        except PdfError as exc:
            return IndexResult(None, f"{display_name or path.name}: {exc}", None)

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = self.db.find_by_hash(digest)
        if existing and existing.status == "ready":
            return IndexResult(existing, f"{existing.filename} is already in the library.", None)
        if existing:
            self.remove(existing.id)

        safe_name = sanitize_filename(display_name or path.name)
        stored = self.files_dir / f"{uuid.uuid4().hex[:10]}_{safe_name}"
        try:
            _store_pdf(path, stored, password)
        except PdfError as exc:
            stored.unlink(missing_ok=True)
            return IndexResult(None, f"{safe_name}: {exc}", None)
        except Exception:
            logger.exception("Could not store %s", safe_name)
            stored.unlink(missing_ok=True)
            return IndexResult(None, f"{safe_name}: This PDF could not be opened.", None)
        document = Document(
            id=str(uuid.uuid4()),
            filename=safe_name,
            stored_path=str(stored),
            page_count=0,
            status="indexing",
            file_hash=digest,
            indexed_at=None,
            error_message=None,
            ocr_used=False,
        )
        self.db.insert_document(document)
        try:
            progress(f"Reading {safe_name}…")
            loaded = load_pdf(stored, password)
            pages = [PageText(page.number, clean_text(page.text)) for page in loaded.pages]
            drafts = chunk_pages(pages, self.settings.chunk_size, self.settings.chunk_overlap)
            if not drafts:
                raise PdfError("No readable text was left after cleaning.")
            if not getattr(self.embedder, "is_cached", True):
                progress("Downloading the local embedding model. This happens once…")
            progress(f"Embedding {safe_name}…")
            vectors = self._embed_batched([draft.text for draft in drafts], progress, safe_name)
            faiss_start = self.db.next_faiss_id()
            records = []
            for offset, draft in enumerate(drafts):
                records.append(
                    ChunkRecord(
                        id=str(uuid.uuid4()),
                        document_id=document.id,
                        page=draft.page,
                        chunk_index=draft.chunk_index,
                        text=draft.text,
                        faiss_id=faiss_start + offset,
                    )
                )
            self.db.insert_chunks(records)
            self.vectors.add([record.faiss_id for record in records], vectors)
            self.db.update_document_status(
                document.id,
                status="ready",
                page_count=loaded.page_count,
                indexed_at=utc_now(),
                error_message=None,
                ocr_used=loaded.ocr_used,
            )
            self._synced = True
            logger.info("Indexed %s pages=%s chunks=%s", safe_name, loaded.page_count, len(records))
            ready = self.db.get_document(document.id)
            return IndexResult(ready, None, loaded.warning)
        except PdfError as exc:
            self._fail(document.id, str(exc))
            return IndexResult(None, f"{safe_name}: {exc}", None)
        except Exception:
            logger.exception("Indexing failed for %s", safe_name)
            self._fail(document.id, "Could not index this PDF.")
            return IndexResult(None, f"{safe_name}: Could not index this PDF.", None)

    def reindex_all(self, progress: Progress) -> list[IndexResult]:
        """Rebuild every ready PDF with the current chunk settings."""
        ready = [doc for doc in self.db.list_documents() if doc.status == "ready"]
        scratch = self.files_dir.parent / "reindex"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        snapshots: list[tuple[str, Path]] = []
        for document in ready:
            source = Path(document.stored_path)
            if not source.exists():
                continue
            dest = scratch / f"{uuid.uuid4().hex[:8]}_{document.filename}"
            shutil.copy2(source, dest)
            snapshots.append((document.filename, dest))
        self.clear_all()
        results: list[IndexResult] = []
        if not snapshots:
            progress("No documents to reindex.")
            shutil.rmtree(scratch, ignore_errors=True)
            return results
        total = len(snapshots)
        for index, (filename, path) in enumerate(snapshots, start=1):
            progress(f"Processing document {index} of {total}…")
            results.append(self.index_file(path, None, progress, display_name=filename))
        shutil.rmtree(scratch, ignore_errors=True)
        self._synced = True
        return results

    def remove(self, document_id: str) -> None:
        document = self.db.get_document(document_id)
        if document is None:
            return
        faiss_ids = self.db.faiss_ids_for_document(document_id)
        self.vectors.remove(faiss_ids)
        stored = Path(document.stored_path)
        self.db.delete_document(document_id)
        if stored.exists():
            stored.unlink()

    def clear_all(self) -> None:
        for document in self.db.list_documents():
            stored = Path(document.stored_path)
            if stored.exists():
                stored.unlink()
        self.db.delete_all_documents()
        self.vectors.clear()
        self._synced = True

    def ensure_vectors(self) -> None:
        """Repair an index that was interrupted, without loading the model when it already matches."""
        if self._synced:
            return
        db_ids = set(self.db.all_faiss_ids())
        have = self.vectors.all_ids()
        if db_ids == have:
            self._synced = True
            return
        extra = have - db_ids
        if extra:
            self.vectors.remove(list(extra))
        missing = [faiss_id for faiss_id in db_ids if faiss_id not in have]
        if missing:
            chunks = self.db.get_chunks_by_faiss_ids(missing)
            ordered = sorted(chunks, key=lambda chunk: chunk.faiss_id or 0)
            vectors = self._embed_batched([chunk.text for chunk in ordered], lambda _message: None, "index")
            self.vectors.add([chunk.faiss_id for chunk in ordered], vectors)
        self._synced = True

    def _embed_batched(self, texts: list[str], progress: Progress, label: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch = 32
        total = len(texts)
        for start in range(0, total, batch):
            piece = texts[start : start + batch]
            vectors.extend(self.embedder.embed_documents(piece))
            progress(f"Embedding {label} ({min(start + batch, total)} of {total} passages)…")
        return vectors

    def _fail(self, document_id: str, message: str) -> None:
        faiss_ids = self.db.faiss_ids_for_document(document_id)
        if faiss_ids:
            self.vectors.remove(faiss_ids)
        # Drop partial chunks by deleting and recreating is heavier. Remove chunk rows
        # through a document delete of chunks only: delete_document removes the row too.
        document = self.db.get_document(document_id)
        if document is None:
            return
        self.db.delete_document(document_id)
        # Keep the copied file and a visible error row so the user knows what failed.
        failed = Document(
            id=document_id,
            filename=document.filename,
            stored_path=document.stored_path,
            page_count=0,
            status="error",
            file_hash=document.file_hash,
            indexed_at=None,
            error_message=message,
            ocr_used=False,
        )
        self.db.insert_document(failed)
