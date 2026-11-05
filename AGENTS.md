# AGENTS.md

This file provides guidance to Codex and other coding agents when working with code in this repository.

## What this is

A PySide6 desktop GUI wrapper around Microsoft's `markitdown` Python
package. It is **not** a fork of markitdown and contains no conversion
logic of its own — every actual file-to-Markdown conversion goes through
the real `markitdown` public API (`MarkItDown.convert_local()` /
`convert_uri()`). This repo only adds: a queue/drop-zone UI, a background
worker per item, auto-save-to-Downloads, and i18n.

Core UX contract (do not break when changing things): **drop a file,
paste a URL, or click to browse → conversion starts immediately → the
resulting `.md` is auto-saved to `~/Downloads` with no export step.**
Everything else (preview tabs, "save a copy elsewhere", advanced Azure
settings) is secondary and must stay out of that primary path. The one
exception: output with no text is a failure with its own reason, never an
empty `.md`.

## Commands

Run from the repo root, using whatever interpreter has `requirements.txt`
installed:

```bash
python -m pip install -r requirements.txt   # install deps
python main.py                              # run the app
./run.sh                                     # macOS/Linux launcher (checks python3 is on PATH)
run.bat                                      # Windows launcher (checks python is on PATH)
```

Verification is done by the stdlib `unittest` suite in `tests/` (no extra
dependency) plus the checks below. CI runs the suite and the smoke test on all three OSes.

```bash
# Run the test suite. Tests use a temp home folder and fake QSettings, so they
# never touch the real Downloads or native settings. Most stub convert_item;
# tests/test_failure_reasons.py calls the real one, on scratch files. Anything
# on a platform branch patches sys.platform, since CI runs every OS.
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests

# Syntax check a changed file
python -c "import ast; ast.parse(open('app/ui/main_window.py').read())"

# Headless smoke test — builds the real MainWindow with no display server,
# CI runs this too (see .github/workflows/ci.yml)
QT_QPA_PLATFORM=offscreen python -c "
from app.ui.main_window import MainWindow
from PySide6.QtWidgets import QApplication
app = QApplication([])
w = MainWindow()
w.show()
print('OK')
"

# Lint (also run in CI)
pip install ruff
ruff check .
ruff check . --fix   # only auto-fix; review the diff before trusting it
```

When testing real end-to-end conversion behavior, `app/core/converter.py`'s
`convert_item()` is deliberately Qt-independent — it can be called directly
against a scratch file without spinning up the GUI:

```python
from app.core.converter import convert_item, ConversionOptions
from app.core.queue_model import QueueItem, SourceKind
item = QueueItem(source="/path/to/file.txt", kind=SourceKind.FILE, display_name="file.txt")
print(convert_item(item, ConversionOptions()))
```

Any manual local testing that writes into the real `~/Downloads` (e.g. via
`auto_save_markdown()`) must clean up its own test files afterward —
nothing test-related should be left in the user's actual Downloads folder.

## Architecture

**Three-layer split**, each layer only depends on the one below it:

- `app/core/converter.py` — Qt-agnostic conversion logic + the Qt
  `QRunnable` worker. `ConversionOptions` is frozen: a settings change
  replaces the value, so workers never share a mutable object.
  `ConversionOptions.build_markitdown()` maps the
  GUI's option toggles to real `MarkItDown(...)` constructor kwargs
  (`enable_plugins`, `docintel_endpoint`, `cu_endpoint`, `cu_analyzer_id`),
  and always passes `requests_session` a `_TimeoutSession`, which applies
  `URL_TIMEOUT` (connect, read) to requests that set none and repeats
  markitdown's `Accept` header, set only on a session of its own.
  `convert_item()` raises `NoTextFound` on whitespace-only output, which
  markitdown does not, and maps per-item extension/mimetype/charset overrides to a
  `StreamInfo` object and calls `convert_local()` or `convert_uri()`
  depending on `SourceKind`. `auto_save_markdown()` / `get_downloads_dir()`
  / `unique_download_path()` implement the Downloads auto-save contract
  (collision-safe numeric suffixing, `Path.home()`-based so it's portable
  across accounts/OSes). `export_markdown()` is the collision-safe bulk
  export; it collects `OSError`s in its result instead of raising.
  `classify_paths()` sorts dropped/browsed paths for queueing.
  `classify_conversion_error()` and `classify_save_error()` sort failures into
  a `FailureReason`, by exception type and by errno, since library text cannot
  be translated. markitdown wraps what a converter raised in
  `FileConversionException.attempts`; a text file renamed `.pdf` converts
  without error, so test against what really raises.
- `app/core/queue_model.py` — `QueueItem` (dataclass) + `QueueTableModel`
  (`QAbstractTableModel`) backing the queue `QTableView`. **Important**:
  `ItemStatus` enum values are translation *keys* (`"status.pending"`,
  not `"Pending"`) so `QueueTableModel.data()` and the delegate call `tr()`
  at display time — this is what lets a live language switch retranslate
  rows that were added before the switch. Don't store display strings in
  the model. `QueueItem` compares by identity (`eq=False`), so workers can
  address it while rows shift. What a state means lives in one place:
  `QueueItem.display_state` (a derived `DisplayState` enum, also translation
  keys) and the `mark_*()` transitions. A failed retry keeps `saved_path`,
  because the earlier file still exists. `FailureReason` values are keys too:
  an item stores the key plus the raw text, and `row_status_text()` and
  `failure_reason_text()` resolve them at display time. Rows carry that text in
  `Qt.AccessibleTextRole` for screen readers.
- `app/core/conversion_queue.py` — `ConversionQueue(QObject)` owns the
  convert-then-auto-save contract: dispatch, in-flight guard, transitions,
  progress that accumulates across overlapping batches, and auto-save. It
  emits signals and never calls `tr()`; the window translates. Worker signals
  connect to its bound slots, so results and saves run on the GUI thread.
  `discard()` is called after rows are removed: a worker not yet started is
  cancelled with `QThreadPool.tryTake` and leaves the total; a running one
  cannot be interrupted, so it keeps counting and its result goes nowhere.
  Removed items report nothing.
- `app/ui/` — everything Qt/visual, one class per file:
  - `main_window.py` — `MainWindow`, the main window/queue/menu logic.
    Holds one `ConversionOptions` value, starts work through
    `ConversionQueue` and reacts to its signals to update the UI. Imports
    the widgets below rather than defining them.
  - `drop_zone.py` — `DropZone` (no box: the empty-window instruction with
    add buttons and the link field, reduced to just the link row once items
    exist, via `set_prominent()`). No `MainWindow` reference — takes plain
    callables in its constructor. `accept_drops_on()` extends file drops to
    other widgets, and the window itself is one of them, so drops work
    anywhere. `drag_active_changed` drives the window's drag overlay.
  - `queue_delegate.py` — `QueueItemDelegate`, paints queue rows from
    `display_state` through `status_style()`: a glyph shape plus words, so
    status never relies on color. It fills its whole cell opaquely first;
    that is what prevents selection bleed from the style underneath.
    Selection is a quiet fill plus a `mark` stroke behind the file name only.
    Rows needing it paint a retry in one fixed column (`retry_rect()`,
    `retry_requested`); Enter on the focused row does the same, from
    `MainWindow.eventFilter`. Delete removes rows only while the list has
    focus (`WidgetShortcut`), so a file drop hands the list focus unless
    someone is typing or a dialog is open, and removing rows selects the row
    now at the first removed position. `row_tooltip()` lives here too.
  - `preview_browser.py` — `PreviewBrowser`, the rendered preview. Reads no
    image or stylesheet that converted text names, only embedded `data:` images.
    Links go through `_on_link_clicked()` (`setOpenLinks(False)`): fragments
    scroll, absolute `http`, `https` and `mailto` open externally, and the rest
    do nothing. No `MainWindow` reference. `_render_markdown()` in `main_window.py`
    renders only `preview_excerpt()`, up to `PREVIEW_CHAR_LIMIT` and cut at a line,
    with a notice through `preview_html()`, and typing in the Markdown tab reaches
    it through a single-shot timer. The item takes every keystroke at once, so
    nothing waits on that timer to be kept. On a scaled screen Qt checks for
    `name@2x.png` before `loadResource`, so `main.py` sets
    `QT_HIGHDPI_DISABLE_2X_IMAGE_LOADING` before anything imports Qt.
  - `queue_text.py` — plain functions for the pane's words: `queue_summary()`,
    `detail_status()` and `word_count()`.
  - `status_mark.py` — `StatusMark` and `paint_status_glyph()`, one silhouette
    per state, which the delegate paints too.
  - `brand_mark.py` — `BrandMark` and `paint_brand_mark()`.
  - `advanced_settings_dialog.py` — `AdvancedSettingsDialog`, the
    secondary settings panel opened from Edit > Advanced settings. Takes
    the current options and target item; on accept the caller reads
    `selected_options()` and calls `apply_item_overrides()`, which returns whether
    the hints changed. Changed hints on an item with status `DONE` convert it again
    through `enqueue()`; the in-flight guard covers one already dispatched, and a
    failed item waits for Retry. No `MainWindow` reference.
  - `about_dialog.py` — `AboutDialog`. Reads the markitdown package
    version via `app.core.converter.get_markitdown_version()` rather
    than importing `markitdown` itself — `converter.py` is the only file
    allowed to import from the `markitdown` package directly; keep it
    that way if you touch this again.
  - `theme.py` — design `Tokens` (`LIGHT`/`DARK`), `tokens_for()`,
    `current_tokens()`, `set_tier()`, `apply_fusion_palette()`, `stylesheet_for()`,
    `document_css_for()`, plus `preview_html()`, which wraps code blocks and
    quotes in table cells because Qt's rich text has no padding on plain
    blocks, and `needs_full_width()`; no widget classes. Applied at the
    `QApplication` level, not per-widget.

**Visual rules**: ink on paper, and one highlighter. `mark` goes only on what
the person is working on (empty-window instruction, selected row, selected
text, drag overlay, focused primary); every neutral is a dilution of the ink
and red means failure only, with no success color. Each state has at most one
button with `tier="primary"`, set through `set_tier()`; the rest are quiet or
ghost, or live in the More menu and menu bar. New text and control pairings
go in `tests/test_theme_contrast.py`. No cards, pills or chips. Set font sizes
in QSS, since it overrides `setFont()`. Do not give the window an explicit
minimum width: it overrides the layout's minimum and clips the action row.

**i18n (`app/i18n.py`)** is a hand-rolled, dependency-free layer — no Qt
Linguist `.ts`/`.qm` build step. `TRANSLATIONS` is a `{lang: {key: text}}`
dict for `"en"`/`"es"`. `manager` (a module-level `TranslationManager`)
holds the current language, persists it via `QSettings`, and exposes a
`language_changed` Signal. `tr(key, **kwargs)` never raises — falls back
to English, then to the raw key, so a typo'd key degrades instead of
crashing. Any widget with text that can change language mid-session must
implement a `retranslate_ui()`/`retranslate()` method and connect it to
`manager.language_changed`, and must NOT store already-translated text
anywhere persistent (see the `QueueTableModel` status-key note above).
When adding a new user-facing string: add the key to **both** the `en`
and `es` dicts in `app/i18n.py` — Spanish must stay neutral/professional
(no voseo, no regional slang), not Rioplatense.

**Retry**: `action_convert_selected()` (the Retry action and header button) only
starts `_selected_retry_rows()`, and the action is enabled when that is not empty,
while the other actions follow the first selected row. `_start_conversion()` does
not filter: the row button, Enter and the context menu check their own row first.
It calls `ConversionQueue.retry()`: a `SAVE_FAILED` item with text saves again on the
GUI thread, with no worker and no change to progress or `batch_finished`, and any
other item goes through `enqueue()`. `_has_result()` decides what Copy, Save a copy
and Export reach: `DONE` items with text, and `ERROR` items whose text never reached a
file. A failed retry of a saved item offers nothing, since that text is out of date.

**Closing**: with results still to come (`unfinished_count()`, which leaves out
removed items), `closeEvent` asks through `_confirm_close()`, defaulting to keep
converting. Close anyway calls `cancel_unstarted()`, the `discard()` path. A
running worker cannot be interrupted, so after `app.exec()` `end_process()` in
`main.py` syncs settings and, only if the pool still has an active thread, ends
with `os._exit`, since a normal exit would wait for it and then raise
`Signal source has been deleted`. Tests closing a window with work in flight must
patch `QMessageBox.exec`, or the real dialog blocks them.

**Threading model**: conversions never block the UI thread. Each queue
item gets its own `ConversionWorker` (`QRunnable`) submitted by
`ConversionQueue` to the global `QThreadPool`; `WorkerSignals`
(`started`/`finished`/`failed`, carrying the `QueueItem`) are the only
channel back to the GUI. Per-item exceptions are caught inside
`ConversionWorker.run()` and turned into a `failed` signal — one bad file
must never abort the rest of a batch.

**Cross-platform note**: `reveal_command()` in `main_window.py` dispatches on
`sys.platform` (`explorer` / `open -R` / `xdg-open`) and never goes through a
shell, so `%VAR%` or `&` in a file name stay literal. Any new OS-shell-out needs
the same three-way branch — don't assume Windows. `detect_system_theme()` asks
Qt's `styleHints().colorScheme()`: the app palette cannot answer, because
`apply_fusion_palette()` has already replaced it.

## CI/CD (all in `.github/workflows/`)

- `ci.yml` — on every push/PR to `main`: `ruff check .`, `python -m
  compileall`, the headless smoke test above, and `python -m unittest discover
  -s tests`, matrixed across windows-latest/macos-latest/ubuntu-latest.
  PySide6 is held below 6.12 in `requirements.txt`: 6.12.0 loses a reference to
  `True` on every `Signal.emit()`, which aborts on Linux with Python 3.11
  (`tests/test_signal_refcount.py` measures it).
- `assets/icon.*` — the app icon, drawn by `assets/make_icons.py` (needs
  Pillow, which the app does not); the window, both PyInstaller builds and
  `installer.iss` use it.
- `release.yml` — on any `vX.Y.Z` tag push: builds a PyInstaller
  `--onedir --windowed` bundle per OS (`--collect-all markitdown
  --collect-all magika`, needed because both do dynamic/plugin-style
  imports PyInstaller's static analysis can't see), zips it, and attaches
  it to the GitHub Release via `softprops/action-gh-release`.

Branch protection is enabled on `main` (required PR review) but
`enforce_admins` is `false` — the repo owner can still push directly;
external contributors cannot.

Version bumps follow semver in `CHANGELOG.md` (Keep a Changelog format):
move `[Unreleased]` entries into a new `[X.Y.Z] - date` section, update
the comparison links at the bottom of the file, then `git tag vX.Y.Z &&
git push origin vX.Y.Z` to trigger `release.yml`.

## Landing page (`docs/`)

`docs/index.html` is a single self-contained file (inline CSS/JS, no
build step, no external script/font dependencies) served by GitHub Pages
from `/docs` on `main`. It mirrors — but is not generated from — the
README; update both when a user-facing feature changes. Respects
`prefers-color-scheme` plus a `data-theme` override, and fetches a live
GitHub star count client-side (`fetch` against the public GitHub REST
API, no auth, degrades silently if it fails/rate-limits).
