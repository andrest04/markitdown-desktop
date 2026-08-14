"""Secondary, opt-in dialog for the markitdown power-user options."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from app.i18n import tr

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


class AdvancedSettingsDialog(QDialog):
    """Secondary, opt-in dialog for the markitdown power-user options.

    Kept out of the main window on purpose: the primary flow is
    "drop a file or paste a URL, done" -- these fields (plugins, Azure
    Document Intelligence / Content Understanding, per-item stream-info
    hints) are for the rare cases that need them.
    """

    def __init__(self, main_window: MainWindow, parent=None):
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
