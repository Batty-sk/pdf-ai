"""Extract text from a PDF, one page at a time.

Scanned pages are sent through Tesseract only when that program is installed.
A missing OCR install becomes a clear error instead of an empty index.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from utils.errors import EmptyPdfError, InvalidPdfError, PasswordProtectedError, ScannedPdfError

logger = logging.getLogger(__name__)


@dataclass
class PageText:
    number: int
    text: str


@dataclass
class LoadedPdf:
    pages: list[PageText]
    page_count: int
    ocr_used: bool
    warning: str | None


def load_pdf(path: Path, password: str | None = None) -> LoadedPdf:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise InvalidPdfError("This PDF could not be opened.") from exc

    try:
        if document.is_encrypted and not document.authenticate(password or ""):
            raise PasswordProtectedError("This PDF is password-protected.")
        if document.page_count == 0:
            raise EmptyPdfError("This PDF has no pages.")

        pages: list[PageText] = []
        ocr_used = False
        skipped = 0
        for index, page in enumerate(document):
            text = page.get_text("text") or ""
            if not text.strip():
                ocr_text = _ocr_page(page)
                if ocr_text.strip():
                    text = ocr_text
                    ocr_used = True
                else:
                    skipped += 1
            pages.append(PageText(number=index + 1, text=text))

        readable = any(page.text.strip() for page in pages)
        if not readable:
            if skipped and not _tesseract_available():
                raise ScannedPdfError(
                    "This PDF has no text layer. Install Tesseract OCR to read scanned pages, "
                    "or upload a text-based PDF."
                )
            if skipped:
                raise ScannedPdfError(
                    "OCR could not read this scanned PDF. Check that Tesseract language data is installed."
                )
            raise EmptyPdfError("This PDF has no readable text.")

        warning = None
        if skipped:
            warning = f"{skipped} page(s) had no text and were skipped."
        if ocr_used:
            ocr_note = "Some text was read with OCR. Check those excerpts before relying on them."
            warning = f"{warning} {ocr_note}".strip() if warning else ocr_note
        return LoadedPdf(
            pages=pages,
            page_count=document.page_count,
            ocr_used=ocr_used,
            warning=warning,
        )
    finally:
        document.close()


def render_page_image(path: str, page_number: int, zoom: float = 1.6):
    """Return a PyMuPDF pixmap for the page preview, or None if it cannot be drawn."""
    try:
        document = pymupdf.open(path)
    except Exception:
        logger.info("Could not open PDF for page preview")
        return None
    try:
        if document.is_encrypted:
            return None
        index = page_number - 1
        if index < 0 or index >= document.page_count:
            return None
        page = document[index]
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    except Exception:
        logger.info("Could not render PDF page %s", page_number)
        return None
    finally:
        document.close()


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_page(page) -> str:
    if not _tesseract_available():
        return ""
    try:
        text_page = page.get_textpage_ocr(language="eng", dpi=200, full=True)
        return page.get_text("text", textpage=text_page) or ""
    except Exception:
        logger.info("OCR failed on a page")
        return ""
