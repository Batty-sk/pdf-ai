"""FAISS inner-product index. Vectors are L2-normalized so scores are cosine."""

from __future__ import annotations

import threading
from pathlib import Path

import faiss
import numpy as np


class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.index = None
        if path.exists():
            self.index = faiss.read_index(str(path))

    @property
    def exists(self) -> bool:
        return self.index is not None and self.index.ntotal > 0

    def all_ids(self) -> set[int]:
        with self._lock:
            if self.index is None or self.index.ntotal == 0:
                return set()
            try:
                raw = faiss.vector_to_array(self.index.id_map)
            except Exception:
                return set()
        return {int(value) for value in raw}

    def add(self, ids: list[int], vectors: list[list[float]]) -> None:
        if not ids:
            return
        matrix = _matrix(vectors)
        id_array = np.asarray(ids, dtype=np.int64)
        with self._lock:
            if self.index is None:
                base = faiss.IndexFlatIP(matrix.shape[1])
                self.index = faiss.IndexIDMap2(base)
            elif self.index.d != matrix.shape[1]:
                raise ValueError("Embedding size does not match the saved index.")
            self.index.add_with_ids(matrix, id_array)
            self._save()

    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]:
        with self._lock:
            if self.index is None or self.index.ntotal == 0 or limit <= 0:
                return []
            matrix = _matrix([vector])
            if matrix.shape[1] != self.index.d:
                raise ValueError("Embedding size does not match the saved index.")
            k = min(limit, self.index.ntotal)
            scores, ids = self.index.search(matrix, k)
        found: list[tuple[int, float]] = []
        for score, index in zip(scores[0], ids[0]):
            if int(index) < 0:
                continue
            found.append((int(index), float(score)))
        return found

    def remove(self, ids: list[int]) -> None:
        usable = [int(value) for value in ids if value is not None]
        if not usable:
            return
        with self._lock:
            if self.index is None:
                return
            try:
                self.index.remove_ids(np.asarray(usable, dtype=np.int64))
            except RuntimeError:
                return
            self._save()

    def clear(self) -> None:
        with self._lock:
            dimension = self.index.d if self.index is not None else None
            self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension)) if dimension else None
            if self.path.exists():
                self.path.unlink()
            if self.index is not None:
                self._save()

    def _save(self) -> None:
        if self.index is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.path))


def _matrix(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    faiss.normalize_L2(matrix)
    return np.ascontiguousarray(matrix)
