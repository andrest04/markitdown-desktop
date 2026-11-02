"""Secondary, opt-in dialog for the markitdown power-user options."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from app.core.converter import ConversionOptions
from app.core.queue_model import QueueItem
from app.i18n import tr


class AdvancedSettingsDialog(QDialog):
    """Secondary, opt-in dialog for the markitdown power-user options.

    Kept out of the main window on purpose: the primary flow is
    "drop a file or paste a URL, done" -- these fields (plugins, Azure
    Document Intelligence / Content Understanding, per-item stream-info
    hints) are for the rare cases that need them.

    Takes the current options and the item the hints apply to (None when no
    row is selected). On accept, the caller reads `selected_options()` and
    calls `apply_item_overrides()`.
    """

    def __init__(self, options: ConversionOptions, target_item: QueueItem | None = None, parent=None):
        super().__init__(parent)
        self._options = options
        self._target_item = target_item
        self.setWindowTitle(tr("advanced.title"))
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel(tr("advanced.conversion_options")))
        self.enable_plugins_cb = QCheckBox(tr("advanced.enable_plugins"))
        self.enable_plugins_cb.setChecked(options.enable_plugins)
        layout.addWidget(self.enable_plugins_cb)

        self.keep_data_uris_cb = QCheckBox(tr("advanced.keep_data_uris"))
        self.keep_data_uris_cb.setChecked(options.keep_data_uris)
        layout.addWidget(self.keep_data_uris_cb)

        self.docintel_cb = QCheckBox(tr("advanced.enable_docintel"))
        self.docintel_cb.setChecked(options.docintel_enabled)
        layout.addWidget(self.docintel_cb)
        self.docintel_endpoint_edit = QLineEdit(options.docintel_endpoint)
        self.docintel_endpoint_edit.setPlaceholderText(tr("advanced.docintel_placeholder"))
        layout.addWidget(self.docintel_endpoint_edit)

        self.cu_cb = QCheckBox(tr("advanced.enable_cu"))
        self.cu_cb.setChecked(options.cu_enabled)
        layout.addWidget(self.cu_cb)
        self.cu_endpoint_edit = QLineEdit(options.cu_endpoint)
        self.cu_endpoint_edit.setPlaceholderText(tr("advanced.cu_endpoint_placeholder"))
        layout.addWidget(self.cu_endpoint_edit)
        self.cu_analyzer_edit = QLineEdit(options.cu_analyzer_id)
        self.cu_analyzer_edit.setPlaceholderText(tr("advanced.cu_analyzer_placeholder"))
        layout.addWidget(self.cu_analyzer_edit)

        layout.addSpacing(10)
        layout.addWidget(QLabel(tr("advanced.per_item_hints")))
        item = target_item
        if item is None:
            select_first = QLabel(tr("advanced.select_row_first"))
            select_first.setWordWrap(True)
            layout.addWidget(select_first)
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
        layout.addSpacing(10)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("advanced.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel"))
        for button in buttons.buttons():
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # No ring on open: focus lands on a control once the keyboard moves it.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFocus()

    def selected_options(self) -> ConversionOptions:
        """The options as edited, as a new value; the input is left untouched."""
        return replace(
            self._options,
            enable_plugins=self.enable_plugins_cb.isChecked(),
            keep_data_uris=self.keep_data_uris_cb.isChecked(),
            docintel_enabled=self.docintel_cb.isChecked(),
            docintel_endpoint=self.docintel_endpoint_edit.text(),
            cu_enabled=self.cu_cb.isChecked(),
            cu_endpoint=self.cu_endpoint_edit.text(),
            cu_analyzer_id=self.cu_analyzer_edit.text(),
        )

    def apply_item_overrides(self) -> None:
        if self._target_item is not None:
            self._target_item.extension_override = self.extension_override_edit.text()
            self._target_item.mimetype_override = self.mimetype_override_edit.text()
            self._target_item.charset_override = self.charset_override_edit.text()
