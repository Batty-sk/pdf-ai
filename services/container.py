"""Wire the database, index, and services the window uses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from database.database import Database
from evaluation.evaluator import Evaluator
from llm.openai_provider import OpenAICompatibleProvider
from rag.embeddings import EmbeddingModel, FastEmbedder
from rag.rag_pipeline import RagPipeline
from rag.vector_store import VectorStore
from services.chat_service import ChatService
from services.compare_service import CompareService
from services.document_service import DocumentService
from utils.config import SettingsStore, default_data_dir
from utils.logging import setup_logging


@dataclass
class AppContext:
    data_dir: Path
    db: Database
    settings: SettingsStore
    documents: DocumentService
    chat: ChatService
    compare: CompareService
    evaluator: Evaluator
    pipeline: RagPipeline


def build_context(
    data_dir: Path | None = None,
    embedder: EmbeddingModel | None = None,
    provider_factory=None,
) -> AppContext:
    directory = data_dir or default_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "documents").mkdir(exist_ok=True)
    (directory / "models").mkdir(exist_ok=True)
    setup_logging(directory / "app.log")
    db = Database(directory / "app.db")
    settings = SettingsStore(db)
    vectors = VectorStore(directory / "index.faiss")
    model = embedder or FastEmbedder(directory / "models")
    documents = DocumentService(db, vectors, model, settings, directory / "documents")
    if provider_factory is None:
        provider_factory = lambda: OpenAICompatibleProvider.from_settings(settings, directory)
    pipeline = RagPipeline(db, vectors, model, provider_factory, settings)
    pipeline.prepare = documents.ensure_vectors
    return AppContext(
        data_dir=directory,
        db=db,
        settings=settings,
        documents=documents,
        chat=ChatService(db, pipeline),
        compare=CompareService(db, pipeline, settings),
        evaluator=Evaluator(db, pipeline),
        pipeline=pipeline,
    )
