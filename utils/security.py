"""File checks and credential storage.

A key typed in Settings is stored in the system keychain when that is available.
If the keychain cannot be used, it is written to a user-only file under the app
data directory and is never placed in SQLite. An empty Settings field uses the
built-in Gemini key instead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from pathlib import Path

from utils.errors import FileTooLargeError, InvalidPdfError, UnsupportedFileError

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 100 * 1024 * 1024
_KEYCHAIN_SERVICE = "PDF AI Assistant"
_KEYCHAIN_NAME = "llm_api_key"
BUILTIN_GEMINI_API_KEY = ""


def sanitize_filename(name: str) -> str:
    """Keep a display name that is safe to store and show."""
    base = Path(name).name.replace("\x00", "")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if not cleaned:
        cleaned = "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned[:180]


def validate_upload(path: Path) -> None:
    """Reject anything that is not a modestly sized PDF."""
    if path.suffix.lower() != ".pdf":
        raise UnsupportedFileError("Unsupported file type. Add a PDF.")
    if not path.is_file():
        raise InvalidPdfError("That file could not be read.")
    size = path.stat().st_size
    if size > MAX_PDF_BYTES:
        raise FileTooLargeError("This PDF is larger than 100 MB. Split it and try again.")
    if size < 5:
        raise InvalidPdfError("This file is not a valid PDF.")
    with path.open("rb") as handle:
        header = handle.read(1024)
    if b"%PDF" not in header:
        raise InvalidPdfError("This file is not a valid PDF.")


def _credential_file(data_dir: Path) -> Path:
    return data_dir / "credentials.json"


def _read_fallback(data_dir: Path) -> str:
    path = _credential_file(data_dir)
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = payload.get("api_key", "")
    return value if isinstance(value, str) else ""


def _write_fallback(data_dir: Path, api_key: str) -> None:
    path = _credential_file(data_dir)
    if not api_key:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps({"api_key": api_key}), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.info("Could not restrict permissions on the credential file")


def stored_api_key(data_dir: Path) -> str:
    """Return only the key the user saved. An empty string means the field is blank."""
    try:
        import keyring

        stored = keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_NAME)
        if stored:
            return stored
    except Exception:
        logger.info("System keychain is unavailable; checking the local credential file")
    return _read_fallback(data_dir)


def get_api_key(data_dir: Path) -> str:
    """Use the saved key, or the built-in Gemini key when Settings is left blank."""
    saved = stored_api_key(data_dir).strip()
    return saved or BUILTIN_GEMINI_API_KEY


def set_api_key(data_dir: Path, api_key: str) -> None:
    api_key = api_key.strip()
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        if api_key:
            keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_NAME, api_key)
        else:
            try:
                keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_NAME)
            except PasswordDeleteError:
                pass
        _write_fallback(data_dir, "")
        return
    except Exception:
        logger.info("Could not write to the system keychain; using a private credential file")
    _write_fallback(data_dir, api_key)
