"""Logging that never writes API keys to disk."""

from __future__ import annotations

import logging
import re
from pathlib import Path

_SECRET = re.compile(
    r"(?P<sk>sk-[A-Za-z0-9_\-]{8,})"
    r"|(?P<gemini>AQ\.[A-Za-z0-9_\-]{8,})"
    r"|(?P<bearer>Bearer\s+[A-Za-z0-9_\-\.]+)"
    r"|(?P<label>(?:api[_-]?key|authorization)\s*[=:]\s*)(?P<value>\S+)",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Replace key-shaped strings before they reach a log file."""

    def _sub(match: re.Match[str]) -> str:
        if match.group("label"):
            return match.group("label") + "[redacted]"
        return "[redacted]"

    return _SECRET.sub(_sub, text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(item) if isinstance(item, str) else item for item in record.args
            )
        return True


def setup_logging(log_path: Path) -> None:
    """Write a single app log. HTTP client loggers stay quiet so headers are not stored."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RedactFilter())
    root.addHandler(file_handler)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(RedactFilter())
    root.addHandler(stream)

    for name in ("openai", "httpx", "httpcore", "huggingface_hub", "httpx2", "filelock"):
        logging.getLogger(name).setLevel(logging.ERROR)
