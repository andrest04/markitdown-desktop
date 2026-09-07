"""Main application window for MarkItDown Desktop."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser

import markdown as markdown_lib
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
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
    QSplitter,
    QStatusBar,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.converter import (
    ConversionOptions,
    ConversionWorker,
    auto_save_markdown,
    default_basename,
    detect_type_label,
    is_supported_file,
    iter_supported_files,
    sanitize_filename,
    supported_name_filter,
)
from app.core.queue_model import (
    COLUMN_STATUS,
    COLUMN_TYPE,
    ItemStatus,
    QueueItem,
    QueueTableModel,
    SourceKind,
)
from app.i18n import LANG_EN, LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.about_dialog import AboutDialog
from app.ui.advanced_settings_dialog import AdvancedSettingsDialog
from app.ui.drop_zone import DropZone
from app.ui.queue_delegate import ROW_HEIGHT, QueueItemDelegate
from app.ui.theme import apply_fusion_palette, stylesheet_for

ORG_NAME = "andres"
APP_NAME = "MarkItDownDesktop"


def detect_system_theme() -> str:
    """Best-effort light/dark detection based on the current QPalette."""
    palette = QGuiApplication.palette()
    window_color = palette.color(palette.ColorRole.Window)
    luminance = 0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
    return "dark" if luminance < 128 else "light"


class _FileDropFilter(QObject):
    """Accept file drops on panes that are not the drop zone itself."""

    def __init__(self, on_paths, set_active, parent=None):
        super().__init__(parent)
        self._on_paths = on_paths
        self._set_active = set_active

    def eventFilter(self, watched, event):
        et = event.type()
        if et == QEvent.Type.DragEnter:
            mime = event.mimeData()
            if mime is not None and mime.hasUrls():
                event.acceptProposedAction()
                self._set_active(True)
                return True
        elif et == QEvent.Type.DragLeave:
            self._set_active(False)
        elif et == QEvent.Type.Drop:
            self._set_active(False)
            mime = event.mimeData()
            paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if paths:
                self._on_paths(paths)
            event.acceptProposedAction()
            return True
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        i18n_manager.init_from_settings(self.settings)
        i18n_manager.language_changed.connect(self._on_language_changed)

        self.setWindowTitle(tr("window.title"))
        self.resize(1180, 780)
        self.setMinimumSize(880, 600)

        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers = 0
        self._total_batch = 0
        self._preview_item: QueueItem | None = None

        self.enable_plugins = False
        self.keep_data_uris = False
        self.docintel_enabled = False
        self.docintel_endpoint = ""
        self.cu_enabled = False
        self.cu_endpoint = ""
        self.cu_analyzer_id = ""

        self.model = QueueTableModel(self)

        self._build_ui()
        self._build_menu()
        self._build_language_switcher()
        self._install_shortcuts()
        self._restore_settings()
        self._apply_theme(self._current_theme_name())
        self._update_drop_zone_prominence()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(10)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter, 1)

        self.left_panel = self._build_left_panel()
        self.preview_panel = self._build_right_panel()
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.setSizes([420, 720])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._drop_filter = _FileDropFilter(
            self._add_paths,
            lambda active: self.drop_zone.set_drag_active(active),
            self,
        )
        for widget in (self.left_panel, self.preview_panel, self.table_view.viewport()):
            widget.setAcceptDrops(True)
            widget.installEventFilter(self._drop_filter)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("QueuePane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

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
        self.table_view.setItemDelegate(QueueItemDelegate(self.table_view))
        self.table_view.horizontalHeader().setVisible(False)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setColumnHidden(COLUMN_TYPE, True)
        self.table_view.setColumnHidden(COLUMN_STATUS, True)
        self.table_view.horizontalHeader().setSectionResizeMode(0, self.table_view.horizontalHeader().ResizeMode.Stretch)
        self.table_view.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
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
        queue_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.remove_btn = QPushButton(tr("button.remove_selected"))
        self.remove_btn.setObjectName("secondary")
        self.remove_btn.clicked.connect(self.action_remove_selected)
        self.clear_btn = QPushButton(tr("button.clear_all"))
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self.action_clear_all)
        queue_controls_layout.addWidget(self.remove_btn)
        queue_controls_layout.addWidget(self.clear_btn)
        layout.addWidget(self.queue_controls_widget)

        self.model.rowsInserted.connect(self._update_drop_zone_prominence)
        self.model.rowsRemoved.connect(self._update_drop_zone_prominence)
        self.model.modelReset.connect(self._update_drop_zone_prominence)

        return panel

    def _update_drop_zone_prominence(self, *args) -> None:
        empty = len(self.model.items()) == 0
        self.drop_zone.set_prominent(empty)
        self.table_view.setVisible(not empty)
        self.queue_controls_widget.setVisible(not empty)
        self.preview_panel.setVisible(not empty)
        if empty:
            self._update_preview_header(None)
            self._show_preview_empty(tr("preview.empty"), tr("preview.empty.hint"))

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("PreviewPane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)

        self.preview_header = QWidget()
        self.preview_header.setObjectName("PreviewHeader")
        self.preview_header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.preview_header.setVisible(False)
        header = QVBoxLayout(self.preview_header)
        header.setContentsMargins(14, 10, 14, 10)
        header.setSpacing(6)
        self.preview_header_name = QLabel()
        self.preview_header_name.setObjectName("PreviewHeaderName")
        self.preview_header_name.setWordWrap(True)
        self.preview_header_status = QLabel()
        self.preview_header_status.setObjectName("PreviewHeaderStatus")
        self.preview_header_status.setWordWrap(True)
        header.addWidget(self.preview_header_name)
        header.addWidget(self.preview_header_status)
        header_actions = QHBoxLayout()
        header_actions.setSpacing(8)
        self.open_file_btn = QPushButton(tr("button.open_file"))
        self.open_file_btn.clicked.connect(self._open_preview_file)
        self.reveal_btn = QPushButton(tr("button.open_folder"))
        self.reveal_btn.setObjectName("secondary")
        self.reveal_btn.clicked.connect(self._reveal_preview_file)
        self.retry_header_btn = QPushButton(tr("menu.retry"))
        self.retry_header_btn.setObjectName("secondary")
        self.retry_header_btn.clicked.connect(self.action_convert_selected)
        header_actions.addWidget(self.open_file_btn)
        header_actions.addWidget(self.reveal_btn)
        header_actions.addWidget(self.retry_header_btn)
        header_actions.addStretch(1)
        header.addLayout(header_actions)
        layout.addWidget(self.preview_header)

        self.preview_empty = QWidget()
        empty_layout = QVBoxLayout(self.preview_empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty_title = QLabel(tr("preview.empty"))
        self.preview_empty_title.setObjectName("PreviewEmptyTitle")
        self.preview_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty_title.setWordWrap(True)
        self.preview_empty_hint = QLabel(tr("preview.empty.hint"))
        self.preview_empty_hint.setObjectName("PreviewEmptyHint")
        self.preview_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.preview_empty_title)
        empty_layout.addWidget(self.preview_empty_hint)

        self.preview_body = QWidget()
        body_layout = QVBoxLayout(self.preview_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.rendered_view = QTextBrowser()
        self.rendered_view.setOpenExternalLinks(True)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.raw_view.setFont(font)
        self.raw_view.textChanged.connect(self._on_raw_text_changed)
        self.tabs.addTab(self.rendered_view, tr("tab.rendered"))
        self.tabs.addTab(self.raw_view, tr("tab.raw"))
        body_layout.addWidget(self.tabs, 1)

        self.autosave_note = QLabel(tr("note.autosave"))
        self.autosave_note.setWordWrap(True)
        self.autosave_note.setObjectName("SupportedTypesLabel")
        body_layout.addWidget(self.autosave_note)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton(tr("button.copy_raw"))
        self.copy_btn.setObjectName("secondary")
        self.copy_btn.clicked.connect(self.action_copy_raw)
        self.save_md_btn = QPushButton(tr("button.save_copy_as"))
        self.save_md_btn.setObjectName("secondary")
        self.save_md_btn.clicked.connect(self.action_save_current)
        self.export_all_btn = QPushButton(tr("button.export_all_to"))
        self.export_all_btn.setObjectName("ghost")
        self.export_all_btn.clicked.connect(self.action_export_all)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.save_md_btn)
        btn_row.addWidget(self.export_all_btn)
        body_layout.addLayout(btn_row)

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
        self.save_copy_action = self._make_action("menu.save_copy_as", self.action_save_current)
        self.export_all_action = self._make_action("menu.export_all_to", self.action_export_all)
        self.exit_action = self._make_action("menu.exit", self.close)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.file_menu.addAction(self.add_files_action)
        self.file_menu.addAction(self.add_folder_action)
        self.file_menu.addAction(self.add_url_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.save_copy_action)
        self.file_menu.addAction(self.export_all_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = menu_bar.addMenu(tr("menu.edit"))
        self.advanced_settings_action = self._make_action("menu.advanced_settings", self._show_advanced_settings)
        self.edit_menu.addAction(self.advanced_settings_action)

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
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lang_en_btn.clicked.connect(lambda: i18n_manager.set_language(LANG_EN, self.settings))
        self.lang_es_btn.clicked.connect(lambda: i18n_manager.set_language(LANG_ES, self.settings))
        corner_layout.addWidget(self.lang_en_btn)
        corner_layout.addWidget(self.lang_es_btn)
        self.menuBar().setCornerWidget(self.language_switcher_widget, Qt.Corner.TopRightCorner)
        self._sync_language_buttons()

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence.StandardKey.Delete, self.table_view, self.action_remove_selected)

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
        self.remove_btn.setText(tr("button.remove_selected"))
        self.clear_btn.setText(tr("button.clear_all"))
        self.open_file_btn.setText(tr("button.open_file"))
        self.reveal_btn.setText(tr("button.open_folder"))
        self.retry_header_btn.setText(tr("menu.retry"))

        self.preview_empty_title.setText(tr("preview.empty"))
        self.preview_empty_hint.setText(tr("preview.empty.hint"))
        self.tabs.setTabText(0, tr("tab.rendered"))
        self.tabs.setTabText(1, tr("tab.raw"))
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        self.autosave_note.setText(tr("note.autosave"))
        self.save_md_btn.setText(tr("button.save_copy_as"))
        self.export_all_btn.setText(tr("button.export_all_to"))
        self.copy_btn.setText(tr("button.copy_raw"))

        self.file_menu.setTitle(tr("menu.file"))
        self.edit_menu.setTitle(tr("menu.edit"))
        self.view_menu.setTitle(tr("menu.view"))
        self.help_menu.setTitle(tr("menu.help"))
        for action in (
            self.add_files_action,
            self.add_folder_action,
            self.add_url_action,
            self.save_copy_action,
            self.export_all_action,
            self.exit_action,
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
        added_rows: list[int] = []
        skipped = 0
        saw_folder = False
        for path in paths:
            if os.path.isdir(path):
                saw_folder = True
                for file_path in iter_supported_files(path):
                    row = self._add_single_file(file_path)
                    if row is not None:
                        added_rows.append(row)
            elif os.path.isfile(path):
                if not is_supported_file(path):
                    skipped += 1
                    continue
                row = self._add_single_file(path)
                if row is not None:
                    added_rows.append(row)
        if added_rows:
            message = tr("status.added_files", count=len(added_rows))
            if skipped:
                message = f"{message} {tr('status.skipped_unsupported', count=skipped)}"
            self.status_bar.showMessage(message, 4000)
            if self._selected_row() < 0:
                self.table_view.selectRow(added_rows[0])
            self._start_conversion(added_rows)
            return
        if skipped or saw_folder:
            QMessageBox.information(
                self,
                tr("msgbox.unsupported.title"),
                tr("msgbox.unsupported.text"),
            )

    def _add_single_file(self, path: str) -> int | None:
        abs_path = os.path.abspath(path)
        if self.model.source_exists(abs_path):
            return None
        item = QueueItem(
            source=abs_path,
            kind=SourceKind.FILE,
            display_name=os.path.basename(abs_path),
            detected_type=detect_type_label(abs_path, SourceKind.FILE),
        )
        self.model.add_item(item)
        return len(self.model.items()) - 1

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
        item = QueueItem(
            source=url,
            kind=SourceKind.URL,
            display_name=url,
            detected_type=detect_type_label(url, SourceKind.URL),
        )
        self.model.add_item(item)
        self.url_edit.clear()
        row = len(self.model.items()) - 1
        if self._selected_row() < 0:
            self.table_view.selectRow(row)
        self._start_conversion([row])

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

    def _current_options(self) -> ConversionOptions:
        return ConversionOptions(
            enable_plugins=self.enable_plugins,
            keep_data_uris=self.keep_data_uris,
            docintel_enabled=self.docintel_enabled,
            docintel_endpoint=self.docintel_endpoint,
            cu_enabled=self.cu_enabled,
            cu_endpoint=self.cu_endpoint,
            cu_analyzer_id=self.cu_analyzer_id,
        )

    def action_convert_all(self) -> None:
        rows = list(range(len(self.model.items())))
        self._start_conversion(rows)

    def action_convert_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, tr("msgbox.no_selection.title"), tr("msgbox.no_selection.text"))
            return
        self._start_conversion(rows)

    def _start_conversion(self, rows: list[int]) -> None:
        if not rows:
            return
        options = self._current_options()
        self._active_workers = 0
        launched = 0

        for row in rows:
            item = self.model.item_at(row)
            if item is None or item.status == ItemStatus.CONVERTING:
                continue
            worker = ConversionWorker(row, item, options)
            worker.signals.started.connect(self._on_conversion_started)
            worker.signals.finished.connect(self._on_conversion_finished)
            worker.signals.failed.connect(self._on_conversion_failed)
            self.thread_pool.start(worker)
            launched += 1

        self._total_batch = launched
        if launched == 0:
            self.progress_bar.setVisible(False)
            return
        self.progress_bar.setMaximum(launched)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

    def _on_conversion_started(self, row: int) -> None:
        item = self.model.item_at(row)
        if item is not None:
            item.status = ItemStatus.CONVERTING
            self.model.refresh_row(row)
            if self._selected_row() == row:
                self._refresh_preview()

    def _on_conversion_finished(self, row: int, markdown_text: str) -> None:
        item = self.model.item_at(row)
        if item is not None:
            item.status = ItemStatus.DONE
            item.markdown_result = markdown_text
            item.error_message = ""
            self._auto_save_to_downloads(item)
            self.model.refresh_row(row)
            if self._selected_row() < 0:
                self.table_view.selectRow(row)
            elif self._selected_row() == row:
                self._refresh_preview()
        self._advance_progress()

    def _auto_save_to_downloads(self, item: QueueItem) -> None:
        """Write a freshly converted item straight to Downloads (the whole
        point of the app being "drop it and it's done" -- no manual export
        step required)."""
        try:
            saved_path = auto_save_markdown(item, item.markdown_result or "")
        except OSError as exc:
            item.saved_path = ""
            item.save_error = str(exc)
            self.status_bar.showMessage(tr("status.autosave_failed", error=exc), 6000)
        else:
            item.saved_path = str(saved_path)
            item.save_error = ""
            self.status_bar.showMessage(tr("status.saved_to", path=saved_path), 5000)

    def _on_conversion_failed(self, row: int, message: str) -> None:
        item = self.model.item_at(row)
        if item is not None:
            item.status = ItemStatus.ERROR
            item.error_message = message
            self.model.refresh_row(row)
            if self._selected_row() == row:
                self._refresh_preview()
        self._advance_progress()
        self.status_bar.showMessage(tr("status.conversion_failed", message=message), 5000)

    def _advance_progress(self) -> None:
        self._active_workers += 1
        self.progress_bar.setValue(self._active_workers)
        if self._active_workers >= self._total_batch:
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
            self._show_preview_empty(tr("preview.empty"), tr("preview.empty.hint"))
            return
        if item.status == ItemStatus.CONVERTING:
            self._show_preview_empty(tr("preview.converting"), item.display_name)
            return
        if item.status == ItemStatus.PENDING:
            self._show_preview_empty(tr("preview.pending"), item.display_name)
            return
        if item.status == ItemStatus.ERROR:
            self._show_preview_empty(tr("preview.failed"), item.error_message or tr("status.error"))
            return
        if item.markdown_result:
            self._show_item_preview(item)
            return
        self._show_preview_empty(tr("preview.empty"), tr("preview.empty.hint"))

    def _update_preview_header(self, item: QueueItem | None) -> None:
        self._preview_item = item
        if item is None:
            self.preview_header.setVisible(False)
            return
        self.preview_header.setVisible(True)
        self.preview_header_name.setText(item.display_name)
        saved = bool(item.status == ItemStatus.DONE and item.saved_path)
        failed = item.status == ItemStatus.ERROR or (item.status == ItemStatus.DONE and bool(item.save_error))
        converting = item.status == ItemStatus.CONVERTING
        if saved:
            status = tr("status.done_saved")
            kind = "saved"
        elif item.status == ItemStatus.DONE and item.save_error:
            status = tr("status.done_save_failed")
            kind = "error"
        elif item.status == ItemStatus.ERROR:
            status = item.error_message or tr("preview.failed")
            kind = "error"
        elif converting:
            status = tr("preview.converting")
            kind = "converting"
        elif item.status == ItemStatus.PENDING:
            status = tr("preview.pending")
            kind = "pending"
        else:
            status = tr(item.status.value)
            kind = "pending"
        self.preview_header_status.setText(status)
        self.preview_header_status.setProperty("kind", kind)
        self.preview_header_status.style().unpolish(self.preview_header_status)
        self.preview_header_status.style().polish(self.preview_header_status)
        self.open_file_btn.setVisible(saved)
        self.reveal_btn.setVisible(saved)
        self.retry_header_btn.setVisible(failed and not converting)

    def _show_preview_empty(self, title: str, hint: str) -> None:
        self.preview_empty_title.setText(title)
        self.preview_empty_hint.setText(hint)
        self.preview_empty.setVisible(True)
        self.preview_body.setVisible(False)

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
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(item.markdown_result)
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

        used_names: set[str] = set()
        written = 0
        for item in converted:
            base = sanitize_filename(default_basename(item))
            name = base
            counter = 1
            while name in used_names:
                name = f"{base}_{counter}"
                counter += 1
            used_names.add(name)
            out_path = os.path.join(folder, f"{name}.md")
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(item.markdown_result)
            written += 1

        self.status_bar.showMessage(tr("status.exported", count=written, folder=folder), 5000)

    def action_copy_raw(self) -> None:
        text = self.raw_view.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.status_bar.showMessage(tr("status.copied_raw"), 3000)

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _show_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(self, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_to_main_window()
