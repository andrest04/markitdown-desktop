"""Main application window for MarkItDown Desktop."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser

import markdown as markdown_lib
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, QUrl
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.conversion_queue import ConversionQueue
from app.core.converter import (
    ConversionOptions,
    classify_paths,
    default_basename,
    export_markdown,
    supported_name_filter,
)
from app.core.queue_model import (
    COLUMN_STATUS,
    COLUMN_TYPE,
    DisplayState,
    ItemStatus,
    QueueItem,
    QueueTableModel,
)
from app.i18n import LANG_EN, LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.about_dialog import AboutDialog
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog
from app.ui.drop_zone import DropZone
from app.ui.queue_delegate import ROW_HEIGHT, QueueItemDelegate
from app.ui.theme import (
    READING_WIDTH,
    apply_fusion_palette,
    document_css_for,
    set_tier,
    stylesheet_for,
)

ORG_NAME = "andres"
APP_NAME = "MarkItDownDesktop"

# Preview header per state: translation key and the stylesheet `kind` property.
_HEADER_STATUS = {
    DisplayState.PENDING: ("preview.pending", "pending"),
    DisplayState.CONVERTING: ("preview.converting", "converting"),
    DisplayState.DONE: ("status.done", "pending"),
    DisplayState.SAVED: ("status.done_saved", "saved"),
    DisplayState.SAVE_FAILED: ("status.done_save_failed", "error"),
    DisplayState.ERROR: ("preview.failed", "error"),
}

_SPINNER_INTERVAL_MS = 90
_COPY_FEEDBACK_MS = 1500
_BRIEF_ERROR_CHARS = 200
_LIST_WIDTH = 340
# With the view's 2px focus border this lines the text up with the pane header.
_SHEET_MARGIN = 22
_PANE_MARGIN = 24


def _brief_error(message: str) -> str:
    """First line of a conversion error, short enough for the status line."""
    lines = message.strip().splitlines()
    first = lines[0] if lines else ""
    return first if len(first) <= _BRIEF_ERROR_CHARS else first[:_BRIEF_ERROR_CHARS].rstrip() + "…"


def detect_system_theme() -> str:
    """Best-effort light/dark detection based on the current QPalette."""
    palette = QGuiApplication.palette()
    window_color = palette.color(palette.ColorRole.Window)
    luminance = 0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
    return "dark" if luminance < 128 else "light"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        i18n_manager.init_from_settings(self.settings)
        i18n_manager.language_changed.connect(self._on_language_changed)

        self.setWindowTitle(tr("window.title"))
        self.resize(1180, 780)
        # Height only: an explicit width would override the layout's minimum
        # and clip the action row in longer languages or larger fonts.
        self.setMinimumHeight(560)

        self._preview_item: QueueItem | None = None

        self.conversion_options = ConversionOptions()

        self.model = QueueTableModel(self)
        self.conversion_queue = ConversionQueue(self.model, parent=self)
        self.conversion_queue.item_started.connect(self._on_item_started)
        self.conversion_queue.item_finished.connect(self._on_item_finished)
        self.conversion_queue.item_failed.connect(self._on_item_failed)
        self.conversion_queue.item_saved.connect(self._on_item_saved)
        self.conversion_queue.item_save_failed.connect(self._on_item_save_failed)
        self.conversion_queue.progress_changed.connect(self._on_progress_changed)
        self.conversion_queue.batch_finished.connect(self._on_batch_finished)

        self._spinner = QTimer(self)
        self._spinner.setInterval(_SPINNER_INTERVAL_MS)
        self._spinner.timeout.connect(self._advance_spinner)
        self._copy_feedback = QTimer(self)
        self._copy_feedback.setSingleShot(True)
        self._copy_feedback.setInterval(_COPY_FEEDBACK_MS)
        self._copy_feedback.timeout.connect(self._restore_copy_label)

        self._build_ui()
        self._build_menu()
        self._build_language_switcher()
        self._install_shortcuts()
        self._restore_settings()
        self._apply_theme(self._current_theme_name())
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

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(2)
        # Keeps its strip when hidden, so a batch starting never shifts the panes.
        policy = self.progress_bar.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.progress_bar.setSizePolicy(policy)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

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

        self.drag_overlay = QLabel(tr("overlay.drop"), central)
        self.drag_overlay.setObjectName("DragOverlay")
        self.drag_overlay.setIndent(56)
        self.drag_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Transparent to the drag as well, so the drop lands on the panes below.
        self.drag_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.drag_overlay.setVisible(False)
        self.drop_zone.drag_active_changed.connect(self._on_drag_active_changed)
        central.installEventFilter(self)
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
            elif watched is self.preview_panel:
                self._fit_preview_title()
            elif watched is self.rendered_view.viewport():
                self.rendered_view.setLineWrapColumnOrWidth(min(watched.width(), READING_WIDTH))
        return super().eventFilter(watched, event)

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
            self._add_paths,
            on_click=self.action_add_files,
            on_url=self.action_add_url,
            on_folder=self.action_add_folder,
        )
        self.url_edit = self.drop_zone.url_edit
        layout.addWidget(self.drop_zone)

        self.table_view = QTableView()
        self.table_view.setObjectName("QueueView")
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
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_queue_menu)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table_view, 1)

        self.queue_controls_widget = QWidget()
        queue_controls_layout = QHBoxLayout(self.queue_controls_widget)
        queue_controls_layout.setContentsMargins(8, 6, 8, 8)
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

        return panel

    def _update_drop_zone_prominence(self, *args) -> None:
        empty = len(self.model.items()) == 0
        self.drop_zone.set_prominent(empty)
        self.left_panel.setProperty("empty", empty)
        self.left_panel.style().unpolish(self.left_panel)
        self.left_panel.style().polish(self.left_panel)
        self.table_view.setVisible(not empty)
        self.queue_controls_widget.setVisible(not empty)
        self.preview_panel.setVisible(not empty)
        self.status_bar.setVisible(not empty)
        self.clear_action.setEnabled(not empty)
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
        empty_layout.setContentsMargins(_PANE_MARGIN, 8, _PANE_MARGIN, _PANE_MARGIN)
        empty_layout.setSpacing(4)
        self.preview_empty_title = QLabel()
        self.preview_empty_title.setObjectName("PreviewEmptyTitle")
        self.preview_empty_title.setWordWrap(True)
        self.preview_empty_hint = QLabel()
        self.preview_empty_hint.setObjectName("PreviewEmptyHint")
        self.preview_empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.preview_empty_title)
        empty_layout.addWidget(self.preview_empty_hint)
        empty_layout.addStretch(1)

        self.preview_body = QWidget()
        body_layout = QVBoxLayout(self.preview_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.rendered_view = QTextBrowser()
        self.rendered_view.setOpenExternalLinks(True)
        self.rendered_view.document().setDocumentMargin(_SHEET_MARGIN)
        self.rendered_view.setLineWrapMode(QTextBrowser.LineWrapMode.FixedPixelWidth)
        self.rendered_view.setLineWrapColumnOrWidth(READING_WIDTH)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        self.raw_view.document().setDocumentMargin(_SHEET_MARGIN)
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
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
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
        QShortcut(QKeySequence.StandardKey.Delete, self.table_view, self.action_remove_selected)
        # Mouse clicks leave focus alone, so a focus ring only ever means the keyboard.
        for button in self.findChildren(QPushButton):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _sync_language_buttons(self) -> None:
        language = i18n_manager.language
        self.lang_en_btn.setChecked(language == LANG_EN)
        self.lang_es_btn.setChecked(language == LANG_ES)

    def _restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        theme_pref = self.settings.value("theme/preference", "system")
        self._theme_preference = theme_pref
        self._sync_theme_menu_checks()

    def _current_theme_name(self) -> str:
        if self._theme_preference == "system":
            return detect_system_theme()
        return self._theme_preference

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

    def closeEvent(self, event) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)

    def _on_language_changed(self, language: str) -> None:
        self._sync_language_buttons()
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Re-pull every user-facing string from tr() so the currently
        visible UI updates immediately, with no restart required."""
        self.setWindowTitle(tr("window.title"))
        self.drop_zone.retranslate()
        self.add_files_btn.setText(tr("button.add_files"))
        self.clear_btn.setText(tr("button.clear_all"))
        self.open_file_btn.setText(tr("button.open_file"))
        self.reveal_btn.setText(tr("button.open_folder"))
        self.retry_header_btn.setText(tr("menu.retry"))
        self.more_btn.setText(tr("button.more"))
        self.drag_overlay.setText(tr("overlay.drop"))

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

    def _add_paths(self, paths: list[str]) -> None:
        classified = classify_paths(paths)
        new_items: list[QueueItem] = []
        new_sources: set[str] = set()
        for file_path in classified.files:
            item = QueueItem.from_path(file_path)
            if item.source not in new_sources and not self.model.source_exists(item.source):
                new_sources.add(item.source)
                new_items.append(item)
        if new_items:
            message = tr("status.added_files", count=len(new_items))
            if classified.skipped:
                message = f"{message} {tr('status.skipped_unsupported', count=classified.skipped)}"
            self.status_bar.showMessage(message, 4000)
            self._enqueue_and_start(new_items)
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
            self.table_view.selectRow(rows[0])
        self.conversion_queue.enqueue(items, self.conversion_options)

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
            self.model.remove_rows(rows)
            self._refresh_preview()

    def action_clear_all(self) -> None:
        self.model.clear()
        self.raw_view.clear()
        self.rendered_view.clear()
        self._refresh_preview()

    def action_convert_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, tr("msgbox.no_selection.title"), tr("msgbox.no_selection.text"))
            return
        self._start_conversion(rows)

    def _start_conversion(self, rows: list[int]) -> None:
        if not rows:
            return
        items = [self.model.item_at(row) for row in rows]
        self.conversion_queue.enqueue([item for item in items if item is not None], self.conversion_options)

    def _refresh_preview_if_selected(self, item: QueueItem) -> None:
        row = self.model.row_of(item)
        if row >= 0 and self._selected_row() == row:
            self._refresh_preview()

    def _on_item_started(self, item: QueueItem) -> None:
        self._refresh_preview_if_selected(item)

    def _on_item_finished(self, item: QueueItem) -> None:
        if self._selected_row() < 0:
            self.table_view.selectRow(self.model.row_of(item))
        else:
            self._refresh_preview_if_selected(item)

    def _on_item_failed(self, item: QueueItem, message: str) -> None:
        self._refresh_preview_if_selected(item)
        self.status_bar.showMessage(tr("status.conversion_failed", message=message), 5000)

    def _on_item_saved(self, item: QueueItem, path: str) -> None:
        self.status_bar.showMessage(tr("status.saved_to", path=path), 5000)

    def _on_item_save_failed(self, item: QueueItem, error: str) -> None:
        self.status_bar.showMessage(tr("status.autosave_failed", error=error), 6000)

    def _on_progress_changed(self, completed: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)
        self.progress_bar.setVisible(True)

    def _on_batch_finished(self) -> None:
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
            self._show_preview_empty("", tr("preview.failed.hint"))
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
        key, kind = _HEADER_STATUS[state]
        if state == DisplayState.SAVE_FAILED:
            status = tr("status.save_failed_detail", error=_brief_error(item.save_error))
        elif state == DisplayState.ERROR:
            status = _brief_error(item.error_message) or tr(key)
        else:
            status = tr(key)
        self.preview_header_status.setText(status)
        self.preview_header_status.setToolTip(self._status_detail(item))
        self.preview_header_status.setProperty("kind", kind)
        self.preview_header_status.style().unpolish(self.preview_header_status)
        self.preview_header_status.style().polish(self.preview_header_status)

        saved = state == DisplayState.SAVED
        retry = state in (DisplayState.ERROR, DisplayState.SAVE_FAILED)
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
        return (
            item is not None
            and item.status == ItemStatus.DONE
            and bool(item.markdown_result)
        )

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
        self.retry_action.setEnabled(state in (DisplayState.ERROR, DisplayState.SAVE_FAILED))
        self.remove_action.setEnabled(item is not None)

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

    def _show_preview_empty(self, title: str, hint: str) -> None:
        self.preview_empty_title.setText(title)
        self.preview_empty_title.setVisible(bool(title))
        self.preview_empty_hint.setText(hint)
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
            if sys.platform.startswith("win"):
                subprocess.Popen(f'explorer /select,"{normalized}"', shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", normalized])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(normalized)])
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
        text = self.raw_view.toPlainText()
        row = self._selected_row()
        item = self.model.item_at(row)
        if item is not None:
            item.markdown_result = text
        self._render_markdown(text)

    def _render_markdown(self, text: str) -> None:
        html = markdown_lib.markdown(text, extensions=["extra", "sane_lists", "tables"]) if text else ""
        self.rendered_view.setHtml(html)

    def _show_queue_menu(self, pos) -> None:
        index = self.table_view.indexAt(pos)
        if index.isValid() and not self.table_view.selectionModel().isSelected(index):
            self.table_view.selectRow(index.row())
        item = self.model.item_at(index.row()) if index.isValid() else None
        menu = QMenu(self)
        if item is not None and item.saved_path:
            menu.addAction(tr("menu.open_file"), lambda: self._open_file(item.saved_path))
            menu.addAction(tr("menu.open_folder"), lambda: self._open_containing_folder(item.saved_path))
        if item is not None and item.status == ItemStatus.ERROR:
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
        if item is None or item.markdown_result is None:
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
                    tr("msgbox.save_copy_failed.text", error=exc),
                )
                return
            self.status_bar.showMessage(tr("status.saved_copy_to", path=path), 4000)

    def action_export_all(self) -> None:
        converted = [item for item in self.model.items() if item.status == ItemStatus.DONE and item.markdown_result]
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
            details = "\n".join(f"{item.display_name}: {error}" for item, error in result.failures)
            QMessageBox.warning(
                self,
                tr("msgbox.export_failed.title"),
                tr("msgbox.export_failed.text", count=len(result.failures), details=details),
            )

    def action_copy_raw(self) -> None:
        text = self.raw_view.toPlainText()
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
            dialog.apply_item_overrides()
