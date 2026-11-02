"""Ink on paper, and one highlighter: light/dark tokens compiled to QSS.

Every neutral is a dilution of the blue-black ink. `mark` is the only color,
and it sits on exactly what the person is working on: the instruction on an
empty window, the selected row, selected text, the window while a file is held
over it, and a focused primary action. Saved has no green and failure is the
only other hue. See `tests/test_theme_contrast.py` for the checked pairings.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_UI = (
    '"Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", '
    '".AppleSystemUIFont", "SF Pro Text", "Ubuntu", "Cantarell", '
    '"Noto Sans", "DejaVu Sans", sans-serif'
)
# Raw Markdown only: there the monospace is the content, not a decoration.
MONO_FAMILIES = (
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "SF Mono",
    "Menlo",
    "Ubuntu Mono",
    "DejaVu Sans Mono",
)
FONT_MONO = ", ".join(f'"{family}"' for family in MONO_FAMILIES) + ", monospace"

# Rendered Markdown stops growing at a comfortable reading measure.
READING_WIDTH = 720


@dataclass(frozen=True)
class Tokens:
    paper: str  # the document sheet
    desk: str  # list pane, menu bar, status bar
    wash: str  # quiet control fill, row hover
    wash_strong: str  # quiet control hover and pressed
    rule: str  # structural hairlines only
    edge: str  # control boundaries, 3:1 against paper and desk
    ink: str  # text, primary action fill, focus ring
    muted: str  # secondary text
    primary_fg: str
    primary_hover: str
    primary_pressed: str
    mark: str  # the highlighter
    on_mark: str
    on_mark_muted: str
    on_mark_danger: str
    danger: str  # failure only


LIGHT = Tokens(
    paper="#FFFFFF",
    desk="#EEF0F4",
    wash="#E2E5EC",
    wash_strong="#D3D8E2",
    rule="#D5D9E2",
    edge="#7A8498",
    ink="#14213D",
    muted="#4A5568",
    primary_fg="#FFFFFF",
    primary_hover="#24345A",
    primary_pressed="#0E1830",
    mark="#FFE84D",
    on_mark="#14213D",
    on_mark_muted="#3F4A5E",
    on_mark_danger="#A1170F",
    danger="#B3261E",
)

DARK = Tokens(
    paper="#232936",
    desk="#1A1F2B",
    wash="#2E3544",
    wash_strong="#3A4254",
    rule="#343B4B",
    edge="#78839A",
    ink="#EEF0F5",
    muted="#AEB6C6",
    primary_fg="#1A1F2B",
    primary_hover="#FFFFFF",
    primary_pressed="#CBD0DB",
    mark="#F5DC4A",
    on_mark="#1A1F2B",
    on_mark_muted="#40485A",
    on_mark_danger="#A1170F",
    danger="#FF9C8F",
)


def tokens_for(theme_name: str) -> Tokens:
    return DARK if theme_name == "dark" else LIGHT


def apply_fusion_palette(app: QApplication, theme_name: str) -> None:
    """Fusion + a matching palette so unstyled chrome (dialogs, file
    pickers) does not snap back to the native OS look."""
    t = tokens_for(theme_name)
    app.setStyle("Fusion")
    # This constructor derives the bevel roles Fusion draws checkboxes with.
    palette = QPalette(QColor(t.wash), QColor(t.paper))
    ink = QColor(t.ink)
    muted = QColor(t.muted)
    palette.setColor(QPalette.ColorRole.Window, QColor(t.desk))
    palette.setColor(QPalette.ColorRole.WindowText, ink)
    palette.setColor(QPalette.ColorRole.Base, QColor(t.paper))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t.desk))
    palette.setColor(QPalette.ColorRole.Text, ink)
    palette.setColor(QPalette.ColorRole.ButtonText, ink)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t.mark))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_mark))
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.Link, ink)
    palette.setColor(QPalette.ColorRole.LinkVisited, ink)
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.paper))
    palette.setColor(QPalette.ColorRole.ToolTipText, ink)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    app.setPalette(palette)
    font = app.font()
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)


def _qss(t: Tokens) -> str:
    return f"""
QWidget {{
    color: {t.ink};
    font-family: {FONT_UI};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {t.desk};
}}

QMenuBar {{
    background-color: {t.desk};
    border-bottom: 1px solid {t.rule};
    padding: 1px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 9px;
}}
QMenuBar::item:selected {{
    background-color: {t.wash};
}}
QMenu {{
    background-color: {t.paper};
    border: 1px solid {t.edge};
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 28px 6px 16px;
}}
QMenu::item:selected {{
    background-color: {t.wash};
}}
QMenu::item:disabled {{
    color: {t.muted};
}}
QMenu::separator {{
    height: 1px;
    background: {t.rule};
    margin: 4px 0;
}}

QPushButton {{
    background-color: {t.wash};
    border: 2px solid transparent;
    border-radius: 4px;
    padding: 4px 12px;
    outline: none;
}}
QPushButton:hover, QPushButton:pressed {{
    background-color: {t.wash_strong};
}}
QPushButton:focus {{
    border-color: {t.ink};
}}
QPushButton:disabled {{
    background-color: transparent;
    color: {t.muted};
}}
QPushButton::menu-indicator {{
    image: none;
    width: 0;
}}

QPushButton[tier="primary"], QDialogButtonBox QPushButton:default {{
    background-color: {t.ink};
    color: {t.primary_fg};
    font-weight: 600;
}}
QPushButton[tier="primary"]:hover, QDialogButtonBox QPushButton:default:hover {{
    background-color: {t.primary_hover};
}}
QPushButton[tier="primary"]:pressed, QDialogButtonBox QPushButton:default:pressed {{
    background-color: {t.primary_pressed};
}}
QPushButton[tier="primary"]:focus, QDialogButtonBox QPushButton:default:focus {{
    background-color: {t.mark};
    color: {t.on_mark};
    border-color: {t.on_mark};
}}

QPushButton[tier="ghost"] {{
    background-color: transparent;
    padding: 4px 8px;
}}
QPushButton[tier="ghost"]:hover, QPushButton[tier="ghost"]:pressed {{
    background-color: {t.wash};
}}

QPushButton#lang {{
    background-color: transparent;
    color: {t.muted};
    border-radius: 0;
    padding: 2px 6px;
}}
QPushButton#lang:hover {{
    color: {t.ink};
}}
QPushButton#lang:checked {{
    color: {t.ink};
    font-weight: 600;
    border-bottom-color: {t.ink};
}}
QPushButton#lang:focus {{
    border-color: {t.ink};
}}

QLineEdit {{
    background-color: {t.paper};
    border: 1px solid {t.edge};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {t.mark};
    selection-color: {t.on_mark};
}}
QLineEdit:focus {{
    border: 2px solid {t.ink};
    padding: 4px 7px;
}}
QLineEdit:disabled {{
    background-color: {t.desk};
    color: {t.muted};
}}

QPlainTextEdit, QTextBrowser {{
    background-color: {t.paper};
    border: 2px solid transparent;
    padding: 14px 22px;
    selection-background-color: {t.mark};
    selection-color: {t.on_mark};
}}
QPlainTextEdit:focus, QTextBrowser:focus {{
    border-color: {t.ink};
}}

QTableView#QueueView {{
    background-color: {t.desk};
    border: none;
    outline: none;
}}

QTabWidget::pane {{
    border: none;
    border-top: 1px solid {t.rule};
    top: -1px;
}}
QTabWidget::tab-bar {{
    left: 18px;
}}
QTabBar {{
    outline: none;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.muted};
    padding: 6px 6px;
    margin-right: 10px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {t.ink};
}}
QTabBar::tab:selected {{
    color: {t.ink};
    font-weight: 600;
    border-bottom: 2px solid {t.ink};
}}
QTabBar::tab:focus {{
    background: {t.wash};
}}

QProgressBar {{
    border: none;
    background-color: {t.wash};
    max-height: 2px;
    min-height: 2px;
}}
QProgressBar::chunk {{
    background-color: {t.ink};
}}

QStatusBar {{
    background-color: {t.desk};
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
    margin: 0 1px;
}}
QScrollBar::handle:vertical {{
    background: {t.edge};
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 1px 0;
}}
QScrollBar::handle:horizontal {{
    background: {t.edge};
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t.muted};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}

QCheckBox {{
    border: 2px solid transparent;
    padding: 1px 2px;
    spacing: 8px;
}}
QCheckBox:focus {{
    border-color: {t.ink};
    outline: none;
}}

QSplitter::handle {{
    background: {t.rule};
}}
QSplitter::handle:hover {{
    background: {t.edge};
}}

QToolTip {{
    background-color: {t.paper};
    color: {t.ink};
    border: 1px solid {t.edge};
    padding: 4px 6px;
}}

#QueuePane, #LanguageSwitch {{
    background: {t.desk};
}}
#QueuePane[empty="true"], #DropZone[prominent="true"] {{
    background: {t.paper};
}}
#PreviewPane {{
    background: {t.paper};
}}
#DropZone[prominent="false"] {{
    background: {t.desk};
}}

#DropZoneTitle {{
    background: {t.mark};
    color: {t.on_mark};
    font-size: 30px;
    font-weight: 600;
    padding: 4px 12px;
}}
#DropZoneHint {{
    background: transparent;
    font-size: 15px;
}}
#DropZoneLabel {{
    background: transparent;
    font-weight: 600;
}}
#DropZoneFormats {{
    background: transparent;
    color: {t.muted};
}}
#DragOverlay {{
    background: {t.mark};
    color: {t.on_mark};
    font-size: 30px;
    font-weight: 600;
}}

#PreviewHeaderName {{
    background: transparent;
    font-size: 18px;
    font-weight: 600;
}}
#PreviewHeaderStatus {{
    background: transparent;
    color: {t.muted};
}}
#PreviewHeaderStatus[kind="error"] {{
    color: {t.danger};
    font-weight: 600;
}}
#PreviewHeaderStatus[kind="saved"], #PreviewHeaderStatus[kind="converting"] {{
    color: {t.ink};
}}
#PreviewEmptyTitle {{
    background: transparent;
    font-weight: 600;
}}
#PreviewEmptyHint {{
    background: transparent;
    color: {t.muted};
}}
"""


def stylesheet_for(theme_name: str) -> str:
    """Return the QSS string for 'light' or 'dark'; defaults to light."""
    return _qss(tokens_for(theme_name))


def document_css_for(theme_name: str) -> str:
    """Default stylesheet for rendered Markdown in the preview."""
    t = tokens_for(theme_name)
    return f"""
a {{ color: {t.ink}; text-decoration: underline; }}
h1, h2, h3, h4 {{ color: {t.ink}; font-weight: 600; }}
code, pre {{ font-family: {FONT_MONO}; background-color: {t.desk}; }}
th {{ font-weight: 600; }}
"""
