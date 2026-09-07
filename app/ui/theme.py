"""Inkbench visual system — light/dark tokens compiled to QSS.

The app is a conversion bench for documents, not a SaaS dashboard.
Paper is uncoated stock (cool green-gray), ink is forest-black, and the
one loud color is pine — a press mark, not a generic blue button.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_UI = (
    '"Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", '
    '"SF Pro Text", "Ubuntu", "Cantarell", "Noto Sans", sans-serif'
)
FONT_MONO = (
    '"Cascadia Code", "Cascadia Mono", "SF Mono", "Menlo", '
    '"Ubuntu Mono", "Consolas", monospace'
)


@dataclass(frozen=True)
class Tokens:
    paper: str
    elevated: str
    sunken: str
    ink: str
    muted: str
    faint: str
    rule: str
    mark: str
    mark_hover: str
    mark_pressed: str
    mark_tint: str
    on_mark: str
    danger: str
    danger_hover: str
    danger_tint: str
    shadow: str


LIGHT = Tokens(
    paper="#F1F3F0",
    elevated="#FBFCFB",
    sunken="#E7EBE6",
    ink="#1A211C",
    muted="#5E6A63",
    faint="#8A948C",
    rule="#C5CEC6",
    mark="#0F6E56",
    mark_hover="#0C5A47",
    mark_pressed="#094536",
    mark_tint="#DCEBE4",
    on_mark="#F4FBF7",
    danger="#B42318",
    danger_hover="#912018",
    danger_tint="#F8E6E4",
    shadow="#0F6E56",
)

DARK = Tokens(
    paper="#101614",
    elevated="#181E1B",
    sunken="#0C110F",
    ink="#E6EDE8",
    muted="#8A968E",
    faint="#6B766F",
    rule="#2A332E",
    mark="#3DAB86",
    mark_hover="#56C49C",
    mark_pressed="#2E8A6A",
    mark_tint="#16352C",
    on_mark="#06241B",
    danger="#F97066",
    danger_hover="#FDA29B",
    danger_tint="#3B1C1A",
    shadow="#3DAB86",
)


def tokens_for(theme_name: str) -> Tokens:
    return DARK if theme_name == "dark" else LIGHT


def apply_fusion_palette(app: QApplication, theme_name: str) -> None:
    """Fusion + a matching palette so unstyled chrome (dialogs, file
    pickers) does not snap back to the native OS look."""
    t = tokens_for(theme_name)
    app.setStyle("Fusion")
    palette = QPalette()
    paper = QColor(t.paper)
    ink = QColor(t.ink)
    elevated = QColor(t.elevated)
    muted = QColor(t.muted)
    mark = QColor(t.mark)
    palette.setColor(QPalette.ColorRole.Window, paper)
    palette.setColor(QPalette.ColorRole.WindowText, ink)
    palette.setColor(QPalette.ColorRole.Base, elevated)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t.sunken))
    palette.setColor(QPalette.ColorRole.Text, ink)
    palette.setColor(QPalette.ColorRole.Button, elevated)
    palette.setColor(QPalette.ColorRole.ButtonText, ink)
    palette.setColor(QPalette.ColorRole.Highlight, mark)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_mark))
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.Link, mark)
    palette.setColor(QPalette.ColorRole.ToolTipBase, elevated)
    palette.setColor(QPalette.ColorRole.ToolTipText, ink)
    app.setPalette(palette)
    font = app.font()
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPointSize(10)
    app.setFont(font)


def _qss(t: Tokens) -> str:
    return f"""
QMainWindow, QDialog {{
    background-color: {t.paper};
    color: {t.ink};
    font-family: {FONT_UI};
    font-size: 13px;
}}
QWidget {{
    color: {t.ink};
    font-family: {FONT_UI};
}}
QMenuBar {{
    background-color: {t.paper};
    color: {t.ink};
    border-bottom: 1px solid {t.rule};
    padding: 2px 8px 0 8px;
    spacing: 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 6px;
}}
QMenuBar::item:selected {{
    background-color: {t.mark_tint};
}}
QMenu {{
    background-color: {t.elevated};
    color: {t.ink};
    border: 1px solid {t.rule};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px 7px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {t.mark_tint};
    color: {t.ink};
}}
QMenu::separator {{
    height: 1px;
    background: {t.rule};
    margin: 5px 8px;
}}

QPushButton {{
    background-color: {t.mark};
    color: {t.on_mark};
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {t.mark_hover};
}}
QPushButton:pressed {{
    background-color: {t.mark_pressed};
}}
QPushButton:disabled {{
    background-color: {t.sunken};
    color: {t.faint};
}}
QPushButton:focus {{
    outline: none;
}}
QPushButton:focus-visible {{
    border: 2px solid {t.mark};
}}

QPushButton#secondary, QPushButton#ghost {{
    background-color: transparent;
    color: {t.ink};
    border: 1px solid {t.rule};
    font-weight: 500;
}}
QPushButton#secondary:hover, QPushButton#ghost:hover {{
    background-color: {t.sunken};
    border-color: {t.muted};
}}
QPushButton#secondary:pressed, QPushButton#ghost:pressed {{
    background-color: {t.mark_tint};
}}
QPushButton#secondary:disabled, QPushButton#ghost:disabled {{
    background-color: transparent;
    color: {t.faint};
    border-color: {t.rule};
}}

QPushButton#danger {{
    background-color: transparent;
    color: {t.danger};
    border: 1px solid {t.rule};
    font-weight: 500;
}}
QPushButton#danger:hover {{
    background-color: {t.danger_tint};
    border-color: {t.danger};
}}

QPushButton#link {{
    background-color: transparent;
    color: {t.mark};
    border: none;
    padding: 4px 8px;
    font-weight: 600;
}}
QPushButton#link:hover {{
    background-color: {t.mark_tint};
}}

QPushButton#lang {{
    background-color: transparent;
    color: {t.muted};
    border: none;
    border-radius: 6px;
    padding: 4px 9px;
    font-weight: 600;
    min-width: 36px;
}}
QPushButton#lang:checked {{
    background-color: {t.mark_tint};
    color: {t.mark};
}}
QPushButton#lang:hover {{
    color: {t.ink};
}}

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background-color: {t.elevated};
    color: {t.ink};
    border: 1px solid {t.rule};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {t.mark_tint};
    selection-color: {t.ink};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {t.mark};
}}
QTextBrowser {{
    padding: 16px 18px;
}}

QTableView#QueueView {{
    background-color: transparent;
    alternate-background-color: transparent;
    border: none;
    gridline-color: transparent;
    outline: none;
    color: {t.ink};
}}
QTableView#QueueView::item {{
    background: transparent;
    border: none;
    padding: 0;
}}
QTableView#QueueView::item:selected {{
    background: transparent;
}}
QHeaderView::section {{
    background-color: transparent;
    border: none;
    height: 0;
}}

QTabWidget::pane {{
    border: 1px solid {t.rule};
    border-radius: 10px;
    background-color: {t.elevated};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.muted};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {t.elevated};
    color: {t.ink};
    font-weight: 600;
    border: 1px solid {t.rule};
    border-bottom: 1px solid {t.elevated};
}}
QTabBar::tab:hover:!selected {{
    color: {t.ink};
}}

QProgressBar {{
    border: none;
    background-color: {t.sunken};
    border-radius: 2px;
    max-height: 3px;
    min-height: 3px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {t.mark};
    border-radius: 2px;
}}

QStatusBar {{
    background-color: {t.paper};
    color: {t.muted};
    border-top: 1px solid {t.rule};
    font-size: 12px;
}}
QStatusBar::item {{
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.rule};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t.rule};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {t.rule};
    border-radius: 4px;
    background: {t.elevated};
}}
QCheckBox::indicator:checked {{
    background: {t.mark};
    border-color: {t.mark};
}}

QSplitter::handle {{
    background: {t.rule};
    width: 1px;
    margin: 8px 0;
}}
QSplitter::handle:hover {{
    background: {t.mark};
}}

QToolTip {{
    background-color: {t.elevated};
    color: {t.ink};
    border: 1px solid {t.rule};
    border-radius: 6px;
    padding: 6px 8px;
}}

#DropZone {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 14px;
}}
#DropZone[prominent="false"] {{
    background-color: {t.elevated};
    border: 1px solid {t.rule};
}}
#DropZone[dragActive="true"] {{
    border: 2px solid {t.mark};
    background-color: {t.mark_tint};
}}
#DropZoneTitle {{
    color: {t.ink};
    background: transparent;
    font-weight: 600;
}}
#DropZoneHint, #DropZoneSaveNote, #SupportedTypesLabel {{
    color: {t.muted};
    background: transparent;
}}
#FormatChip {{
    background-color: {t.sunken};
    color: {t.muted};
    border: none;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

#QueuePane, #PreviewPane {{
    background: transparent;
}}
#PreviewEmptyTitle {{
    color: {t.ink};
    background: transparent;
    font-size: 16px;
    font-weight: 600;
}}
#PreviewEmptyHint {{
    color: {t.muted};
    background: transparent;
}}

#PreviewHeader {{
    background-color: {t.elevated};
    border: 1px solid {t.rule};
    border-radius: 10px;
}}
#PreviewHeaderName {{
    background: transparent;
    color: {t.ink};
    font-weight: 600;
}}
#PreviewHeaderStatus {{
    background: transparent;
    color: {t.muted};
}}
#PreviewHeaderStatus[kind="saved"] {{
    color: {t.mark};
    font-weight: 600;
}}
#PreviewHeaderStatus[kind="error"] {{
    color: {t.danger};
    font-weight: 600;
}}
#PreviewHeaderStatus[kind="converting"] {{
    color: {t.mark};
    font-weight: 600;
}}

#LanguageSwitch {{
    background: transparent;
}}
"""


def stylesheet_for(theme_name: str) -> str:
    """Return the QSS string for 'light' or 'dark'; defaults to light."""
    return _qss(tokens_for(theme_name))
