"""Light and dark QSS stylesheets for the application."""
from __future__ import annotations

LIGHT_QSS = """
QWidget {
    background-color: #f5f6f8;
    color: #1d1f21;
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog {
    background-color: #f5f6f8;
}
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #dcdfe4;
}
QMenuBar::item:selected {
    background-color: #e4e8ef;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #dcdfe4;
}
QMenu::item:selected {
    background-color: #d7e4fb;
}
QGroupBox {
    border: 1px solid #d7dade;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #2f6fed;
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #4a82f0;
}
QPushButton:pressed {
    background-color: #1f56c4;
}
QPushButton:disabled {
    background-color: #b6c3dc;
    color: #eef1f7;
}
QPushButton#secondary {
    background-color: #e4e8ef;
    color: #1d1f21;
}
QPushButton#secondary:hover {
    background-color: #d3d9e3;
}
QPushButton#danger {
    background-color: #d64545;
}
QPushButton#danger:hover {
    background-color: #e05a5a;
}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {
    background-color: #ffffff;
    border: 1px solid #cfd4db;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #a9c6fb;
}
QTableView {
    background-color: #ffffff;
    alternate-background-color: #f0f2f5;
    gridline-color: #e2e5ea;
    border: 1px solid #d7dade;
}
QHeaderView::section {
    background-color: #eceff3;
    padding: 4px;
    border: none;
    border-bottom: 1px solid #d7dade;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #d7dade;
    border-radius: 4px;
}
QTabBar::tab {
    background: #e9ecf1;
    padding: 6px 14px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background: #ffffff;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #cfd4db;
    border-radius: 4px;
    text-align: center;
    background-color: #ffffff;
}
QProgressBar::chunk {
    background-color: #2f6fed;
    border-radius: 3px;
}
#DropZone {
    border: 2px dashed #9aa7bd;
    border-radius: 8px;
    background-color: #eceff3;
}
#DropZone:hover {
    border-color: #2f6fed;
    background-color: #e4ebfa;
}
#DropZone[dragActive="true"] {
    border-color: #2f6fed;
    background-color: #e9f0ff;
}
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #dcdfe4;
}
#SupportedTypesLabel {
    color: #6b7280;
}
"""

DARK_QSS = """
QWidget {
    background-color: #1e2126;
    color: #e6e8eb;
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog {
    background-color: #1e2126;
}
QMenuBar {
    background-color: #26292f;
    border-bottom: 1px solid #34383f;
}
QMenuBar::item:selected {
    background-color: #343941;
}
QMenu {
    background-color: #26292f;
    border: 1px solid #34383f;
}
QMenu::item:selected {
    background-color: #2f4d82;
}
QGroupBox {
    border: 1px solid #34383f;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #3d7bf5;
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #5a90f7;
}
QPushButton:pressed {
    background-color: #2f5fc9;
}
QPushButton:disabled {
    background-color: #3a4250;
    color: #7c8697;
}
QPushButton#secondary {
    background-color: #343941;
    color: #e6e8eb;
}
QPushButton#secondary:hover {
    background-color: #3f454f;
}
QPushButton#danger {
    background-color: #b8433f;
}
QPushButton#danger:hover {
    background-color: #cc524d;
}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {
    background-color: #26292f;
    border: 1px solid #3a3f47;
    border-radius: 4px;
    padding: 4px;
    color: #e6e8eb;
    selection-background-color: #2f5fc9;
}
QTableView {
    background-color: #22252b;
    alternate-background-color: #26292f;
    gridline-color: #34383f;
    border: 1px solid #34383f;
    color: #e6e8eb;
}
QHeaderView::section {
    background-color: #2a2e35;
    padding: 4px;
    border: none;
    border-bottom: 1px solid #34383f;
    font-weight: 600;
    color: #e6e8eb;
}
QTabWidget::pane {
    border: 1px solid #34383f;
    border-radius: 4px;
}
QTabBar::tab {
    background: #26292f;
    padding: 6px 14px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #c7cbd1;
}
QTabBar::tab:selected {
    background: #1e2126;
    font-weight: 600;
    color: #ffffff;
}
QProgressBar {
    border: 1px solid #3a3f47;
    border-radius: 4px;
    text-align: center;
    background-color: #26292f;
}
QProgressBar::chunk {
    background-color: #3d7bf5;
    border-radius: 3px;
}
#DropZone {
    border: 2px dashed #4a505b;
    border-radius: 8px;
    background-color: #292d34;
}
#DropZone:hover {
    border-color: #3d7bf5;
    background-color: #232833;
}
#DropZone[dragActive="true"] {
    border-color: #3d7bf5;
    background-color: #1f2b40;
}
QStatusBar {
    background-color: #26292f;
    border-top: 1px solid #34383f;
}
#SupportedTypesLabel {
    color: #9aa3b0;
}
"""


def stylesheet_for(theme_name: str) -> str:
    """Return the QSS string for 'light' or 'dark'; defaults to light."""
    return DARK_QSS if theme_name == "dark" else LIGHT_QSS
