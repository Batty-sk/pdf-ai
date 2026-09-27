"""Local embeddings. Document text is not sent to the chat API to be indexed."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# BGE retrieval models expect this instruction on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingModel(Protocol):
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passage text."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a question."""


class FastEmbedder:
    """ONNX embedding model downloaded into the app data folder on first use."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None
        self.dimension = 384

    @property
    def is_cached(self) -> bool:
        return any(self.cache_dir.rglob("*.onnx"))

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info("Loading embedding model %s", MODEL_NAME)
            self._model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(self.cache_dir))
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = []
        for vector in model.embed(texts):
            array = vector.tolist()
            self.dimension = len(array)
            vectors.append(array)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([QUERY_PREFIX + text])[0]
