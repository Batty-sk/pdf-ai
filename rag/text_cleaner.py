"""Normalize extracted PDF text before it is chunked."""

from __future__ import annotations

import re
import unicodedata


def clean_text(text: str) -> str:
    """Join hyphenated line breaks and collapse noisy whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
