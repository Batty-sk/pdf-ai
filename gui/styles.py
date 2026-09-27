"""Gallery theme: cool gray room, white sheets, ink type, a quiet page number."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPixmap

from utils.config import asset_dir

SANS = "Figtree"
SERIF = "Fraunces"
MONO = "IBM Plex Mono"


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    card: str
    ink: str
    muted: str
    line: str
    accent: str
    accent_text: str
    stamp: str
    user_bubble: str
    user_text: str
    warning_bg: str
    warning_ink: str
    danger: str
    input_bg: str
    sidebar_text: str
    sidebar_muted: str
    chip: str
    track: str
    plate: str
    plate_text: str


LIGHT = Palette(
    name="light",
    bg="#E8E9ED",
    sidebar="#F7F7F8",
    card="#FFFFFF",
    ink="#14161A",
    muted="#6E7380",
    line="#E2E3E8",
    accent="#14161A",
    accent_text="#FFFFFF",
    stamp="#8E95A6",
    user_bubble="#E3E5EB",
    user_text="#14161A",
    warning_bg="#F4EFE4",
    warning_ink="#6A5430",
    danger="#8E3B3B",
    input_bg="#FFFFFF",
    sidebar_text="#14161A",
    sidebar_muted="#8A8F9C",
    chip="#EEEFF3",
    track="#E4E6EC",
    plate="#14161A",
    plate_text="#FFFFFF",
)

DARK = Palette(
    name="dark",
    bg="#0E0F12",
    sidebar="#141518",
    card="#1C1D22",
    ink="#F4F5F7",
    muted="#9AA0AE",
    line="#2C2E36",
    accent="#F4F5F7",
    accent_text="#14161A",
    stamp="#8E95A6",
    user_bubble="#2A2C33",
    user_text="#F4F5F7",
    warning_bg="#2E291F",
    warning_ink="#E4D2A8",
    danger="#E09A9A",
    input_bg="#1C1D22",
    sidebar_text="#F4F5F7",
    sidebar_muted="#8A8F9C",
    chip="#24262E",
    track="#2A2C33",
    plate="#F4F5F7",
    plate_text="#14161A",
)


def load_fonts() -> None:
    """Register the bundled faces. If the OS rejects them, the stylesheet falls back."""
    global SANS, SERIF, MONO
    folder = asset_dir() / "fonts"
    if not folder.exists():
        return
    # Core Text on macOS can refuse fonts that live inside Documents.
    # Register a copy from a neutral temp directory instead.
    cache = Path(tempfile.gettempdir()) / "PDF AI Assistant" / "fonts"
    cache.mkdir(parents=True, exist_ok=True)
    sans_names: list[str] = []
    serif_names: list[str] = []
    mono_names: list[str] = []
    for source in sorted(Path(folder).glob("*.ttf")):
        path = cache / source.name
        if not path.exists() or path.stat().st_size != source.stat().st_size:
            shutil.copy2(source, path)
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        for name in QFontDatabase.applicationFontFamilies(font_id):
            lowered = name.lower()
            if "figtree" in lowered:
                sans_names.append(name)
            elif "fraunces" in lowered:
                serif_names.append(name)
            elif "plex mono" in lowered:
                mono_names.append(name)
    SANS = _preferred_family(sans_names, "Figtree")
    SERIF = _preferred_family(serif_names, "Fraunces")
    MONO = _preferred_family(mono_names, "IBM Plex Mono")


def _preferred_family(names: list[str], ideal: str) -> str:
    if ideal in names:
        return ideal
    plain = [
        name
        for name in names
        if not any(word in name.lower() for word in ("semi", "bold", "light", "italic", "medium"))
    ]
    if plain:
        return plain[0]
    return names[0] if names else ideal


def resolve_palette(preference: str) -> Palette:
    if preference == "dark":
        return DARK
    if preference == "light":
        return LIGHT
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def stylesheet(palette: Palette) -> str:
    css = _CSS
    # Longer tokens first so "@sidebar_text@" is not clipped by "@sidebar@".
    for key in sorted(palette.__dict__, key=len, reverse=True):
        css = css.replace(f"@{key}@", str(palette.__dict__[key]))
    css = css.replace("@sans@", SANS).replace("@serif@", SERIF).replace("@mono@", MONO)
    return css


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#14161A"))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#F7F7F8"))
    painter.setFont(QFont(SERIF, 22))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "p")
    painter.end()
    return QIcon(pixmap)


_CSS = """
* { font-family: "@sans@", "Avenir Next", "Helvetica Neue", sans-serif; }
QMainWindow, QDialog { background: @bg@; color: @ink@; }
QWidget#CenterRoot, QWidget#SettingsRoot, QWidget#SettingsForm, QWidget#CompareRoot, QWidget#EvalRoot, QWidget#EvidenceRoot, QWidget#TranscriptBody, QWidget#EvidenceBody {
    background: @bg@; color: @ink@;
}
QWidget#Sidebar { background: @sidebar@; color: @sidebar_text@; border-right: 1px solid @line@; }
QWidget#EvidenceRoot { border-left: 1px solid @line@; }
QWidget#Sidebar QLabel { color: @sidebar_text@; background: transparent; }
QWidget#Sidebar QLabel#Muted, QWidget#Sidebar QLabel#Section { color: @sidebar_muted@; background: transparent; }
QLabel { color: @ink@; background: transparent; }
QLabel#Muted { color: @muted@; }
QLabel#PaneTitle {
    font-family: "@serif@", "Iowan Old Style", Georgia, serif;
    font-size: 28px;
    color: @ink@;
}
QLabel#Brand {
    font-family: "@serif@", Georgia, serif;
    font-size: 20px;
    color: @sidebar_text@;
    background: transparent;
}
QLabel#Section {
    color: @muted@;
    font-family: "@mono@", Menlo, monospace;
    font-size: 11px;
}
QWidget#Sidebar QLabel#Section {
    color: @sidebar_muted@;
    font-family: "@mono@", Menlo, monospace;
    font-size: 11px;
}
QWidget#Sidebar QPushButton {
    background: transparent;
    color: @sidebar_text@;
    text-align: left;
    border: none;
    border-radius: 8px;
    padding: 8px 10px;
}
QWidget#Sidebar QPushButton:hover { background: @chip@; }
QWidget#Sidebar QPushButton:focus { border: none; }
QWidget#Sidebar QPushButton:checked { background: @chip@; }
QWidget#Sidebar QPushButton#PrimaryButton {
    background: @plate@;
    color: @plate_text@;
    text-align: center;
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 600;
}
QWidget#Sidebar QPushButton#PrimaryButton:hover { background: @plate@; }
QWidget#Sidebar QPushButton#LibraryAdd {
    background: @plate@;
    color: @plate_text@;
    text-align: center;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QWidget#Sidebar QPushButton#LibraryAdd:hover { background: @ink@; }
QWidget#Sidebar QPushButton#LibraryRemove {
    background: @card@;
    color: @ink@;
    text-align: center;
    border: 1px solid @line@;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QWidget#Sidebar QPushButton#LibraryRemove:hover { background: @chip@; }
QWidget#Sidebar QPushButton#LibraryClear {
    background: @card@;
    color: @danger@;
    text-align: center;
    border: 1px solid @danger@;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QWidget#Sidebar QPushButton#LibraryClear:hover { background: @warning_bg@; color: @danger@; }
QPushButton#PrimaryButton {
    background: @accent@;
    color: @accent_text@;
    text-align: center;
    border: none;
    border-radius: 12px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: @accent@; }
QPushButton#GhostButton, QPushButton#DangerButton {
    background: transparent;
    color: @muted@;
    border: none;
    border-radius: 8px;
    padding: 6px 8px;
}
QPushButton#DangerButton { color: @danger@; }
QPushButton#GhostButton:hover, QPushButton#DangerButton:hover { background: @chip@; color: @ink@; }
QPushButton#CitationChip {
    background: transparent;
    color: @muted@;
    border: none;
    border-radius: 6px;
    padding: 2px 0px;
    margin-right: 12px;
    font-size: 12px;
    text-align: left;
}
QPushButton#CitationChip:hover { color: @ink@; background: transparent; }
QPushButton:disabled { color: @muted@; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid @ink@;
}
QFrame#ComposerShell {
    background: @card@;
    border: 1px solid @line@;
    border-radius: 20px;
}
QFrame#ComposerShell QPlainTextEdit#Composer,
QFrame#ComposerShell QPlainTextEdit#Composer:focus {
    background: transparent;
    border: none;
    font-size: 15px;
    padding: 6px 4px;
}
QListWidget#ChatList, QListWidget#DocList {
    background: transparent;
    border: none;
    outline: none;
    color: @sidebar_text@;
}
QListWidget#ChatList::item, QListWidget#DocList::item {
    padding: 9px 10px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#ChatList::item:selected, QListWidget#DocList::item:selected {
    background: @chip@;
    color: @sidebar_text@;
}
QListWidget#ChatList::item:hover, QListWidget#DocList::item:hover {
    background: @chip@;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: @input_bg@;
    color: @ink@;
    border: 1px solid @line@;
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: @ink@;
    selection-color: @card@;
}
QPlainTextEdit#Composer { font-size: 15px; padding: 10px 12px; }
QComboBox::drop-down { border: none; width: 22px; }
QCheckBox { color: @ink@; spacing: 8px; }
QGroupBox {
    color: @ink@;
    border: 1px solid @line@;
    border-radius: 14px;
    margin-top: 16px;
    padding: 8px 8px 8px 8px;
    background: @card@;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; background: @bg@; }
QSlider { min-height: 32px; }
QSlider::groove:horizontal {
    height: 6px;
    background: @track@;
    border: none;
    border-radius: 3px;
    margin: 0 12px;
}
QSlider::sub-page:horizontal {
    background: @ink@;
    border-radius: 3px;
    margin: 0 12px;
}
QSlider::add-page:horizontal {
    background: transparent;
    margin: 0 12px;
}
QSlider::handle:horizontal {
    width: 22px;
    height: 22px;
    margin: -8px -11px;
    background: @card@;
    border: 2px solid @ink@;
    border-radius: 11px;
}
QSlider::handle:horizontal:hover { background: @ink@; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: @line@;
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar {
    background: @track@;
    border: none;
    border-radius: 1px;
}
QProgressBar::chunk { background: @ink@; border-radius: 1px; }
QTableWidget {
    background: @card@;
    color: @ink@;
    border: 1px solid @line@;
    border-radius: 12px;
    gridline-color: @line@;
    selection-background-color: @chip@;
    selection-color: @ink@;
}
QHeaderView::section {
    background: @bg@;
    color: @muted@;
    border: none;
    border-bottom: 1px solid @line@;
    padding: 8px;
    font-family: "@mono@", Menlo, monospace;
    font-size: 11px;
}
QMenu {
    background: @card@;
    color: @ink@;
    border: 1px solid @line@;
    padding: 4px;
}
QMenu::item { padding: 6px 18px; }
QMenu::item:selected { background: @chip@; }
QToolTip {
    background: @sidebar@;
    color: @sidebar_text@;
    border: none;
    padding: 6px 8px;
}
QStatusBar { background: @bg@; color: @muted@; }
QSplitter::handle { background: @bg@; }
"""
