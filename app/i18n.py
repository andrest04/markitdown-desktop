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

        # Drop zone
        "dropzone.title.empty": "Drop a document anywhere",
        "dropzone.saves_to": "The Markdown saves to Downloads on its own.",
        "dropzone.url_label": "Or paste a link",
        "dropzone.formats": "Works with PDF, Word, Excel, PowerPoint, images, audio, HTML, ZIP and web pages.",
        "overlay.drop": "Drop to convert",

        # Left panel
        "button.add_files": "Add files",
        "button.add_folder": "Add folder",
        "url.placeholder": "https://example.com or a YouTube link",
        "url.placeholder.filled": "Paste a link",
        "button.add_url": "Convert",
        "button.clear_all": "Clear list",
        "button.open_folder": "Show in folder",
        "button.open_file": "Open file",
        "button.more": "More",
        "button.copied": "Copied",

        # Right panel
        "tab.rendered": "Preview",
        "tab.raw": "Markdown",
        "raw.placeholder": "Converted Markdown will appear here",
        "button.copy_raw": "Copy Markdown",
        "preview.empty.hint": "Select a file in the list to see its Markdown.",
        "preview.converting.hint": "The Markdown appears here when it is ready. Large files can take a few minutes.",
        "preview.pending.hint": "Conversion starts on its own when the files ahead of it finish.",
        "preview.failed.hint": "Retry the conversion, or check that the file opens in its own app.",
        "preview.no_text": "The conversion found no text in this file.",
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
        "menu.add_url": "Add link",
        "menu.save_copy_as": "Save a copy…",
        "menu.export_all_to": "Export all…",
        "menu.exit": "Exit",
        "menu.advanced_settings": "Advanced settings…",
        "menu.retry": "Retry conversion",
        "menu.open_folder": "Show in folder",
        "menu.open_file": "Open file",
        "menu.remove": "Remove",
        "menu.theme_system": "Follow system theme",
        "menu.theme_light": "Light theme",
        "menu.theme_dark": "Dark theme",
        "menu.about": "About",
        "menu.github": "markitdown on GitHub",

        # Table headers
        "column.name": "Name or link",
        "column.type": "Type",
        "column.status": "Status",

        # Detected type labels (only the language-dependent ones; file
        # extensions like "PDF" and brand names like "YouTube" are passed
        # through unchanged -- tr() falls back to the raw value for those).
        "type.webpage": "Webpage",
        "type.file": "File",

        "a11y.queue": "Files to convert",
        "advanced.save": "Save settings",
        "button.cancel": "Cancel",
        "button.close": "Close",
        # Item status
        "status.pending": "Waiting",
        "status.converting": "Converting",
        "status.done": "Converted",
        "status.error": "Failed",
        "status.done_saved": "Saved to Downloads",
        "status.done_save_failed": "Converted, not saved",
        "status.save_failed_detail": "Converted, but could not save to Downloads: {error}",
        "status.file_missing": "The saved file is no longer in that folder. It may have been moved or deleted.",
        "tooltip.save_failed": "Converted successfully, but auto-save failed: {error}",

        # File dialogs
        "dialog.add_files": "Add files",
        "dialog.add_folder": "Add folder",
        "dialog.save_copy_as": "Save a copy",
        "dialog.choose_export_folder": "Export all to a folder",
        "filter.markdown": "Markdown (*.md)",
        "filter.supported": "Compatible files",

        # Message boxes
        "msgbox.invalid_url.title": "That link cannot be converted",
        "msgbox.invalid_url.text": "Enter a link that starts with http:// or https://.",
        "msgbox.no_selection.title": "No selection",
        "msgbox.no_selection.text": "Select a file in the list first.",
        "msgbox.nothing_to_save.title": "Nothing to save",
        "msgbox.nothing_to_save.text": "Select a converted file in the list first.",
        "msgbox.nothing_to_export.title": "Nothing to export",
        "msgbox.nothing_to_export.text": "No files have been converted yet.",
        "msgbox.export_failed.title": "Export incomplete",
        "msgbox.export_failed.text": "{count} file(s) could not be exported:\n{details}",
        "msgbox.save_copy_failed.title": "Could not save the copy",
        "msgbox.save_copy_failed.text": "The copy could not be saved: {error}",
        "msgbox.unsupported.title": "No compatible files",
        "msgbox.unsupported.text": "None of these files can be converted. Try a document such as a PDF, Word, Excel or PowerPoint file, an image, or HTML.",
        "status.skipped_unsupported": "Skipped {count} unsupported file(s).",

        # Status bar messages
        "status.added_files": "Converting {count} file(s)",
        "status.url_already_queued": "That link is already in the list",
        "status.saved_to": "Saved to {path}",
        "status.autosave_failed": "Converted, but could not save to Downloads: {error}",
        "status.conversion_failed": "Conversion failed: {message}",
        "status.batch_complete": "All conversions finished",
        "status.batch_complete_problems": "All conversions finished, {summary}",
        "status.saved_copy_to": "Saved a copy to {path}",
        "status.exported": "Exported {count} file(s) to {folder}",
        "status.copied_raw": "Markdown copied",
        "status.saved_as": "Saved as {name} in Downloads",
        "detail.words.one": "{count} word",
        "detail.words.other": "{count} words",
        "status.failed_reason": "Failed: {reason}",
        "status.not_saved_reason": "Not saved: {reason}",

        # Why something failed. Lower case: they follow "Failed:" on a row and
        # are capitalized where they stand alone.
        "error.unsupported_format": "unsupported format",
        "error.missing_dependency": "missing component",
        "error.unreadable_file": "damaged or unreadable file",
        "error.file_not_found": "file not found",
        "error.permission_denied": "permission denied",
        "error.network": "connection or link unavailable",
        "error.no_text": "no text found",
        "error.generic": "conversion error",
        "error.disk_full": "disk full",
        "error.save_generic": "write error",
        "statusbar.saving_to": "Saving to {path}",

        # Queue summary: what needs attention first, then what is ready
        "summary.failed.one": "1 failed",
        "summary.failed.other": "{count} failed",
        "summary.not_saved.one": "1 not saved",
        "summary.not_saved.other": "{count} not saved",
        "summary.ready.one": "1 ready",
        "summary.ready.other": "{count} ready",
        "summary.converting.one": "1 converting",
        "summary.converting.other": "{count} converting",
        "summary.waiting.one": "1 waiting",
        "summary.waiting.other": "{count} waiting",
        "summary.ready_of": "{ready} of {total} ready",
        "summary.all_saved.one": "1 saved to Downloads",
        "summary.all_saved.other": "All {count} saved to Downloads",
        "button.retry_row": "Retry",
        "row.retry_hint": "Press Enter to retry",

        # About dialog
        "about.title": "About MarkItDown Desktop",
        "about.heading": "<b>MarkItDown Desktop</b>",
        "about.markitdown_version": "markitdown package version {version}",
        "about.description": "A personal desktop GUI around Microsoft's markitdown.",

        # Advanced settings dialog
        "advanced.title": "Advanced settings",
        "advanced.conversion_options": "<b>Conversion options</b>",
        "advanced.enable_plugins": "Enable plugins (enable_plugins)",
        "advanced.keep_data_uris": "Keep data URIs in output (keep_data_uris)",
        "advanced.enable_docintel": "Enable Azure Document Intelligence (docintel_endpoint)",
        "advanced.docintel_placeholder": "https://<resource>.cognitiveservices.azure.com/",
        "advanced.enable_cu": "Enable Azure Content Understanding (cu_endpoint)",
        "advanced.cu_endpoint_placeholder": "Content Understanding endpoint (cu_endpoint)",
        "advanced.cu_analyzer_placeholder": "Analyzer ID, optional (cu_analyzer_id)",
        "advanced.per_item_hints": "<b>Hints for the selected file</b>",
        "advanced.select_row_first": "Select a file in the list first to set an extension, mimetype or charset for it.",
        "advanced.applies_to": "Applies to: {name}",
        "advanced.extension_placeholder": "Extension (.pdf)",
        "advanced.mimetype_placeholder": "Mimetype (text/html)",
        "advanced.charset_placeholder": "Charset (utf-8)",
    },
    LANG_ES: {
        # Window
        "window.title": "MarkItDown Desktop",

        # Drop zone
        "dropzone.title.empty": "Suelte un documento en cualquier lugar",
        "dropzone.saves_to": "El Markdown se guarda en Descargas automáticamente.",
        "dropzone.url_label": "O pegue un enlace",
        "dropzone.formats": "Funciona con PDF, Word, Excel, PowerPoint, imágenes, audio, HTML, ZIP y páginas web.",
        "overlay.drop": "Suelte para convertir",

        # Left panel
        "button.add_files": "Agregar archivos",
        "button.add_folder": "Agregar carpeta",
        "url.placeholder": "https://ejemplo.com o un enlace de YouTube",
        "url.placeholder.filled": "Pegue un enlace",
        "button.add_url": "Convertir",
        "button.clear_all": "Vaciar lista",
        "button.open_folder": "Ver en carpeta",
        "button.open_file": "Abrir archivo",
        "button.more": "Más",
        "button.copied": "Copiado",

        # Right panel
        "tab.rendered": "Vista previa",
        "tab.raw": "Markdown",
        "raw.placeholder": "El Markdown convertido aparecerá aquí",
        "button.copy_raw": "Copiar Markdown",
        "preview.empty.hint": "Seleccione un archivo de la lista para ver su Markdown.",
        "preview.converting.hint": "El Markdown aparecerá aquí cuando esté listo. Los archivos grandes pueden tardar unos minutos.",
        "preview.pending.hint": "La conversión empieza sola cuando terminen los archivos anteriores.",
        "preview.failed.hint": "Reintente la conversión o compruebe que el archivo se abre en su aplicación.",
        "preview.no_text": "La conversión no encontró texto en este archivo.",
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
        "menu.add_url": "Agregar enlace",
        "menu.save_copy_as": "Guardar una copia…",
        "menu.export_all_to": "Exportar todo…",
        "menu.exit": "Salir",
        "menu.advanced_settings": "Configuración avanzada…",
        "menu.retry": "Reintentar conversión",
        "menu.open_folder": "Ver en carpeta",
        "menu.open_file": "Abrir archivo",
        "menu.remove": "Quitar",
        "menu.theme_system": "Seguir el tema del sistema",
        "menu.theme_light": "Tema claro",
        "menu.theme_dark": "Tema oscuro",
        "menu.about": "Acerca de",
        "menu.github": "markitdown en GitHub",

        # Table headers
        "column.name": "Nombre o enlace",
        "column.type": "Tipo",
        "column.status": "Estado",

        "type.webpage": "Página web",
        "type.file": "Archivo",

        "a11y.queue": "Archivos para convertir",
        "advanced.save": "Guardar configuración",
        "button.cancel": "Cancelar",
        "button.close": "Cerrar",
        # Item status
        "status.pending": "En espera",
        "status.converting": "Convirtiendo",
        "status.done": "Convertido",
        "status.error": "Falló",
        "status.done_saved": "Guardado en Descargas",
        "status.done_save_failed": "Convertido, sin guardar",
        "status.save_failed_detail": "Convertido, pero no se pudo guardar en Descargas: {error}",
        "status.file_missing": "El archivo guardado ya no está en esa carpeta. Puede haberse movido o eliminado.",
        "tooltip.save_failed": "Convertido correctamente, pero falló el guardado automático: {error}",

        # File dialogs
        "dialog.add_files": "Agregar archivos",
        "dialog.add_folder": "Agregar carpeta",
        "dialog.save_copy_as": "Guardar una copia",
        "dialog.choose_export_folder": "Exportar todo a una carpeta",
        "filter.markdown": "Markdown (*.md)",
        "filter.supported": "Archivos compatibles",

        # Message boxes
        "msgbox.invalid_url.title": "Ese enlace no se puede convertir",
        "msgbox.invalid_url.text": "Escriba un enlace que empiece con http:// o https://.",
        "msgbox.no_selection.title": "Sin selección",
        "msgbox.no_selection.text": "Seleccione primero un archivo de la lista.",
        "msgbox.nothing_to_save.title": "Nada para guardar",
        "msgbox.nothing_to_save.text": "Seleccione primero un archivo convertido de la lista.",
        "msgbox.nothing_to_export.title": "Nada para exportar",
        "msgbox.nothing_to_export.text": "Todavía no se ha convertido ningún archivo.",
        "msgbox.export_failed.title": "Exportación incompleta",
        "msgbox.export_failed.text": "No se pudieron exportar {count} archivo(s):\n{details}",
        "msgbox.save_copy_failed.title": "No se pudo guardar la copia",
        "msgbox.save_copy_failed.text": "La copia no se pudo guardar: {error}",
        "msgbox.unsupported.title": "No hay archivos compatibles",
        "msgbox.unsupported.text": "Ninguno de estos archivos se puede convertir. Pruebe con un documento como un PDF, un archivo de Word, Excel o PowerPoint, una imagen o HTML.",
        "status.skipped_unsupported": "Se omitieron {count} archivo(s) no compatibles.",

        # Status bar messages
        "status.added_files": "Convirtiendo {count} archivo(s)",
        "status.url_already_queued": "Ese enlace ya está en la lista",
        "status.saved_to": "Guardado en {path}",
        "status.autosave_failed": "Convertido, pero no se pudo guardar en Descargas: {error}",
        "status.conversion_failed": "Falló la conversión: {message}",
        "status.batch_complete": "Terminaron todas las conversiones",
        "status.batch_complete_problems": "Terminaron todas las conversiones, {summary}",
        "status.saved_copy_to": "Copia guardada en {path}",
        "status.exported": "Se exportaron {count} archivo(s) a {folder}",
        "status.copied_raw": "Markdown copiado",
        "status.saved_as": "Guardado como {name} en Descargas",
        "detail.words.one": "{count} palabra",
        "detail.words.other": "{count} palabras",
        "status.failed_reason": "Falló: {reason}",
        "status.not_saved_reason": "Sin guardar: {reason}",

        # Por qué falló algo. En minúscula: siguen a "Falló:" en una fila y se
        # escriben con mayúscula inicial cuando van solos.
        "error.unsupported_format": "formato no compatible",
        "error.missing_dependency": "falta un componente",
        "error.unreadable_file": "archivo dañado o ilegible",
        "error.file_not_found": "archivo no encontrado",
        "error.permission_denied": "permiso denegado",
        "error.network": "conexión o enlace no disponible",
        "error.no_text": "no se encontró texto",
        "error.generic": "error de conversión",
        "error.disk_full": "disco lleno",
        "error.save_generic": "error de escritura",
        "statusbar.saving_to": "Guardando en {path}",

        # Queue summary: what needs attention first, then what is ready
        "summary.failed.one": "1 falló",
        "summary.failed.other": "{count} fallaron",
        "summary.not_saved.one": "1 sin guardar",
        "summary.not_saved.other": "{count} sin guardar",
        "summary.ready.one": "1 listo",
        "summary.ready.other": "{count} listos",
        "summary.converting.one": "1 convirtiendo",
        "summary.converting.other": "{count} convirtiendo",
        "summary.waiting.one": "1 en espera",
        "summary.waiting.other": "{count} en espera",
        "summary.ready_of": "{ready} de {total} listos",
        "summary.all_saved.one": "1 guardado en Descargas",
        "summary.all_saved.other": "Los {count} guardados en Descargas",
        "button.retry_row": "Reintentar",
        "row.retry_hint": "Pulse Intro para reintentar",

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
        "advanced.per_item_hints": "<b>Indicaciones para el archivo seleccionado</b>",
        "advanced.select_row_first": "Seleccione primero un archivo de la lista para indicar su extensión, mimetype o charset.",
        "advanced.applies_to": "Aplica a: {name}",
        "advanced.extension_placeholder": "Extensión (.pdf)",
        "advanced.mimetype_placeholder": "Mimetype (text/html)",
        "advanced.charset_placeholder": "Charset (utf-8)",
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
