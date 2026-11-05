"""Main application window for MarkItDown Desktop."""
from __future__ import annotations

import ntpath
import os
import re
import subprocess
import sys
import webbrowser

import markdown as markdown_lib
from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QRect,
    QSettings,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.conversion_queue import ConversionQueue
from app.core.converter import (
    ConversionOptions,
    classify_paths,
    classify_save_error,
    default_basename,
    export_markdown,
    get_downloads_dir,
    supported_name_filter,
)
from app.core.queue_model import (
    COLUMN_STATUS,
    COLUMN_TYPE,
    RETRY_STATES,
    DisplayState,
    FailureReason,
    ItemStatus,
    QueueItem,
    QueueTableModel,
    failure_reason_text,
)
from app.i18n import LANG_EN, LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.about_dialog import AboutDialog
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog
from app.ui.brand_mark import BrandMark
from app.ui.drop_zone import EMPTY_GUTTER, DropZone, center_column, empty_column_left
from app.ui.preview_browser import PreviewBrowser
from app.ui.queue_delegate import ROW_HEIGHT, QueueItemDelegate
from app.ui.queue_text import detail_status, queue_summary
from app.ui.status_mark import StatusMark
from app.ui.theme import (
    PREVIEW_MARGIN,
    READING_WIDTH,
    apply_fusion_palette,
    document_css_for,
    needs_full_width,
    preview_html,
    set_tier,
    stylesheet_for,
)

ORG_NAME = "andres"
APP_NAME = "MarkItDownDesktop"

# Preview header per state: the stylesheet `kind` property.
_HEADER_KIND = {
    DisplayState.PENDING: "pending",
    DisplayState.CONVERTING: "converting",
    DisplayState.DONE: "pending",
    DisplayState.SAVED: "saved",
    DisplayState.SAVE_FAILED: "error",
    DisplayState.ERROR: "error",
}

_SPINNER_INTERVAL_MS = 90
_COPY_FEEDBACK_MS = 1500
_LIST_WIDTH = 340
_PANE_MARGIN = 24
_PROGRESS_HEIGHT = 2
_ERROR_DETAIL_CHARS = 1200
# The empty screen is one short column; the list and preview need real room.
COMPACT_WINDOW_SIZE = (760, 500)
WORKING_WINDOW_SIZE = (1180, 780)

_BRAND_MARGINS_EMPTY = (EMPTY_GUTTER, 18, EMPTY_GUTTER, 0)
# Centers the mark on the state marks below and starts the name on their text edge.
_BRAND_MARGINS_FILLED = (12, 14, 14, 10)
# Fits a headline and a detail line, so rows never shift when one goes away.
_SUMMARY_HEIGHT = 46

# Characters of Markdown the preview renders. Measured on a narrow table, the worst
# case found: 50,000 characters take about 0.5 s, 100,000 about 2 s and the whole
# 739 KB of a 50,000-row table about 24 s, since the cost grows faster than the size.
# The same amount of prose takes 0.02 s.
PREVIEW_CHAR_LIMIT = 50_000
# Long enough to span the gap between keystrokes, short enough to feel live.
_RENDER_DEBOUNCE_MS = 200


def _save_failure_text(reason: FailureReason, detail: str) -> str:
    """For a message box, which has room for the system's words after the reason."""
    return f"{tr(reason.value)} ({detail})"


def heading_anchor(heading: str, separator: str) -> str:
    """The name a heading goes by, as GitHub makes it, which is what links in Markdown
    mostly follow: `Credits & License` is `credits--license`, and accents stay."""
    name = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return name.replace(" ", separator)


# `toc` only for the ids it gives headings, which QTextBrowser takes as anchors. An empty
# marker stops it turning a literal `[TOC]` in converted text into a contents list.
_MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "tables", "toc"]
_MARKDOWN_EXTENSION_CONFIGS = {"toc": {"marker": "", "slugify": heading_anchor}}


def preview_excerpt(text: str) -> str:
    """As much of `text` as the preview renders, ending at a line boundary if it has one."""
    if len(text) <= PREVIEW_CHAR_LIMIT:
        return text
    line_end = text.rfind("\n", 0, PREVIEW_CHAR_LIMIT)
    return text[: line_end + 1] if line_end >= 0 else text[:PREVIEW_CHAR_LIMIT]


def reveal_command(path: str) -> str | list[str]:
    """The command that shows `path` in the system's file manager, for `Popen`.

    No shell ever sees it, so `%VAR%` and `&` in a file name stay literal. Windows
    gets one string because `Popen` passes a string to CreateProcess unchanged,
    and Explorer needs the `/select,"<path>"` quoting that a list would not produce.
    The full path is there because CreateProcess looks for a bare name in the
    current folder first.
    """
    if sys.platform.startswith("win"):
        system_root = os.environ.get("SystemRoot")
        explorer = ntpath.join(system_root, "explorer.exe") if system_root else "explorer"
        return f'{explorer} /select,"{path}"'
    if sys.platform == "darwin":
        return ["open", "-R", path]
    return ["xdg-open", os.path.dirname(path)]


def palette_theme() -> str:
    """Light or dark, read from the current QPalette.

    Only meaningful before `apply_fusion_palette` replaces that palette with
    the app's own, which is why the window reads it once, at launch.
    """
    palette = QGuiApplication.palette()
    window_color = palette.color(palette.ColorRole.Window)
    luminance = 0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
    return "dark" if luminance < 128 else "light"


def detect_system_theme(fallback: str = "light") -> str:
    """Ask the system for light or dark; `fallback` when it has no answer."""
    # colorScheme() arrived in Qt 6.5, and requirements.txt does not pin Qt.
    color_scheme = getattr(QGuiApplication.styleHints(), "colorScheme", None)
    if color_scheme is None:
        return fallback
    scheme = color_scheme()
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    return fallback


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        i18n_manager.init_from_settings(self.settings)
        i18n_manager.language_changed.connect(self._on_language_changed)

        self.setWindowTitle(tr("window.title"))
        self.resize(*COMPACT_WINDOW_SIZE)
        # Height only: an explicit width would override the layout's minimum
        # and clip the action row in longer languages or larger fonts.
        self.setMinimumHeight(COMPACT_WINDOW_SIZE[1])
        self._showing_empty = True

        self._preview_item: QueueItem | None = None
        self._preview_full_width = False
        self._launch_theme = palette_theme()

        self.conversion_options = ConversionOptions()

        self.model = QueueTableModel(self)
        self.conversion_queue = ConversionQueue(self.model, parent=self)
        self.conversion_queue.item_started.connect(self._on_item_started)
        self.conversion_queue.item_finished.connect(self._on_item_finished)
        self.conversion_queue.item_failed.connect(self._on_item_failed)
        self.conversion_queue.item_saved.connect(self._on_item_saved)
        self.conversion_queue.item_save_failed.connect(self._on_item_save_failed)
        self.conversion_queue.batch_started.connect(self._on_batch_started)
        self.conversion_queue.progress_changed.connect(self._on_progress_changed)
        self.conversion_queue.batch_finished.connect(self._on_batch_finished)

        self._spinner = QTimer(self)
        self._spinner.setInterval(_SPINNER_INTERVAL_MS)
        self._spinner.timeout.connect(self._advance_spinner)
        self._copy_feedback = QTimer(self)
        self._copy_feedback.setSingleShot(True)
        self._copy_feedback.setInterval(_COPY_FEEDBACK_MS)
        self._copy_feedback.timeout.connect(self._restore_copy_label)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_RENDER_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._on_raw_edit_settled)

        self._build_ui()
        self._build_menu()
        self._build_language_switcher()
        self._install_shortcuts()
        self._restore_settings()
        self._apply_theme(self._current_theme_name())
        self._follow_system_theme_changes()
        self._update_drop_zone_prominence()
        self.centralWidget().setFocus()

    def _build_ui(self) -> None:
        central = QWidget()
        # Holds focus on launch and after clicking empty space, so a focus ring
        # only appears once the keyboard moves it.
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.left_panel = self._build_left_panel()
        self.preview_panel = self._build_right_panel()
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([_LIST_WIDTH, 840])

        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)
        # What the strip says at rest. Messages cover it for a moment, then it returns.
        self.saving_to_label = QLabel()
        self.saving_to_label.setObjectName("SavingTo")
        self.saving_to_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_bar.addWidget(self.saving_to_label, 1)
        self._retranslate_saving_to()

        # Floats over the panes, so a batch starting never shifts the layout.
        self.progress_bar = QProgressBar(central)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)

        self.drag_overlay = QLabel(tr("overlay.drop"), central)
        self.drag_overlay.setObjectName("DragOverlay")
        self.drag_overlay.setIndent(56)
        self.drag_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Transparent to the drag as well, so the drop lands on the panes below.
        self.drag_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.drag_overlay.setVisible(False)
        self.drop_zone.drag_active_changed.connect(self._on_drag_active_changed)
        central.installEventFilter(self)
        self.table_view.installEventFilter(self)
        self.preview_panel.installEventFilter(self)
        self.rendered_view.viewport().installEventFilter(self)

        # The window itself catches the menu bar, status bar and everything
        # that has no drop handling. The rest would refuse the drag themselves.
        self.drop_zone.accept_drops_on(
            self,
            self.left_panel,
            self.preview_panel,
            self.table_view.viewport(),
            self.rendered_view.viewport(),
            self.raw_view.viewport(),
            self.url_edit,
        )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            if watched is self.centralWidget():
                self.drag_overlay.setGeometry(watched.rect())
                self.drag_overlay.setIndent(empty_column_left(watched.width(), self.drop_zone.column_width()))
                self.progress_bar.setGeometry(0, 0, watched.width(), _PROGRESS_HEIGHT)
            elif watched is self.preview_panel:
                self._fit_preview_title()
            elif watched is self.rendered_view.viewport():
                self._fit_reading_width()
        elif (
            watched is self.table_view
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._retry_focused_row()
        ):
            return True
        return super().eventFilter(watched, event)

    def _retry_focused_row(self) -> bool:
        """The row's Retry, for the keyboard: Enter acts on the row with the focus ring."""
        row = self.table_view.currentIndex().row()
        item = self.model.item_at(row)
        if item is None or item.display_state not in RETRY_STATES:
            return False
        self._start_conversion([row])
        return True

    def _on_drag_active_changed(self, active: bool) -> None:
        self.drag_overlay.setGeometry(self.centralWidget().rect())
        self.drag_overlay.setVisible(active)
        if active:
            self.drag_overlay.raise_()

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("QueuePane")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setMinimumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.drop_zone = DropZone(
            self._on_paths_dropped,
            on_click=self.action_add_files,
            on_url=self.action_add_url,
            on_folder=self.action_add_folder,
        )
        self.url_edit = self.drop_zone.url_edit

        layout.addLayout(self._build_brand_row())
        layout.addWidget(self._build_queue_summary())

        self.table_view = QTableView()
        self.table_view.setObjectName("QueueView")
        self.table_view.setAccessibleName(tr("a11y.queue"))
        self.table_view.setModel(self.model)
        self.table_view.setShowGrid(False)
        self.table_view.setAlternatingRowColors(False)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue_delegate = QueueItemDelegate(self.table_view)
        self.table_view.setItemDelegate(self.queue_delegate)
        self.table_view.horizontalHeader().setVisible(False)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setColumnHidden(COLUMN_TYPE, True)
        self.table_view.setColumnHidden(COLUMN_STATUS, True)
        self.table_view.horizontalHeader().setSectionResizeMode(0, self.table_view.horizontalHeader().ResizeMode.Stretch)
        self.table_view.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table_view.setMouseTracking(True)
        self.table_view.setWordWrap(False)
        self.table_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Tab moves to the next control; the arrow keys move between rows.
        self.table_view.setTabKeyNavigation(False)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_queue_menu)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        self.queue_delegate.retry_requested.connect(lambda row: self._start_conversion([row]))
        layout.addWidget(self.table_view, 1)
        # Every way to add something sits together below the list; above it, the
        # name and the answer. An empty window gives the whole pane to this zone.
        layout.addWidget(self.drop_zone, 1)

        self.queue_controls_widget = QWidget()
        queue_controls_layout = QHBoxLayout(self.queue_controls_widget)
        # With a ghost button's padding, the labels land on the pane's 14px edges.
        queue_controls_layout.setContentsMargins(4, 0, 4, 8)
        queue_controls_layout.setSpacing(2)
        self.add_files_btn = QPushButton(tr("button.add_files"))
        self.add_files_btn.clicked.connect(self.action_add_files)
        self.clear_btn = QPushButton(tr("button.clear_all"))
        self.clear_btn.clicked.connect(self.action_clear_all)
        for button in (self.add_files_btn, self.clear_btn):
            set_tier(button, "ghost")
        queue_controls_layout.addWidget(self.add_files_btn)
        queue_controls_layout.addStretch(1)
        queue_controls_layout.addWidget(self.clear_btn)
        layout.addWidget(self.queue_controls_widget)

        for signal in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            signal.connect(self._update_drop_zone_prominence)
        for signal in (self.model.dataChanged, self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            signal.connect(self._sync_spinner)
            signal.connect(self._refresh_queue_summary)

        return panel

    def _build_brand_row(self) -> QHBoxLayout:
        self._brand_row = QHBoxLayout()
        self._brand_row.setSpacing(0)
        self._brand_column = QWidget()
        column = QHBoxLayout(self._brand_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.brand_mark = BrandMark()
        self.brand_name = QLabel(tr("window.title"))
        self.brand_name.setObjectName("BrandName")
        column.addWidget(self.brand_mark)
        column.addWidget(self.brand_name)
        column.addStretch(1)
        self._brand_row.addStretch(1)
        self._brand_row.addWidget(self._brand_column, 10)
        self._brand_row.addStretch(1)
        return self._brand_row

    def _build_queue_summary(self) -> QWidget:
        self.queue_summary = QWidget()
        self.queue_summary.setFixedHeight(_SUMMARY_HEIGHT)
        row = QHBoxLayout(self.queue_summary)
        row.setContentsMargins(14, 0, 14, 8)
        row.setSpacing(10)
        self.summary_mark = StatusMark()
        self.summary_headline = QLabel()
        self.summary_headline.setObjectName("SummaryHeadline")
        self.summary_detail = QLabel()
        self.summary_detail.setObjectName("SummaryDetail")
        for label in (self.summary_headline, self.summary_detail):
            # The pane sets the width; the full line is also the tooltip.
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(self.summary_headline)
        text.addWidget(self.summary_detail)
        text.addStretch(1)
        mark_column = QVBoxLayout()
        mark_column.setContentsMargins(0, 1, 0, 0)
        mark_column.addWidget(self.summary_mark)
        mark_column.addStretch(1)
        row.addLayout(mark_column)
        row.addLayout(text, 1)
        self.queue_summary.setVisible(False)
        return self.queue_summary

    def _refresh_queue_summary(self, *args) -> None:
        summary = queue_summary(self.model.items())
        self.queue_summary.setVisible(summary is not None)
        if summary is None:
            return
        self.summary_mark.set_glyph(summary.glyph, summary.attention)
        self.summary_headline.setText(summary.headline)
        self.summary_detail.setText(summary.detail)
        self.queue_summary.setToolTip(", ".join(part for part in (summary.headline, summary.detail) if part))
        if self.summary_headline.property("attention") != summary.attention:
            self.summary_headline.setProperty("attention", summary.attention)
            self.summary_headline.style().unpolish(self.summary_headline)
            self.summary_headline.style().polish(self.summary_headline)

    def _retranslate_saving_to(self) -> None:
        path = str(get_downloads_dir())
        self.saving_to_label.setText(tr("statusbar.saving_to", path=path))
        self.saving_to_label.setToolTip(path)

    def _update_drop_zone_prominence(self, *args) -> None:
        empty = len(self.model.items()) == 0
        leaving_work = empty and not self._showing_empty
        if leaving_work:
            self._remember_working_size()
        self.drop_zone.set_prominent(empty)
        self._brand_row.setContentsMargins(*(_BRAND_MARGINS_EMPTY if empty else _BRAND_MARGINS_FILLED))
        center_column(self._brand_row, self._brand_column, empty, self.drop_zone.column_width())
        self.left_panel.setProperty("empty", empty)
        self.left_panel.style().unpolish(self.left_panel)
        self.left_panel.style().polish(self.left_panel)
        self.table_view.setVisible(not empty)
        self.queue_controls_widget.setVisible(not empty)
        self.preview_panel.setVisible(not empty)
        self.status_bar.setVisible(not empty)
        self.clear_action.setEnabled(not empty)
        if empty != self._showing_empty:
            self._showing_empty = empty
            self._apply_window_size(empty)
        if empty:
            self._update_preview_header(None)
            self._show_preview_empty("", "")

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("PreviewPane")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.preview_header = QWidget()
        self.preview_header.setObjectName("PreviewHeader")
        self.preview_header.setVisible(False)
        header = QVBoxLayout(self.preview_header)
        header.setContentsMargins(_PANE_MARGIN, 16, _PANE_MARGIN, 12)
        header.setSpacing(2)
        self.preview_header_name = QLabel()
        self.preview_header_name.setObjectName("PreviewHeaderName")
        # Elided to the pane by hand; a long unbroken name must not widen it.
        self.preview_header_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.preview_header_status = QLabel()
        self.preview_header_status.setObjectName("PreviewHeaderStatus")
        self.preview_header_status.setWordWrap(True)
        self.preview_header_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_policy.setHeightForWidth(True)
        self.preview_header_status.setSizePolicy(status_policy)
        header.addWidget(self.preview_header_name)
        header.addWidget(self.preview_header_status)
        header.addSpacing(10)

        header_actions = QHBoxLayout()
        header_actions.setSpacing(6)
        self.copy_btn = QPushButton(tr("button.copy_raw"))
        self.copy_btn.clicked.connect(self.action_copy_raw)
        self.open_file_btn = QPushButton(tr("button.open_file"))
        self.open_file_btn.clicked.connect(self._open_preview_file)
        self.reveal_btn = QPushButton(tr("button.open_folder"))
        self.reveal_btn.clicked.connect(self._reveal_preview_file)
        self.retry_header_btn = QPushButton(tr("menu.retry"))
        self.retry_header_btn.clicked.connect(self.action_convert_selected)
        self.more_btn = QPushButton(tr("button.more"))
        set_tier(self.more_btn, "ghost")
        # The primary sits first whichever it is, so the eye always lands there.
        header_actions.addWidget(self.retry_header_btn)
        header_actions.addWidget(self.copy_btn)
        header_actions.addWidget(self.open_file_btn)
        header_actions.addWidget(self.reveal_btn)
        header_actions.addStretch(1)
        header_actions.addWidget(self.more_btn)
        header.addLayout(header_actions)
        layout.addWidget(self.preview_header)

        self.preview_empty = QWidget()
        empty_layout = QVBoxLayout(self.preview_empty)
        empty_layout.setContentsMargins(_PANE_MARGIN, 16, _PANE_MARGIN, _PANE_MARGIN)
        empty_layout.setSpacing(4)
        self.preview_empty_title = QLabel()
        self.preview_empty_title.setObjectName("PreviewEmptyTitle")
        self.preview_empty_title.setWordWrap(True)
        self.preview_empty_hint = QLabel()
        self.preview_empty_hint.setObjectName("PreviewEmptyHint")
        self.preview_empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.preview_empty_title)
        empty_layout.addWidget(self.preview_empty_hint)
        empty_layout.addSpacing(12)
        # The header gives the one line that matters; this is the rest of it.
        self.preview_error_detail = QLabel()
        self.preview_error_detail.setObjectName("PreviewErrorDetail")
        self.preview_error_detail.setWordWrap(True)
        self.preview_error_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_error_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_error_detail.setVisible(False)
        empty_layout.addWidget(self.preview_error_detail)
        empty_layout.addStretch(1)

        self.preview_body = QWidget()
        body_layout = QVBoxLayout(self.preview_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.rendered_view = PreviewBrowser()
        self.rendered_view.document().setDocumentMargin(PREVIEW_MARGIN)
        self.rendered_view.document().setIndentWidth(PREVIEW_MARGIN)
        self.rendered_view.setLineWrapMode(PreviewBrowser.LineWrapMode.FixedPixelWidth)
        self.rendered_view.setLineWrapColumnOrWidth(READING_WIDTH)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        self.raw_view.document().setDocumentMargin(PREVIEW_MARGIN)
        self.raw_view.textChanged.connect(self._on_raw_text_changed)
        self.tabs.addTab(self.rendered_view, tr("tab.rendered"))
        self.tabs.addTab(self.raw_view, tr("tab.raw"))
        body_layout.addWidget(self.tabs, 1)

        layout.addWidget(self.preview_empty, 1)
        layout.addWidget(self.preview_body, 1)
        self.preview_body.setVisible(False)

        return panel

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        self.file_menu = menu_bar.addMenu(tr("menu.file"))
        self.add_files_action = self._make_action("menu.add_files", self.action_add_files)
        self.add_files_action.setShortcut(QKeySequence.StandardKey.Open)
        self.add_folder_action = self._make_action("menu.add_folder", self.action_add_folder)
        self.add_url_action = self._make_action("menu.add_url", lambda: self.url_edit.setFocus())
        self.open_file_action = self._make_action("menu.open_file", self._open_preview_file)
        self.reveal_action = self._make_action("menu.open_folder", self._reveal_preview_file)
        self.save_copy_action = self._make_action("menu.save_copy_as", self.action_save_current)
        self.export_all_action = self._make_action("menu.export_all_to", self.action_export_all)
        self.exit_action = self._make_action("menu.exit", self.close)
        # Not StandardKey.Quit: on Windows that is the literal Exit key, shown as "Exit".
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.file_menu.addAction(self.add_files_action)
        self.file_menu.addAction(self.add_folder_action)
        self.file_menu.addAction(self.add_url_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.open_file_action)
        self.file_menu.addAction(self.reveal_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.save_copy_action)
        self.file_menu.addAction(self.export_all_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = menu_bar.addMenu(tr("menu.edit"))
        self.copy_action = self._make_action("button.copy_raw", self.action_copy_raw)
        self.copy_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.retry_action = self._make_action("menu.retry", self.action_convert_selected)
        self.remove_action = self._make_action("menu.remove", self.action_remove_selected)
        self.clear_action = self._make_action("button.clear_all", self.action_clear_all)
        self.advanced_settings_action = self._make_action("menu.advanced_settings", self._show_advanced_settings)
        self.edit_menu.addAction(self.copy_action)
        self.edit_menu.addAction(self.retry_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.remove_action)
        self.edit_menu.addAction(self.clear_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.advanced_settings_action)

        self.more_menu = QMenu(self)
        self.more_menu.addAction(self.save_copy_action)
        self.more_menu.addAction(self.export_all_action)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.remove_action)
        self.more_btn.setMenu(self.more_menu)

        self.view_menu = menu_bar.addMenu(tr("menu.view"))
        self.theme_system_action = QAction(tr("menu.theme_system"), self, checkable=True)
        self.theme_light_action = QAction(tr("menu.theme_light"), self, checkable=True)
        self.theme_dark_action = QAction(tr("menu.theme_dark"), self, checkable=True)
        self.theme_system_action.triggered.connect(lambda: self._set_theme_preference("system"))
        self.theme_light_action.triggered.connect(lambda: self._set_theme_preference("light"))
        self.theme_dark_action.triggered.connect(lambda: self._set_theme_preference("dark"))
        self.view_menu.addAction(self.theme_system_action)
        self.view_menu.addAction(self.theme_light_action)
        self.view_menu.addAction(self.theme_dark_action)

        self.help_menu = menu_bar.addMenu(tr("menu.help"))
        self.about_action = self._make_action("menu.about", self._show_about)
        self.github_action = self._make_action("menu.github", lambda: webbrowser.open("https://github.com/microsoft/markitdown"))
        self.help_menu.addAction(self.about_action)
        self.help_menu.addAction(self.github_action)

    def _make_action(self, key: str, slot) -> QAction:
        action = QAction(tr(key), self)
        action.setData(key)
        action.triggered.connect(slot)
        return action

    def _build_language_switcher(self) -> None:
        self.language_switcher_widget = QWidget(self.menuBar())
        self.language_switcher_widget.setObjectName("LanguageSwitch")
        corner_layout = QHBoxLayout(self.language_switcher_widget)
        corner_layout.setContentsMargins(0, 0, 10, 0)
        corner_layout.setSpacing(2)

        self.lang_en_btn = QPushButton("EN")
        self.lang_es_btn = QPushButton("ES")
        for btn in (self.lang_en_btn, self.lang_es_btn):
            btn.setObjectName("lang")
            btn.setCheckable(True)
        self.lang_en_btn.clicked.connect(lambda: i18n_manager.set_language(LANG_EN, self.settings))
        self.lang_es_btn.clicked.connect(lambda: i18n_manager.set_language(LANG_ES, self.settings))
        corner_layout.addWidget(self.lang_en_btn)
        corner_layout.addWidget(self.lang_es_btn)
        self.menuBar().setCornerWidget(self.language_switcher_widget, Qt.Corner.TopRightCorner)
        self._sync_language_buttons()

    def _install_shortcuts(self) -> None:
        # Only while the list has focus: a button keeps its key to itself, and the
        # text fields already keep Delete from a window shortcut.
        remove_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.table_view, self.action_remove_selected)
        # Set apart: PySide6 ignores a `context=` argument given to this constructor.
        remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        # The pane reads top to bottom, and so does the keyboard.
        zone = self.drop_zone
        for first, second in (
            (self.table_view, zone.browse_btn),
            (zone.browse_btn, zone.folder_btn),
            (zone.folder_btn, zone.url_edit),
            (zone.url_edit, zone.add_url_btn),
            (zone.add_url_btn, self.add_files_btn),
            (self.add_files_btn, self.clear_btn),
        ):
            self.setTabOrder(first, second)
        # Mouse clicks leave focus alone, so a focus ring only ever means the keyboard.
        for button in self.findChildren(QPushButton):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _sync_language_buttons(self) -> None:
        language = i18n_manager.language
        self.lang_en_btn.setChecked(language == LANG_EN)
        self.lang_es_btn.setChecked(language == LANG_ES)

    def _restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        restored = geometry is not None and self.restoreGeometry(geometry)
        # A window closed maximized comes back at its normal geometry, whose position
        # is the frame's, so only one closed at its normal size has the client area's.
        client_position = restored and self.windowState() == Qt.WindowState.WindowNoState
        # The app always opens on the empty screen, whatever size it closed at;
        # only the position carries over.
        self.setWindowState(Qt.WindowState.WindowNoState)
        if client_position:
            # move() takes the frame's position, so it would lower the window by its
            # title bar on every launch.
            self.setGeometry(self._fitted_geometry(empty=True))
        else:
            self._apply_window_size(empty=True)
        theme_pref = self.settings.value("theme/preference", "system")
        self._theme_preference = theme_pref
        self._sync_theme_menu_checks()

    def _current_theme_name(self) -> str:
        if self._theme_preference == "system":
            return detect_system_theme(self._launch_theme)
        return self._theme_preference

    def _follow_system_theme_changes(self) -> None:
        changed = getattr(QGuiApplication.styleHints(), "colorSchemeChanged", None)
        if changed is not None:
            changed.connect(self._on_system_color_scheme_changed)

    def _on_system_color_scheme_changed(self, *args) -> None:
        if self._theme_preference == "system":
            self._apply_theme(self._current_theme_name())

    def _sync_theme_menu_checks(self) -> None:
        self.theme_system_action.setChecked(self._theme_preference == "system")
        self.theme_light_action.setChecked(self._theme_preference == "light")
        self.theme_dark_action.setChecked(self._theme_preference == "dark")

    def _set_theme_preference(self, preference: str) -> None:
        self._theme_preference = preference
        self.settings.setValue("theme/preference", preference)
        self._sync_theme_menu_checks()
        self._apply_theme(self._current_theme_name())

    def _apply_theme(self, theme_name: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_fusion_palette(app, theme_name)
            app.setProperty("themeName", theme_name)
            app.setStyleSheet(stylesheet_for(theme_name))
        self.rendered_view.document().setDefaultStyleSheet(document_css_for(theme_name))
        self._render_markdown(self.raw_view.toPlainText())
        self.table_view.viewport().update()

    def _available_area(self) -> QRect:
        return self.screen().availableGeometry()

    def _remember_working_size(self) -> None:
        if not (self.isMaximized() or self.isFullScreen()):
            self.settings.setValue("window/working_width", self.width())
            self.settings.setValue("window/working_height", self.height())

    def _apply_window_size(self, empty: bool) -> None:
        """Small for the empty screen, the chosen working size for the list,
        always fully on screen. A maximized window stays as the person set it."""
        if self.isMaximized() or self.isFullScreen():
            return
        fitted = self._fitted_geometry(empty)
        self.resize(fitted.size())
        self.move(fitted.topLeft())

    def _fitted_geometry(self, empty: bool) -> QRect:
        """The size for this screen, at the current position moved fully on screen."""
        if empty:
            width, height = COMPACT_WINDOW_SIZE
        else:
            width = int(self.settings.value("window/working_width", WORKING_WINDOW_SIZE[0]))
            height = int(self.settings.value("window/working_height", WORKING_WINDOW_SIZE[1]))
        area = self._available_area()
        frame_width = self.frameGeometry().width() - self.width()
        frame_height = self.frameGeometry().height() - self.height()
        width = min(width, area.width() - frame_width)
        height = min(height, area.height() - frame_height)
        left = max(area.left(), min(self.x(), area.right() + 1 - width - frame_width))
        top = max(area.top(), min(self.y(), area.bottom() + 1 - height - frame_height))
        return QRect(left, top, width, height)

    def closeEvent(self, event) -> None:
        unfinished = self.conversion_queue.unfinished_count()
        if unfinished and not self._confirm_close(unfinished):
            event.ignore()
            return
        self.conversion_queue.cancel_unstarted()
        self.settings.setValue("window/geometry", self.saveGeometry())
        if not self._showing_empty:
            self._remember_working_size()
        super().closeEvent(event)

    def _confirm_close(self, unfinished: int) -> bool:
        """Closing loses these results, so keeping the window is the easy answer."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("msgbox.close_busy.title"))
        box.setText(self._close_busy_text(unfinished))
        keep = box.addButton(tr("msgbox.close_busy.keep"), QMessageBox.ButtonRole.RejectRole)
        close_anyway = box.addButton(tr("msgbox.close_busy.close"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)

        # Results keep arriving while it is open, since `exec` runs an event loop. Once
        # the last one is in, the question has no subject and closing loses nothing.
        nothing_left = False

        def follow_queue(*_args) -> None:
            nonlocal nothing_left
            remaining = self.conversion_queue.unfinished_count()
            if remaining:
                box.setText(self._close_busy_text(remaining))
            elif box.clickedButton() is None:
                nothing_left = True
                box.done(0)

        self.conversion_queue.progress_changed.connect(follow_queue)
        try:
            box.exec()
        finally:
            self.conversion_queue.progress_changed.disconnect(follow_queue)
        closing = nothing_left or box.clickedButton() is close_anyway
        box.deleteLater()
        return closing

    @staticmethod
    def _close_busy_text(unfinished: int) -> str:
        if unfinished == 1:
            return tr("msgbox.close_busy.text.one")
        return tr("msgbox.close_busy.text.other", count=unfinished)

    def _on_language_changed(self, language: str) -> None:
        self._sync_language_buttons()
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Re-pull every user-facing string from tr() so the currently
        visible UI updates immediately, with no restart required."""
        self.setWindowTitle(tr("window.title"))
        self._update_drop_zone_prominence()
        self.brand_name.setText(tr("window.title"))
        self._retranslate_saving_to()
        self._refresh_queue_summary()
        self.add_files_btn.setText(tr("button.add_files"))
        self.clear_btn.setText(tr("button.clear_all"))
        self.open_file_btn.setText(tr("button.open_file"))
        self.reveal_btn.setText(tr("button.open_folder"))
        self.retry_header_btn.setText(tr("menu.retry"))
        self.more_btn.setText(tr("button.more"))
        self.drag_overlay.setText(tr("overlay.drop"))
        self.table_view.setAccessibleName(tr("a11y.queue"))

        self.tabs.setTabText(0, tr("tab.rendered"))
        self.tabs.setTabText(1, tr("tab.raw"))
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        self._restore_copy_label()

        self.file_menu.setTitle(tr("menu.file"))
        self.edit_menu.setTitle(tr("menu.edit"))
        self.view_menu.setTitle(tr("menu.view"))
        self.help_menu.setTitle(tr("menu.help"))
        for action in (
            self.add_files_action,
            self.add_folder_action,
            self.add_url_action,
            self.open_file_action,
            self.reveal_action,
            self.save_copy_action,
            self.export_all_action,
            self.exit_action,
            self.copy_action,
            self.retry_action,
            self.remove_action,
            self.clear_action,
            self.advanced_settings_action,
            self.about_action,
            self.github_action,
        ):
            action.setText(tr(action.data()))
        self.theme_system_action.setText(tr("menu.theme_system"))
        self.theme_light_action.setText(tr("menu.theme_light"))
        self.theme_dark_action.setText(tr("menu.theme_dark"))

        self.model.retranslate()
        self.table_view.viewport().update()
        self._refresh_preview()

    def action_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("dialog.add_files"),
            "",
            supported_name_filter(tr("filter.supported")),
        )
        if files:
            self._add_paths(files)

    def action_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.add_folder"))
        if folder:
            self._add_paths([folder])

    def _on_paths_dropped(self, paths: list[str]) -> None:
        self._add_paths(paths)
        self._focus_list_after_drop()

    def _focus_list_after_drop(self) -> None:
        """Give the list the keyboard, since Delete only works from there.

        A drop arrives from outside the window, so it may find someone typing or
        a dialog open, and those keep the focus they have.
        """
        if QApplication.activeModalWidget() is not None or QApplication.activeWindow() not in (None, self):
            return
        if isinstance(self.focusWidget(), (QLineEdit, QPlainTextEdit)):
            return
        if self.model.rowCount():
            self.table_view.setFocus()

    def _add_paths(self, paths: list[str]) -> None:
        classified = classify_paths(paths)
        new_items: list[QueueItem] = []
        seen_sources: set[str] = set()
        already_queued = 0
        for file_path in classified.files:
            item = QueueItem.from_path(file_path)
            if item.source in seen_sources:
                continue
            seen_sources.add(item.source)
            if self.model.source_exists(item.source):
                already_queued += 1
            else:
                new_items.append(item)
        skipped = [tr("status.skipped_unsupported", count=classified.skipped)] if classified.skipped else []
        if new_items:
            parts = [tr("status.added_files", count=len(new_items))]
            if already_queued:
                parts.append(tr("status.some_already_queued", count=already_queued))
            self._enqueue_and_start(new_items)
            self.status_bar.showMessage(" ".join(parts + skipped), 4000)
            return
        if already_queued:
            # Nothing to add is not the same as nothing supported.
            if already_queued == 1:
                headline = tr("status.file_already_queued")
            else:
                headline = tr("status.files_already_queued", count=already_queued)
            self.status_bar.showMessage(" ".join([headline, *skipped]), 3000)
            return
        if classified.skipped or classified.saw_folder:
            QMessageBox.information(
                self,
                tr("msgbox.unsupported.title"),
                tr("msgbox.unsupported.text"),
            )

    def _enqueue_and_start(self, items: list[QueueItem]) -> None:
        """Add new items to the queue and start converting them right away."""
        rows = [self.model.add_item(item) for item in items]
        if self._selected_row() < 0:
            self._select_row(rows[0])
        self.conversion_queue.enqueue(items, self.conversion_options)

    def _select_row(self, row: int) -> None:
        """Select one row for the app's own reasons.

        `QTableView.selectRow` is for the person's input and reads the keys held down:
        with Shift it selects from an anchor nothing set, which is no row at all.
        """
        flags = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
        self.table_view.selectionModel().setCurrentIndex(self.model.index(row, 0), flags)

    def action_add_url(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, tr("msgbox.invalid_url.title"), tr("msgbox.invalid_url.text"))
            return
        if self.model.source_exists(url):
            self.status_bar.showMessage(tr("status.url_already_queued"), 3000)
            return
        self.url_edit.clear()
        self._enqueue_and_start([QueueItem.from_url(url)])

    def action_remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()})
        if rows:
            items = [self.model.item_at(row) for row in rows]
            self.model.remove_rows(rows)
            self.conversion_queue.discard(items)
            # Removing a row empties the selection, and Delete needs one to act again.
            last_row = self.model.rowCount() - 1
            if last_row >= 0:
                self._select_row(min(rows[0], last_row))
            self._refresh_preview()

    def action_clear_all(self) -> None:
        items = list(self.model.items())
        self.model.clear()
        self.conversion_queue.discard(items)
        self.raw_view.clear()
        self.rendered_view.clear()
        self._refresh_preview()

    def action_convert_selected(self) -> None:
        if not self.table_view.selectionModel().hasSelection():
            QMessageBox.information(self, tr("msgbox.no_selection.title"), tr("msgbox.no_selection.text"))
            return
        self._start_conversion(self._selected_retry_rows())

    def _selected_retry_rows(self) -> list[int]:
        """Selected rows that need a retry. Converting a saved one would duplicate its file."""
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()})
        return [row for row in rows if (item := self.model.item_at(row)) is not None and item.display_state in RETRY_STATES]

    def _start_conversion(self, rows: list[int]) -> None:
        if not rows:
            return
        items = [self.model.item_at(row) for row in rows]
        self.conversion_queue.retry([item for item in items if item is not None], self.conversion_options)

    def _refresh_preview_if_selected(self, item: QueueItem) -> None:
        row = self.model.row_of(item)
        if row >= 0 and self._selected_row() == row:
            self._refresh_preview()
        else:
            # Retry follows the whole selection, and this may be one of the other rows.
            self._update_preview_header(self.model.item_at(self._selected_row()))

    def _on_item_started(self, item: QueueItem) -> None:
        self._refresh_preview_if_selected(item)

    def _on_item_finished(self, item: QueueItem) -> None:
        if self._selected_row() < 0:
            self._select_row(self.model.row_of(item))
        else:
            self._refresh_preview_if_selected(item)

    def _on_item_failed(self, item: QueueItem, message: str) -> None:
        self._refresh_preview_if_selected(item)
        reason = failure_reason_text(item) or message
        self.status_bar.showMessage(tr("status.conversion_failed", message=reason), 5000)

    def _on_item_saved(self, item: QueueItem, path: str) -> None:
        self.status_bar.showMessage(tr("status.saved_to", path=path), 5000)

    def _on_item_save_failed(self, item: QueueItem, error: str) -> None:
        self.status_bar.showMessage(tr("status.autosave_failed", error=tr(item.save_error_reason.value)), 6000)

    def _on_batch_started(self) -> None:
        """New work, so what the strip said about earlier work is out of date."""
        self.status_bar.clearMessage()

    def _on_progress_changed(self, completed: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)
        self.progress_bar.setVisible(True)
        self.progress_bar.raise_()

    def _on_batch_finished(self) -> None:
        # A failure on the last item running reports after this, so it stays on screen.
        summary = queue_summary(self.model.items())
        if summary is not None and summary.attention:
            self.status_bar.showMessage(tr("status.batch_complete_problems", summary=summary.headline), 6000)
        else:
            self.status_bar.showMessage(tr("status.batch_complete"), 4000)
        self.progress_bar.setVisible(False)

    def _selected_row(self) -> int:
        rows = self.table_view.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _on_selection_changed(self) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        row = self._selected_row()
        item = self.model.item_at(row)
        self._update_preview_header(item)
        if item is None:
            self._show_preview_empty("", tr("preview.empty.hint"))
            return
        if item.status == ItemStatus.CONVERTING:
            self._show_preview_empty("", tr("preview.converting.hint"))
            return
        if item.status == ItemStatus.PENDING:
            self._show_preview_empty("", tr("preview.pending.hint"))
            return
        if item.status == ItemStatus.ERROR:
            self._show_preview_empty("", tr("preview.failed.hint"), self._error_detail(item))
            return
        if item.markdown_result:
            self._show_item_preview(item)
            return
        self._show_preview_empty("", tr("preview.no_text"))

    def _update_preview_header(self, item: QueueItem | None) -> None:
        self._preview_item = item
        self._refresh_action_states(item)
        if item is None:
            self.preview_header.setVisible(False)
            return
        self.preview_header.setVisible(True)
        self.preview_header_name.setToolTip(item.source)
        self._fit_preview_title()
        state = item.display_state
        kind = _HEADER_KIND[state]
        self.preview_header_status.setText(detail_status(item))
        self.preview_header_status.setToolTip(self._status_detail(item))
        self.preview_header_status.setProperty("kind", kind)
        self.preview_header_status.style().unpolish(self.preview_header_status)
        self.preview_header_status.style().polish(self.preview_header_status)

        saved = state == DisplayState.SAVED
        # Like the action, for the whole selection; everything else is about this row.
        retry = state in RETRY_STATES or self.retry_action.isEnabled()
        copy = self._has_result(item)
        self.open_file_btn.setVisible(saved)
        self.reveal_btn.setVisible(saved)
        self.retry_header_btn.setVisible(retry)
        self.copy_btn.setVisible(copy)
        self._set_primary(self._primary_button(retry, copy, saved))

    def _primary_button(self, retry: bool, copy: bool, saved: bool) -> QPushButton | None:
        """The one thing to do next, or nothing while there is only waiting."""
        if retry:
            return self.retry_header_btn
        if copy:
            return self.copy_btn
        if saved:
            return self.open_file_btn
        return None

    def _set_primary(self, primary: QPushButton | None) -> None:
        for button in (self.retry_header_btn, self.copy_btn, self.open_file_btn, self.reveal_btn):
            set_tier(button, "primary" if button is primary else "quiet")

    @staticmethod
    def _has_result(item: QueueItem | None) -> bool:
        """Whether there is current text to hand over.

        A failed retry's text is out of date, and a file holds it. If no file does, it
        is the only copy left, so it stays reachable.
        """
        if item is None or not item.markdown_result:
            return False
        return item.status == ItemStatus.DONE or (item.status == ItemStatus.ERROR and not item.saved_path)

    def _status_detail(self, item: QueueItem) -> str:
        state = item.display_state
        if state == DisplayState.ERROR:
            return item.error_message
        if state == DisplayState.SAVED:
            return item.saved_path
        if state == DisplayState.SAVE_FAILED:
            return tr("tooltip.save_failed", error=item.save_error)
        return ""

    def _refresh_action_states(self, item: QueueItem | None) -> None:
        """Menu actions follow the selected item, whichever menu they sit in."""
        state = item.display_state if item is not None else None
        result = self._has_result(item)
        saved = state == DisplayState.SAVED
        self.copy_action.setEnabled(result)
        self.save_copy_action.setEnabled(result)
        self.open_file_action.setEnabled(saved)
        self.reveal_action.setEnabled(saved)
        self._refresh_retry_action()
        self.remove_action.setEnabled(item is not None)

    def _refresh_retry_action(self) -> None:
        """Unlike the other actions, Retry follows the whole selection."""
        self.retry_action.setEnabled(bool(self._selected_retry_rows()))

    def _fit_preview_title(self) -> None:
        """Middle-elide the title so the extension survives a narrow pane."""
        if self._preview_item is None:
            return
        label = self.preview_header_name
        label.ensurePolished()
        available = self.preview_panel.width() - 2 * _PANE_MARGIN
        label.setText(
            label.fontMetrics().elidedText(
                self._preview_item.display_name,
                Qt.TextElideMode.ElideMiddle,
                max(available, 1),
            )
        )

    @staticmethod
    def _error_detail(item: QueueItem) -> str:
        """The library's own words, under the header's translated reason."""
        message = item.error_message.strip()
        if len(message) > _ERROR_DETAIL_CHARS:
            return message[:_ERROR_DETAIL_CHARS].rstrip() + "…"
        return message

    def _show_preview_empty(self, title: str, hint: str, detail: str = "") -> None:
        self.preview_empty_title.setText(title)
        self.preview_empty_title.setVisible(bool(title))
        self.preview_empty_hint.setText(hint)
        self.preview_error_detail.setText(detail)
        self.preview_error_detail.setVisible(bool(detail))
        self.preview_empty.setVisible(True)
        self.preview_body.setVisible(False)

    def _sync_spinner(self, *args) -> None:
        """Tick only while something the person started is actually converting."""
        converting = any(item.status == ItemStatus.CONVERTING for item in self.model.items())
        if converting and not self._spinner.isActive() and QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
            self._spinner.start()
        elif not converting and self._spinner.isActive():
            self._spinner.stop()

    def _advance_spinner(self) -> None:
        self.queue_delegate.advance_spinner()
        self.summary_mark.set_angle(self.queue_delegate.spin_angle)
        self.table_view.viewport().update()

    def _on_row_double_clicked(self, index) -> None:
        item = self.model.item_at(index.row())
        if item is not None and item.saved_path:
            self._open_file(item.saved_path)

    def _open_preview_file(self) -> None:
        if self._preview_item is not None and self._preview_item.saved_path:
            self._open_file(self._preview_item.saved_path)

    def _reveal_preview_file(self) -> None:
        if self._preview_item is not None and self._preview_item.saved_path:
            self._open_containing_folder(self._preview_item.saved_path)

    def _open_file(self, path: str) -> None:
        normalized = os.path.normpath(path)
        if not os.path.isfile(normalized):
            self.status_bar.showMessage(tr("status.file_missing"), 4000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(normalized))

    def _open_containing_folder(self, path: str) -> None:
        normalized = os.path.normpath(path)
        if not os.path.exists(normalized):
            self.status_bar.showMessage(tr("status.file_missing"), 4000)
            return
        try:
            subprocess.Popen(reveal_command(normalized))
        except OSError:
            pass

    def _show_item_preview(self, item: QueueItem) -> None:
        text = item.markdown_result or ""
        self.raw_view.blockSignals(True)
        self.raw_view.setPlainText(text)
        self.raw_view.blockSignals(False)
        self._render_markdown(text)
        self.preview_empty.setVisible(False)
        self.preview_body.setVisible(True)

    def _on_raw_text_changed(self) -> None:
        """The item takes every keystroke; the costly part waits for a pause."""
        item = self.model.item_at(self._selected_row())
        if item is not None:
            item.markdown_result = self.raw_view.toPlainText()
        self._render_timer.start()

    def _on_raw_edit_settled(self) -> None:
        item = self.model.item_at(self._selected_row())
        if item is not None:
            self._update_preview_header(item)
        self._render_markdown(self.raw_view.toPlainText())

    def _render_markdown(self, text: str) -> None:
        self._render_timer.stop()
        excerpt = preview_excerpt(text)
        html = (
            markdown_lib.markdown(excerpt, extensions=_MARKDOWN_EXTENSIONS, extension_configs=_MARKDOWN_EXTENSION_CONFIGS)
            if excerpt
            else ""
        )
        self._preview_full_width = needs_full_width(html)
        self._fit_reading_width()
        notice = self._truncation_notice() if len(excerpt) < len(text) else ""
        self.rendered_view.setHtml(preview_html(html, self._current_theme_name(), notice))

    def _truncation_notice(self) -> str:
        saved = self._preview_item is not None and self._preview_item.display_state == DisplayState.SAVED
        return tr("preview.truncated" if saved else "preview.truncated_unsaved")

    def _fit_reading_width(self) -> None:
        width = self.rendered_view.viewport().width()
        self.rendered_view.setLineWrapColumnOrWidth(width if self._preview_full_width else min(width, READING_WIDTH))

    def _show_queue_menu(self, pos) -> None:
        index = self.table_view.indexAt(pos)
        if index.isValid() and not self.table_view.selectionModel().isSelected(index):
            self._select_row(index.row())
        item = self.model.item_at(index.row()) if index.isValid() else None
        menu = QMenu(self)
        if item is not None and item.saved_path:
            menu.addAction(tr("menu.open_file"), lambda: self._open_file(item.saved_path))
            menu.addAction(tr("menu.open_folder"), lambda: self._open_containing_folder(item.saved_path))
        if item is not None and item.display_state in RETRY_STATES:
            menu.addAction(tr("menu.retry"), lambda: self._start_conversion([index.row()]))
        if item is not None:
            menu.addAction(tr("menu.remove"), self.action_remove_selected)
        if menu.actions():
            menu.addSeparator()
        menu.addAction(tr("button.clear_all"), self.action_clear_all)
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def action_save_current(self) -> None:
        row = self._selected_row()
        item = self.model.item_at(row)
        if not self._has_result(item):
            QMessageBox.information(self, tr("msgbox.nothing_to_save.title"), tr("msgbox.nothing_to_save.text"))
            return
        default_name = default_basename(item) + ".md"
        path, _ = QFileDialog.getSaveFileName(self, tr("dialog.save_copy_as"), default_name, tr("filter.markdown"))
        if path:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(item.markdown_result)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    tr("msgbox.save_copy_failed.title"),
                    tr("msgbox.save_copy_failed.text", error=_save_failure_text(classify_save_error(exc), str(exc))),
                )
                return
            self.status_bar.showMessage(tr("status.saved_copy_to", path=path), 4000)

    def action_export_all(self) -> None:
        converted = [item for item in self.model.items() if self._has_result(item)]
        if not converted:
            QMessageBox.information(self, tr("msgbox.nothing_to_export.title"), tr("msgbox.nothing_to_export.text"))
            return

        last_folder = self.settings.value("export/last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.choose_export_folder"), last_folder)
        if not folder:
            return
        self.settings.setValue("export/last_folder", folder)

        result = export_markdown(converted, folder)
        if result.written:
            self.status_bar.showMessage(tr("status.exported", count=len(result.written), folder=folder), 5000)
        if result.failures:
            details = "\n".join(
                f"{failure.item.display_name}: {_save_failure_text(failure.reason, failure.detail)}"
                for failure in result.failures
            )
            QMessageBox.warning(
                self,
                tr("msgbox.export_failed.title"),
                tr("msgbox.export_failed.text", count=len(result.failures), details=details),
            )

    def action_copy_raw(self) -> None:
        # From the item: a failed row shows its failure, so the tab may hold another's text.
        item = self.model.item_at(self._selected_row())
        text = item.markdown_result if item is not None else ""
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.status_bar.showMessage(tr("status.copied_raw"), 3000)
        self.copy_btn.setText(tr("button.copied"))
        self._copy_feedback.start()

    def _restore_copy_label(self) -> None:
        self._copy_feedback.stop()
        self.copy_btn.setText(tr("button.copy_raw"))

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _show_advanced_settings(self) -> None:
        target_item = self.model.item_at(self._selected_row())
        dialog = AdvancedSettingsDialog(self.conversion_options, target_item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.conversion_options = dialog.selected_options()
            # A finished item would otherwise keep the text made without them, since
            # Retry leaves it alone. A file already saved stays: the new one gets a suffix.
            if dialog.apply_item_overrides() and target_item.status == ItemStatus.DONE:
                self.conversion_queue.enqueue([target_item], self.conversion_options)
