"""Deterministic stand-ins so tests do not download a model or call an API."""

from __future__ import annotations

import hashlib
import json
import re

import numpy as np

from rag.rag_pipeline import NOT_FOUND


class HashEmbedder:
    dimension = 64

    def __init__(self):
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text).tolist() for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._embed(text).tolist()

    def _embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.dimension
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector


class ScriptedProvider:
    """Cite the first chunk id in the prompt and answer from the sample policy."""

    def __init__(self):
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], *, json_mode: bool = True) -> str:
        self.calls.append(messages)
        text = messages[-1]["content"]
        question = text.split("Question:")[-1].lower()
        if "zzzz" in question:
            return json.dumps({"answer": NOT_FOUND, "cited_chunk_ids": [], "grounded": False})
        match = re.search(r"\[([0-9a-fA-F-]{36})\]", text)
        cited = [match.group(1)] if match else []
        return json.dumps(
            {
                "answer": "Employees are entitled to 20 days of annual leave.",
                "cited_chunk_ids": cited,
                "grounded": True,
            }
        )


class BrokenProvider:
    def complete(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return "Employees get 20 days, I am sure of it."


class CompareProvider:
    def complete(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return json.dumps(
            {
                "summary": "Annual leave differs.",
                "rows": [
                    {
                        "topic": "Annual leave",
                        "document_1": "20 days",
                        "document_2": "24 days",
                        "doc1_pages": [1],
                        "doc2_pages": [1],
                    }
                ],
            }
        )
