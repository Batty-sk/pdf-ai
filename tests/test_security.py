import logging
from pathlib import Path

import pytest

from rag.pdf_loader import load_pdf
from tests.pdfutil import write_image_only_pdf, write_locked_pdf, write_text_pdf
from utils.errors import (
    FileTooLargeError,
    InvalidPdfError,
    PasswordProtectedError,
    ScannedPdfError,
    UnsupportedFileError,
)
from utils.logging import RedactFilter, redact
from utils import security


def test_rejects_non_pdf_and_bad_header(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFileError):
        security.validate_upload(text)

    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf")
    with pytest.raises(InvalidPdfError):
        security.validate_upload(fake)


def test_rejects_oversized_pdf(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(security, "MAX_PDF_BYTES", 20)
    path = tmp_path / "big.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * 40)
    with pytest.raises(FileTooLargeError):
        security.validate_upload(path)


def test_password_and_scanned_pdfs(tmp_path: Path, monkeypatch):
    locked = tmp_path / "locked.pdf"
    write_locked_pdf(locked)
    with pytest.raises(PasswordProtectedError):
        load_pdf(locked)
    loaded = load_pdf(locked, "secret")
    assert "Parking permits" in loaded.pages[0].text

    scanned = tmp_path / "scan.pdf"
    write_image_only_pdf(scanned)
    monkeypatch.setattr("rag.pdf_loader._tesseract_available", lambda: False)
    with pytest.raises(ScannedPdfError):
        load_pdf(scanned)


def test_text_pdf_keeps_page_numbers(tmp_path: Path):
    path = tmp_path / "policy.pdf"
    write_text_pdf(path, ["Employees are entitled to 20 days of annual leave."])
    loaded = load_pdf(path)
    assert loaded.page_count == 1
    assert loaded.pages[0].number == 1
    assert "20 days" in loaded.pages[0].text


def test_log_redacts_api_keys():
    secret = "sk-abc1234567890XYZ"
    assert secret not in redact(f"Authorization failed for {secret}")
    assert "redacted" in redact(f"api_key={secret}")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "using %s", (secret,), None)
    assert RedactFilter().filter(record)
    assert secret not in record.args[0]


def test_blank_settings_key_uses_builtin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(security, "stored_api_key", lambda data_dir: "")
    assert security.get_api_key(tmp_path) == security.BUILTIN_GEMINI_API_KEY


def test_saved_key_replaces_builtin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(security, "stored_api_key", lambda data_dir: "user-supplied-key")
    assert security.get_api_key(tmp_path) == "user-supplied-key"


def test_sanitize_filename():
    assert security.sanitize_filename("../My Policy!.pdf") == "My Policy_.pdf"
    assert security.sanitize_filename("no-extension") == "no-extension.pdf"
