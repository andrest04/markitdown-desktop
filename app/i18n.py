"""Lightweight, dependency-free English/Spanish i18n.

No Qt Linguist toolchain (no .ts/.qm files, nothing to compile). Just two
plain dictionaries of key -> translated string, a small manager that tracks
the current language and persists it via QSettings, and a `tr()` lookup
that never raises -- an unknown key falls back to the English string, and
if even that is missing, the key itself is returned so the UI never
crashes over a translation typo.

Widgets that need to update live when the language changes should connect
to `i18n.manager.language_changed` and re-pull their text from `tr()` in a
`retranslate_ui()`-style method.
"""
from __future__ import annotations

from PySide6.QtCore import QLocale, QObject, QSettings, Signal

LANG_EN = "en"
LANG_ES = "es"
SUPPORTED_LANGUAGES = (LANG_EN, LANG_ES)

SETTINGS_KEY = "language/code"


TRANSLATIONS: dict[str, dict[str, str]] = {
    LANG_EN: {
        # Window
        "window.title": "MarkItDown Desktop",
        "status.ready": "Ready",
        "toolbar.language": "Language:",

        # Drop zone
        "dropzone.empty": "Drop a file here",
        "dropzone.filled": "Drop more files here",
        "dropzone.title.empty": "Drop a file",
        "dropzone.title.filled": "Drop more files",
        "dropzone.hint.empty": "Or paste a webpage / YouTube URL",
        "dropzone.saves_to": "Saves to Downloads automatically, no extra step",
        "dropzone.browse": "Browse files",
        "dropzone.add_folder": "Add folder",
        "dropzone.supported_types": (
            "Supports: PDF, Word, Excel, PowerPoint, images, audio, HTML, ZIP, "
            "YouTube / web URLs, and more"
        ),

        # Left panel
        "button.add_files": "Add files",
        "button.add_folder": "Add folder",
        "url.placeholder": "https://example.com or a YouTube link",
        "button.add_url": "Convert",
        "button.remove_selected": "Remove",
        "button.clear_all": "Clear queue",
        "button.convert_all": "Retry all",
        "button.convert_selected": "Retry selected",
        "button.open_folder": "Show in folder",
        "button.open_file": "Open",
        "banner.saved": "Saved {name} to Downloads",

        # Right panel
        "tab.rendered": "Preview",
        "tab.raw": "Markdown",
        "raw.placeholder": "Converted Markdown will appear here",
        "note.autosave": "Already saved to Downloads. These just keep another copy.",
        "button.save_copy_as": "Save a copy…",
        "button.export_all_to": "Export all…",
        "button.copy_raw": "Copy Markdown",
        "preview.empty": "Nothing to preview yet",
        "preview.empty.hint": "Drop a file. Conversion starts on its own.",
        "preview.converting": "Converting…",
        "preview.pending": "Waiting to convert",
        "preview.failed": "Conversion failed",

        # Menu
        "menu.file": "&File",
        "menu.edit": "&Edit",
        "menu.view": "&View",
        "menu.help": "&Help",
        "menu.add_files": "Add files",
        "menu.add_folder": "Add folder",
        "menu.add_url": "Add URL",
        "menu.save_copy_as": "Save a copy as...",
        "menu.export_all_to": "Export all to...",
        "menu.exit": "Exit",
        "menu.advanced_settings": "Advanced Settings...",
        "menu.retry": "Retry conversion",
        "menu.retry_all": "Retry all",
        "menu.open_folder": "Show in folder",
        "menu.open_file": "Open file",
        "menu.remove": "Remove",
        "menu.theme_system": "Follow system theme",
        "menu.theme_light": "Light theme",
        "menu.theme_dark": "Dark theme",
        "menu.about": "About",
        "menu.github": "markitdown on GitHub",
        "menu.language": "&Language",

        # Table headers
        "column.name": "Name / URL",
        "column.type": "Type",
        "column.status": "Status",

        # Detected type labels (only the language-dependent ones; file
        # extensions like "PDF" and brand names like "YouTube" are passed
        # through unchanged -- tr() falls back to the raw value for those).
        "type.webpage": "Webpage",
        "type.file": "File",

        # Item status
        "status.pending": "Pending",
        "status.converting": "Converting",
        "status.done": "Done",
        "status.error": "Error",
        "status.done_saved": "Saved to Downloads",
        "status.done_save_failed": "Done, auto-save failed",
        "status.pill.saved": "Saved",
        "status.pill.converting": "Converting",
        "status.pill.error": "Failed",
        "status.pill.pending": "Waiting",
        "status.pill.save_failed": "Save failed",
        "tooltip.saved_to": "Saved to {path}\nDouble-click to open the file.",
        "status.file_missing": "The saved file is no longer there",
        "tooltip.save_failed": "Converted successfully, but auto-save failed: {error}",

        # File dialogs
        "dialog.add_files": "Add files",
        "dialog.add_folder": "Add folder",
        "dialog.save_copy_as": "Save a copy as",
        "dialog.choose_export_folder": "Choose export folder",
        "filter.markdown": "Markdown (*.md)",
        "filter.supported": "Compatible files",

        # Message boxes
        "msgbox.invalid_url.title": "Invalid URL",
        "msgbox.invalid_url.text": "Please enter a URL starting with http:// or https://",
        "msgbox.no_selection.title": "No selection",
        "msgbox.no_selection.text": "Select one or more rows first.",
        "msgbox.nothing_to_save.title": "Nothing to save",
        "msgbox.nothing_to_save.text": "Select a converted item first.",
        "msgbox.nothing_to_export.title": "Nothing to export",
        "msgbox.nothing_to_export.text": "No successfully converted items yet.",
        "msgbox.unsupported.title": "No compatible files",
        "msgbox.unsupported.text": "This app converts documents such as PDF, Word, Excel, PowerPoint, images, HTML, and similar files. Executables and other file types are not shown.",
        "status.skipped_unsupported": "Skipped {count} unsupported file(s).",

        # Status bar messages
        "status.added_files": "Added {count} file(s) to the queue, converting...",
        "status.url_already_queued": "URL already in the queue",
        "status.saved_to": "Saved to {path}",
        "status.autosave_failed": "Converted, but auto-save to Downloads failed: {error}",
        "status.conversion_failed": "Conversion failed: {message}",
        "status.batch_complete": "Batch conversion complete",
        "status.saved_copy_to": "Saved a copy to {path}",
        "status.exported": "Exported {count} file(s) to {folder}",
        "status.copied_raw": "Raw markdown copied to clipboard",

        # About dialog
        "about.title": "About MarkItDown Desktop",
        "about.heading": "<b>MarkItDown Desktop</b>",
        "about.markitdown_version": "markitdown package version: {version}",
        "about.description": "A personal desktop GUI around Microsoft's markitdown.",

        # Advanced settings dialog
        "advanced.title": "Advanced Settings",
        "advanced.conversion_options": "<b>Conversion options</b>",
        "advanced.enable_plugins": "Enable plugins (enable_plugins)",
        "advanced.keep_data_uris": "Keep data URIs in output (keep_data_uris)",
        "advanced.enable_docintel": "Enable Azure Document Intelligence (docintel_endpoint)",
        "advanced.docintel_placeholder": "https://<resource>.cognitiveservices.azure.com/",
        "advanced.enable_cu": "Enable Azure Content Understanding (cu_endpoint)",
        "advanced.cu_endpoint_placeholder": "Content Understanding endpoint (cu_endpoint)",
        "advanced.cu_analyzer_placeholder": "Analyzer ID, optional (cu_analyzer_id)",
        "advanced.per_item_hints": "<b>Per-item conversion hints</b>",
        "advanced.select_row_first": "Select a row in the queue first to set extension/mimetype/charset hints for it.",
        "advanced.applies_to": "Applies to: {name}",
        "advanced.extension_placeholder": "extension e.g. .pdf",
        "advanced.mimetype_placeholder": "mimetype e.g. text/html",
        "advanced.charset_placeholder": "charset e.g. utf-8",
    },
    LANG_ES: {
        # Window
        "window.title": "MarkItDown Desktop",
        "status.ready": "Listo",
        "toolbar.language": "Idioma:",

        # Drop zone
        "dropzone.empty": "Suelte un archivo aquí",
        "dropzone.filled": "Suelte más archivos aquí",
        "dropzone.title.empty": "Suelte un archivo",
        "dropzone.title.filled": "Suelte más archivos",
        "dropzone.hint.empty": "O pegue una URL web / de YouTube",
        "dropzone.saves_to": "Se guarda en Descargas automáticamente, sin pasos extra",
        "dropzone.browse": "Buscar archivos",
        "dropzone.add_folder": "Agregar carpeta",
        "dropzone.supported_types": (
            "Soporta: PDF, Word, Excel, PowerPoint, imágenes, audio, HTML, ZIP, "
            "URLs de YouTube / web, y más"
        ),

        # Left panel
        "button.add_files": "Agregar archivos",
        "button.add_folder": "Agregar carpeta",
        "url.placeholder": "https://ejemplo.com o un enlace de YouTube",
        "button.add_url": "Convertir",
        "button.remove_selected": "Quitar",
        "button.clear_all": "Vaciar cola",
        "button.convert_all": "Reintentar todo",
        "button.convert_selected": "Reintentar seleccionados",
        "button.open_folder": "Mostrar en carpeta",
        "button.open_file": "Abrir",
        "banner.saved": "Se guardó {name} en Descargas",

        # Right panel
        "tab.rendered": "Vista previa",
        "tab.raw": "Markdown",
        "raw.placeholder": "El Markdown convertido aparecerá aquí",
        "note.autosave": "Ya está en Descargas. Esto solo guarda otra copia.",
        "button.save_copy_as": "Guardar una copia…",
        "button.export_all_to": "Exportar todo…",
        "button.copy_raw": "Copiar Markdown",
        "preview.empty": "Todavía no hay vista previa",
        "preview.empty.hint": "Suelte un archivo. La conversión empieza sola.",
        "preview.converting": "Convirtiendo…",
        "preview.pending": "En espera",
        "preview.failed": "Falló la conversión",

        # Menu
        "menu.file": "&Archivo",
        "menu.edit": "&Editar",
        "menu.view": "&Ver",
        "menu.help": "A&yuda",
        "menu.add_files": "Agregar archivos",
        "menu.add_folder": "Agregar carpeta",
        "menu.add_url": "Agregar URL",
        "menu.save_copy_as": "Guardar una copia como...",
        "menu.export_all_to": "Exportar todo a...",
        "menu.exit": "Salir",
        "menu.advanced_settings": "Configuración avanzada...",
        "menu.retry": "Reintentar conversión",
        "menu.retry_all": "Reintentar todo",
        "menu.open_folder": "Mostrar en carpeta",
        "menu.open_file": "Abrir archivo",
        "menu.remove": "Quitar",
        "menu.theme_system": "Seguir el tema del sistema",
        "menu.theme_light": "Tema claro",
        "menu.theme_dark": "Tema oscuro",
        "menu.about": "Acerca de",
        "menu.github": "markitdown en GitHub",
        "menu.language": "&Idioma",

        # Table headers
        "column.name": "Nombre / URL",
        "column.type": "Tipo",
        "column.status": "Estado",

        "type.webpage": "Página web",
        "type.file": "Archivo",

        # Item status
        "status.pending": "Pendiente",
        "status.converting": "Convirtiendo",
        "status.done": "Listo",
        "status.error": "Error",
        "status.done_saved": "Guardado en Descargas",
        "status.done_save_failed": "Listo, falló el guardado automático",
        "status.pill.saved": "Guardado",
        "status.pill.converting": "Convirtiendo",
        "status.pill.error": "Falló",
        "status.pill.pending": "En espera",
        "status.pill.save_failed": "No se guardó",
        "tooltip.saved_to": "Guardado en {path}\nHaga doble clic para abrir el archivo.",
        "status.file_missing": "El archivo guardado ya no está",
        "tooltip.save_failed": "Convertido correctamente, pero falló el guardado automático: {error}",

        # File dialogs
        "dialog.add_files": "Agregar archivos",
        "dialog.add_folder": "Agregar carpeta",
        "dialog.save_copy_as": "Guardar una copia como",
        "dialog.choose_export_folder": "Elija la carpeta de exportación",
        "filter.markdown": "Markdown (*.md)",
        "filter.supported": "Archivos compatibles",

        # Message boxes
        "msgbox.invalid_url.title": "URL inválida",
        "msgbox.invalid_url.text": "Ingrese una URL que empiece con http:// o https://",
        "msgbox.no_selection.title": "Sin selección",
        "msgbox.no_selection.text": "Seleccione una o más filas primero.",
        "msgbox.nothing_to_save.title": "Nada para guardar",
        "msgbox.nothing_to_save.text": "Seleccione primero un elemento convertido.",
        "msgbox.nothing_to_export.title": "Nada para exportar",
        "msgbox.nothing_to_export.text": "Todavía no hay elementos convertidos con éxito.",
        "msgbox.unsupported.title": "No hay archivos compatibles",
        "msgbox.unsupported.text": "Esta aplicación convierte documentos como PDF, Word, Excel, PowerPoint, imágenes, HTML y archivos similares. Los ejecutables y otros tipos no se muestran.",
        "status.skipped_unsupported": "Se omitieron {count} archivo(s) no compatibles.",

        # Status bar messages
        "status.added_files": "Se agregaron {count} archivo(s) a la cola, convirtiendo...",
        "status.url_already_queued": "La URL ya está en la cola",
        "status.saved_to": "Guardado en {path}",
        "status.autosave_failed": "Convertido, pero falló el guardado automático en Descargas: {error}",
        "status.conversion_failed": "Falló la conversión: {message}",
        "status.batch_complete": "Conversión por lotes completa",
        "status.saved_copy_to": "Copia guardada en {path}",
        "status.exported": "Se exportaron {count} archivo(s) a {folder}",
        "status.copied_raw": "Markdown sin formato copiado al portapapeles",

        # About dialog
        "about.title": "Acerca de MarkItDown Desktop",
        "about.heading": "<b>MarkItDown Desktop</b>",
        "about.markitdown_version": "Versión del paquete markitdown: {version}",
        "about.description": "Una interfaz de escritorio personal para markitdown de Microsoft.",

        # Advanced settings dialog
        "advanced.title": "Configuración avanzada",
        "advanced.conversion_options": "<b>Opciones de conversión</b>",
        "advanced.enable_plugins": "Habilitar plugins (enable_plugins)",
        "advanced.keep_data_uris": "Mantener URIs de datos en la salida (keep_data_uris)",
        "advanced.enable_docintel": "Habilitar Azure Document Intelligence (docintel_endpoint)",
        "advanced.docintel_placeholder": "https://<recurso>.cognitiveservices.azure.com/",
        "advanced.enable_cu": "Habilitar Azure Content Understanding (cu_endpoint)",
        "advanced.cu_endpoint_placeholder": "Endpoint de Content Understanding (cu_endpoint)",
        "advanced.cu_analyzer_placeholder": "ID del analizador, opcional (cu_analyzer_id)",
        "advanced.per_item_hints": "<b>Pistas de conversión por elemento</b>",
        "advanced.select_row_first": "Seleccione primero una fila en la cola para configurar pistas de extensión/mimetype/charset para ella.",
        "advanced.applies_to": "Aplica a: {name}",
        "advanced.extension_placeholder": "extensión, ej. .pdf",
        "advanced.mimetype_placeholder": "mimetype, ej. text/html",
        "advanced.charset_placeholder": "charset, ej. utf-8",
    },
}


def detect_system_language() -> str:
    """Spanish for es_* system locales, English otherwise."""
    try:
        locale_name = QLocale.system().name()  # e.g. "es_AR", "en_US"
    except Exception:  # noqa: BLE001 -- locale detection must never crash startup
        return LANG_EN
    if locale_name.lower().startswith("es"):
        return LANG_ES
    return LANG_EN


class TranslationManager(QObject):
    """Tracks the current language, persists it, and resolves keys.

    `language_changed` is emitted whenever the language changes so widgets
    can retranslate themselves immediately (no restart required).
    """

    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._language = LANG_EN

    @property
    def language(self) -> str:
        return self._language

    def init_from_settings(self, settings: QSettings) -> None:
        """Load a persisted language choice, falling back to system locale."""
        stored = settings.value(SETTINGS_KEY, None)
        if isinstance(stored, str) and stored in SUPPORTED_LANGUAGES:
            self._language = stored
        else:
            self._language = detect_system_language()

    def set_language(self, language: str, settings: QSettings | None = None) -> None:
        if language not in SUPPORTED_LANGUAGES:
            language = LANG_EN
        if language == self._language:
            return
        self._language = language
        if settings is not None:
            settings.setValue(SETTINGS_KEY, language)
        self.language_changed.emit(language)

    def tr(self, key: str, **kwargs) -> str:
        table = TRANSLATIONS.get(self._language, {})
        template = table.get(key)
        if template is None:
            # Fall back to English, then to the raw key -- never crash on a
            # missing/mistyped translation key.
            template = TRANSLATIONS.get(LANG_EN, {}).get(key, key)
        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, IndexError):
                return template
        return template


manager = TranslationManager()


def tr(key: str, **kwargs) -> str:
    return manager.tr(key, **kwargs)
