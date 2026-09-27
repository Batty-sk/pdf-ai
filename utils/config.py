"""Paths, defaults, and saved preferences."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from database.database import Database

APP_NAME = "PDF AI Assistant"
VERSION = "1.0.0"

DEFAULTS: dict[str, str] = {
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "temperature": "0.1",
    "max_tokens": "800",
    "chunk_size": "900",
    "chunk_overlap": "150",
    "top_k": "5",
    "similarity_threshold": "0.35",
    "hybrid_search": "1",
    "theme": "system",
    "notice_dismissed": "0",
    "last_chat_id": "",
}


def default_data_dir() -> Path:
    override = os.environ.get("PDF_AI_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        root = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        path = Path(root) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        path = Path(root) / "pdf-ai-assistant"
    path.mkdir(parents=True, exist_ok=True)
    (path / "documents").mkdir(exist_ok=True)
    (path / "models").mkdir(exist_ok=True)
    return path


def asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


class SettingsStore:
    """Typed view over the settings table. The API key is not stored here."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> str:
        return self.db.get_setting(key, DEFAULTS.get(key, ""))

    def set(self, key: str, value: str) -> None:
        self.db.set_setting(key, value)

    @property
    def model(self) -> str:
        return self.get("model") or DEFAULTS["model"]

    @property
    def base_url(self) -> str:
        return self.get("base_url") or DEFAULTS["base_url"]

    @property
    def temperature(self) -> float:
        return _float(self.get("temperature"), 0.1, 0.0, 2.0)

    @property
    def max_tokens(self) -> int:
        return _int(self.get("max_tokens"), 800, 64, 8000)

    @property
    def chunk_size(self) -> int:
        return _int(self.get("chunk_size"), 900, 200, 4000)

    @property
    def chunk_overlap(self) -> int:
        overlap = _int(self.get("chunk_overlap"), 150, 0, 1000)
        return min(overlap, self.chunk_size // 2)

    @property
    def top_k(self) -> int:
        return _int(self.get("top_k"), 5, 1, 20)

    @property
    def similarity_threshold(self) -> float:
        return _float(self.get("similarity_threshold"), 0.35, 0.0, 1.0)

    @property
    def hybrid_search(self) -> bool:
        return self.get("hybrid_search") != "0"

    @property
    def theme(self) -> str:
        value = self.get("theme")
        return value if value in {"light", "dark", "system"} else "system"

    @property
    def notice_dismissed(self) -> bool:
        return self.get("notice_dismissed") == "1"

    @property
    def last_chat_id(self) -> str:
        return self.get("last_chat_id")


def _float(value: str, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _int(value: str, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))
