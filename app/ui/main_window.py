"""Main application window for MarkItDown Desktop."""
from __future__ import annotations

import os
import sys
import subprocess
import webbrowser
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, Qt, QThreadPool
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
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

import markdown as markdown_lib

from app.core.converter import (
    ConversionOptions,
    ConversionWorker,
    auto_save_markdown,
    default_basename,
    detect_type_label,
    iter_supported_files,
    sanitize_filename,
)
from app.core.queue_model import (
    ItemStatus,
    QueueItem,
    QueueTableModel,
    SourceKind,
)
from app.i18n import LANG_EN, LANG_ES, manager as i18n_manager, tr
from app.ui.theme import stylesheet_for

ORG_NAME = "andres"
APP_NAME = "MarkItDownDesktop"


def detect_system_theme() -> str:
    """Best-effort light/dark detection based on the current QPalette."""
    palette = QGuiApplication.palette()
    window_color = palette.color(palette.ColorRole.Window)
    luminance = 0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
    return "dark" if luminance < 128 else "light"


EMPTY_HEIGHT = 260
FILLED_HEIGHT = 90


class DropZone(QWidget):
    """Drag-and-drop target for files and folders; also click-to-browse.

    Big and centered when the queue is empty (the primary, dominant UI
    surface); shrinks to a slim bar once items exist so the queue table
    can take over.
    """

    def __init__(self, on_paths_dropped, on_click=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_paths_dropped = on_paths_dropped
        self._on_click = on_click
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(EMPTY_HEIGHT)
        self._prominent = True

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(61, 123, 245, 170))
        self.setGraphicsEffect(self._shadow)

        self._hover_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        self._label = QLabel(tr("dropzone.empty"))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        font = self._label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setWeight(QFont.Weight.DemiBold)
        self._label.setFont(font)
        layout.addWidget(self._label)
        self.setProperty("dragActive", False)

    def set_prominent(self, prominent: bool) -> None:
        """Switch between the big "empty queue" look and a slim bar."""
        self._prominent = prominent
        self.setMinimumHeight(EMPTY_HEIGHT if prominent else FILLED_HEIGHT)
        self._label.setText(tr("dropzone.empty") if prominent else tr("dropzone.filled"))

    def retranslate(self) -> None:
        self.set_prominent(self._prominent)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._on_click is not None and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(28)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(0)
        super().leaveEvent(event)

    def _animate_shadow(self, target: int) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._shadow.blurRadius())
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):  # noqa: N802
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):  # noqa: N802
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._on_paths_dropped(paths)
        event.acceptProposedAction()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(360)

        try:
            md_version = pkg_version("markitdown")
        except PackageNotFoundError:
            from markitdown import __about__

            md_version = getattr(__about__, "__version__", "unknown")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("about.heading")))
        layout.addWidget(QLabel(tr("about.markitdown_version", version=md_version)))
        layout.addWidget(QLabel(tr("about.description")))

        link = QLabel('<a href="https://github.com/microsoft/markitdown">github.com/microsoft/markitdown</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class AdvancedSettingsDialog(QDialog):
    """Secondary, opt-in dialog for the markitdown power-user options.

    Kept out of the main window on purpose: the primary flow is
    "drop a file or paste a URL, done" -- these fields (plugins, Azure
    Document Intelligence / Content Understanding, per-item stream-info
    hints) are for the rare cases that need them.
    """

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle(tr("advanced.title"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(tr("advanced.conversion_options")))
        self.enable_plugins_cb = QCheckBox(tr("advanced.enable_plugins"))
        self.enable_plugins_cb.setChecked(main_window.enable_plugins)
        layout.addWidget(self.enable_plugins_cb)

        self.keep_data_uris_cb = QCheckBox(tr("advanced.keep_data_uris"))
        self.keep_data_uris_cb.setChecked(main_window.keep_data_uris)
        layout.addWidget(self.keep_data_uris_cb)

        self.docintel_cb = QCheckBox(tr("advanced.enable_docintel"))
        self.docintel_cb.setChecked(main_window.docintel_enabled)
        layout.addWidget(self.docintel_cb)
        self.docintel_endpoint_edit = QLineEdit(main_window.docintel_endpoint)
        self.docintel_endpoint_edit.setPlaceholderText(tr("advanced.docintel_placeholder"))
        layout.addWidget(self.docintel_endpoint_edit)

        self.cu_cb = QCheckBox(tr("advanced.enable_cu"))
        self.cu_cb.setChecked(main_window.cu_enabled)
        layout.addWidget(self.cu_cb)
        self.cu_endpoint_edit = QLineEdit(main_window.cu_endpoint)
        self.cu_endpoint_edit.setPlaceholderText(tr("advanced.cu_endpoint_placeholder"))
        layout.addWidget(self.cu_endpoint_edit)
        self.cu_analyzer_edit = QLineEdit(main_window.cu_analyzer_id)
        self.cu_analyzer_edit.setPlaceholderText(tr("advanced.cu_analyzer_placeholder"))
        layout.addWidget(self.cu_analyzer_edit)

        layout.addWidget(QLabel(tr("advanced.per_item_hints")))
        row = main_window._selected_row()
        item = main_window.model.item_at(row)
        self._target_item = item
        if item is None:
            layout.addWidget(QLabel(tr("advanced.select_row_first")))
            self.extension_override_edit = QLineEdit()
            self.mimetype_override_edit = QLineEdit()
            self.charset_override_edit = QLineEdit()
            for widget in (self.extension_override_edit, self.mimetype_override_edit, self.charset_override_edit):
                widget.setEnabled(False)
        else:
            layout.addWidget(QLabel(tr("advanced.applies_to", name=item.display_name)))
            self.extension_override_edit = QLineEdit(item.extension_override)
            self.extension_override_edit.setPlaceholderText(tr("advanced.extension_placeholder"))
            self.mimetype_override_edit = QLineEdit(item.mimetype_override)
            self.mimetype_override_edit.setPlaceholderText(tr("advanced.mimetype_placeholder"))
            self.charset_override_edit = QLineEdit(item.charset_override)
            self.charset_override_edit.setPlaceholderText(tr("advanced.charset_placeholder"))
        override_row = QHBoxLayout()
        override_row.addWidget(self.extension_override_edit)
        override_row.addWidget(self.mimetype_override_edit)
        override_row.addWidget(self.charset_override_edit)
        layout.addLayout(override_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to_main_window(self) -> None:
        mw = self.main_window
        mw.enable_plugins = self.enable_plugins_cb.isChecked()
        mw.keep_data_uris = self.keep_data_uris_cb.isChecked()
        mw.docintel_enabled = self.docintel_cb.isChecked()
        mw.docintel_endpoint = self.docintel_endpoint_edit.text()
        mw.cu_enabled = self.cu_cb.isChecked()
        mw.cu_endpoint = self.cu_endpoint_edit.text()
        mw.cu_analyzer_id = self.cu_analyzer_edit.text()
        if self._target_item is not None:
            self._target_item.extension_override = self.extension_override_edit.text()
            self._target_item.mimetype_override = self.mimetype_override_edit.text()
            self._target_item.charset_override = self.charset_override_edit.text()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        i18n_manager.init_from_settings(self.settings)
        i18n_manager.language_changed.connect(self._on_language_changed)

        self.setWindowTitle(tr("window.title"))
        self.resize(1180, 760)

        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers = 0
        self._total_batch = 0

        # Advanced/optional conversion settings (edited via AdvancedSettingsDialog).
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
        self._restore_settings()
        self._apply_theme(self._current_theme_name())
        self._update_drop_zone_prominence()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(layout.contentsMargins().left(), 50, layout.contentsMargins().right(), layout.contentsMargins().bottom())

        self.drop_zone = DropZone(self._add_paths, on_click=self.action_add_files)
        layout.addWidget(self.drop_zone)

        self.supported_types_label = QLabel(tr("dropzone.supported_types"))
        self.supported_types_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.supported_types_label.setWordWrap(True)
        small_font = self.supported_types_label.font()
        small_font.setPointSize(max(small_font.pointSize() - 1, 7))
        self.supported_types_label.setFont(small_font)
        self.supported_types_label.setObjectName("SupportedTypesLabel")
        layout.addWidget(self.supported_types_label)

        add_row = QHBoxLayout()
        self.add_files_btn = QPushButton(tr("button.add_files"))
        self.add_files_btn.setObjectName("secondary")
        self.add_files_btn.clicked.connect(self.action_add_files)
        self.add_folder_btn = QPushButton(tr("button.add_folder"))
        self.add_folder_btn.setObjectName("secondary")
        self.add_folder_btn.clicked.connect(self.action_add_folder)
        add_row.addWidget(self.add_files_btn)
        add_row.addWidget(self.add_folder_btn)
        layout.addLayout(add_row)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("url.placeholder"))
        self.url_edit.returnPressed.connect(self.action_add_url)
        self.add_url_btn = QPushButton(tr("button.add_url"))
        self.add_url_btn.clicked.connect(self.action_add_url)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.add_url_btn)
        layout.addLayout(url_row)

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionResizeMode(0, self.table_view.horizontalHeader().ResizeMode.Stretch)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table_view, 1)

        self.queue_controls_widget = QWidget()
        queue_controls_layout = QVBoxLayout(self.queue_controls_widget)
        queue_controls_layout.setContentsMargins(0, 0, 0, 0)

        queue_btn_row = QHBoxLayout()
        self.remove_btn = QPushButton(tr("button.remove_selected"))
        self.remove_btn.setObjectName("secondary")
        self.remove_btn.clicked.connect(self.action_remove_selected)
        self.clear_btn = QPushButton(tr("button.clear_all"))
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self.action_clear_all)
        queue_btn_row.addWidget(self.remove_btn)
        queue_btn_row.addWidget(self.clear_btn)
        queue_controls_layout.addLayout(queue_btn_row)

        convert_row = QHBoxLayout()
        self.convert_all_btn = QPushButton(tr("button.convert_all"))
        self.convert_all_btn.setObjectName("secondary")
        self.convert_all_btn.clicked.connect(self.action_convert_all)
        self.convert_selected_btn = QPushButton(tr("button.convert_selected"))
        self.convert_selected_btn.setObjectName("secondary")
        self.convert_selected_btn.clicked.connect(self.action_convert_selected)
        convert_row.addWidget(self.convert_all_btn)
        convert_row.addWidget(self.convert_selected_btn)
        queue_controls_layout.addLayout(convert_row)

        layout.addWidget(self.queue_controls_widget)

        # New items convert automatically as soon as they're added, so these
        # buttons are only needed to retry a batch (e.g. after tweaking
        # Advanced Settings for a specific row).

        self.model.rowsInserted.connect(self._update_drop_zone_prominence)
        self.model.rowsRemoved.connect(self._update_drop_zone_prominence)
        self.model.modelReset.connect(self._update_drop_zone_prominence)

        return panel

    def _update_drop_zone_prominence(self, *args) -> None:
        empty = len(self.model.items()) == 0
        self.drop_zone.set_prominent(empty)
        self.table_view.setVisible(not empty)
        self.queue_controls_widget.setVisible(not empty)

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.tabs = QTabWidget()
        self.rendered_view = QTextBrowser()
        self.rendered_view.setOpenExternalLinks(True)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setPlaceholderText(tr("raw.placeholder"))
        font = self.raw_view.font()
        font.setFamily("Consolas")
        font.setPointSize(10)
        self.raw_view.setFont(font)
        self.raw_view.textChanged.connect(self._on_raw_text_changed)

        self.tabs.addTab(self.rendered_view, tr("tab.rendered"))
        self.tabs.addTab(self.raw_view, tr("tab.raw"))
        layout.addWidget(self.tabs, 1)

        self.autosave_note = QLabel(tr("note.autosave"))
        self.autosave_note.setWordWrap(True)
        self.autosave_note.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.autosave_note)

        btn_row = QHBoxLayout()
        self.save_md_btn = QPushButton(tr("button.save_copy_as"))
        self.save_md_btn.setObjectName("secondary")
        self.save_md_btn.clicked.connect(self.action_save_current)
        self.export_all_btn = QPushButton(tr("button.export_all_to"))
        self.export_all_btn.setObjectName("secondary")
        self.export_all_btn.clicked.connect(self.action_export_all)
        self.copy_btn = QPushButton(tr("button.copy_raw"))
        self.copy_btn.setObjectName("secondary")
        self.copy_btn.clicked.connect(self.action_copy_raw)
        btn_row.addWidget(self.save_md_btn)
        btn_row.addWidget(self.export_all_btn)
        btn_row.addWidget(self.copy_btn)
        layout.addLayout(btn_row)

        return panel

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        self.file_menu = menu_bar.addMenu(tr("menu.file"))
        self.add_files_action = self._make_action("menu.add_files", self.action_add_files)
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
        corner_layout = QHBoxLayout(self.language_switcher_widget)
        corner_layout.setContentsMargins(0, 0, 8, 0)
        corner_layout.setSpacing(6)

        self.language_label = QLabel(tr("toolbar.language"))
        corner_layout.addWidget(self.language_label)

        self.language_combo = QComboBox()
        self.language_combo.addItem("English", LANG_EN)
        self.language_combo.addItem("Español", LANG_ES)
        self.language_combo.setCurrentIndex(0 if i18n_manager.language == LANG_EN else 1)
        self.language_combo.currentIndexChanged.connect(self._on_language_combo_changed)
        corner_layout.addWidget(self.language_combo)

        self.menuBar().setCornerWidget(self.language_switcher_widget, Qt.Corner.TopRightCorner)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
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
            app.setStyleSheet(stylesheet_for(theme_name))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.settings.setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------
    def _on_language_combo_changed(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if code:
            i18n_manager.set_language(code, self.settings)

    def _on_language_changed(self, language: str) -> None:
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(0 if language == LANG_EN else 1)
        self.language_combo.blockSignals(False)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Re-pull every user-facing string from tr() so the currently
        visible UI updates immediately, with no restart required."""
        self.setWindowTitle(tr("window.title"))
        self.language_label.setText(tr("toolbar.language"))

        self.drop_zone.retranslate()
        self.supported_types_label.setText(tr("dropzone.supported_types"))
        self.add_files_btn.setText(tr("button.add_files"))
        self.add_folder_btn.setText(tr("button.add_folder"))
        self.url_edit.setPlaceholderText(tr("url.placeholder"))
        self.add_url_btn.setText(tr("button.add_url"))
        self.remove_btn.setText(tr("button.remove_selected"))
        self.clear_btn.setText(tr("button.clear_all"))
        self.convert_all_btn.setText(tr("button.convert_all"))
        self.convert_selected_btn.setText(tr("button.convert_selected"))

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

    # ------------------------------------------------------------------
    # Queue actions
    # ------------------------------------------------------------------
    def action_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("dialog.add_files"))
        if files:
            self._add_paths(files)

    def action_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.add_folder"))
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths: list[str]) -> None:
        added_rows: list[int] = []
        for path in paths:
            if os.path.isdir(path):
                for file_path in iter_supported_files(path):
                    row = self._add_single_file(file_path)
                    if row is not None:
                        added_rows.append(row)
            elif os.path.isfile(path):
                row = self._add_single_file(path)
                if row is not None:
                    added_rows.append(row)
        if added_rows:
            self.status_bar.showMessage(tr("status.added_files", count=len(added_rows)), 4000)
            self._start_conversion(added_rows)

    def _add_single_file(self, path: str) -> Optional[int]:
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
        if not (url.startswith("http://") or url.startswith("https://")):
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
        self._start_conversion([row])

    def action_remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()})
        if rows:
            self.model.remove_rows(rows)

    def action_clear_all(self) -> None:
        self.model.clear()
        self.raw_view.clear()
        self.rendered_view.clear()

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
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
        self._total_batch = len(rows)
        self._active_workers = 0
        self.progress_bar.setMaximum(self._total_batch)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        for row in rows:
            item = self.model.item_at(row)
            if item is None:
                continue
            worker = ConversionWorker(row, item, options)
            worker.signals.started.connect(self._on_conversion_started)
            worker.signals.finished.connect(self._on_conversion_finished)
            worker.signals.failed.connect(self._on_conversion_failed)
            self.thread_pool.start(worker)

    def _on_conversion_started(self, row: int) -> None:
        item = self.model.item_at(row)
        if item is not None:
            item.status = ItemStatus.CONVERTING
            self.model.refresh_row(row)

    def _on_conversion_finished(self, row: int, markdown_text: str) -> None:
        item = self.model.item_at(row)
        if item is not None:
            item.status = ItemStatus.DONE
            item.markdown_result = markdown_text
            item.error_message = ""
            self._auto_save_to_downloads(item)
            self.model.refresh_row(row)
            selected_row = self._selected_row()
            if selected_row == row:
                self._show_item_preview(item)
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
        self._advance_progress()
        self.status_bar.showMessage(tr("status.conversion_failed", message=message), 5000)

    def _advance_progress(self) -> None:
        self._active_workers += 1
        self.progress_bar.setValue(self._active_workers)
        if self._active_workers >= self._total_batch:
            self.status_bar.showMessage(tr("status.batch_complete"), 4000)
            self.progress_bar.setVisible(False)

    # ------------------------------------------------------------------
    # Selection / preview
    # ------------------------------------------------------------------
    def _selected_row(self) -> int:
        rows = self.table_view.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _on_selection_changed(self) -> None:
        row = self._selected_row()
        item = self.model.item_at(row)
        if item is None:
            return
        self._show_item_preview(item)

    def _on_row_double_clicked(self, index) -> None:
        item = self.model.item_at(index.row())
        if item is not None and item.saved_path:
            self._open_containing_folder(item.saved_path)

    def _open_containing_folder(self, path: str) -> None:
        normalized = os.path.normpath(path)
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["explorer", "/select,", normalized], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", normalized], check=False)
            else:
                subprocess.run(["xdg-open", os.path.dirname(normalized)], check=False)
        except OSError:
            pass

    def _show_item_preview(self, item: QueueItem) -> None:
        text = item.markdown_result or ""
        self.raw_view.blockSignals(True)
        self.raw_view.setPlainText(text)
        self.raw_view.blockSignals(False)
        self._render_markdown(text)

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

    # ------------------------------------------------------------------
    # Save / export
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Misc dialogs
    # ------------------------------------------------------------------
    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _show_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(self, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_to_main_window()
