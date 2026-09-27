"""Write a chat to text or PDF, including the cited pages."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument

from database.models import Message


def write_text(path: str, body: str) -> None:
    Path(path).write_text(body, encoding="utf-8")


def write_pdf(path: str, title: str, messages: list[Message]) -> None:
    parts = [f"<h1>{escape(title)}</h1>"]
    for message in messages:
        speaker = "You" if message.role == "user" else "PDF AI Assistant"
        body = escape(message.content).replace("\n", "<br>")
        parts.append(f"<p><strong>{speaker}</strong><br>{body}</p>")
        if message.sources and message.warning != "error":
            items = []
            for source in message.sources:
                filename = escape(str(source.get("filename", "PDF")))
                page = escape(str(source.get("page", "")))
                items.append(f"<li>{filename}, page {page}</li>")
            parts.append("<ul>" + "".join(items) + "</ul>")
    document = QTextDocument()
    document.setHtml("".join(parts))
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(96)
    document.print_(writer)
