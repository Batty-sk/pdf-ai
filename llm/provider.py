"""Provider interface used by the RAG pipeline."""

from __future__ import annotations

from typing import Protocol


class LlmProvider(Protocol):
    def complete(self, messages: list[dict], *, json_mode: bool = True) -> str:
        """Return the model's text. Implementations must not log message bodies."""
