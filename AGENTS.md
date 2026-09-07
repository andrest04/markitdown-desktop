# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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
settings) is secondary and must stay out of that primary path.

## Commands

Run from the repo root, using whatever interpreter has `requirements.txt`
installed:

```bash
python -m pip install -r requirements.txt   # install deps
python main.py                              # run the app
./run.sh                                     # macOS/Linux launcher (checks python3 is on PATH)
run.bat                                      # Windows launcher (checks python is on PATH)
```

There is no automated test suite. Verification is done by:

```bash
# Syntax check a changed file
python -c "import ast; ast.parse(open('app/ui/main_window.py').read())"

# Headless smoke test — builds the real MainWindow with no display server,
# this is what CI runs (see .github/workflows/ci.yml)
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
  `QRunnable` worker. `ConversionOptions.build_markitdown()` maps the
  GUI's option toggles to real `MarkItDown(...)` constructor kwargs
  (`enable_plugins`, `docintel_endpoint`, `cu_endpoint`, `cu_analyzer_id`).
  `convert_item()` maps per-item extension/mimetype/charset overrides to a
  `StreamInfo` object and calls `convert_local()` or `convert_uri()`
  depending on `SourceKind`. `auto_save_markdown()` / `get_downloads_dir()`
  / `unique_download_path()` implement the Downloads auto-save contract
  (collision-safe numeric suffixing, `Path.home()`-based so it's portable
  across accounts/OSes).
- `app/core/queue_model.py` — `QueueItem` (dataclass) + `QueueTableModel`
  (`QAbstractTableModel`) backing the queue `QTableView`. **Important**:
  `ItemStatus` enum values are translation *keys* (`"status.pending"`,
  not `"Pending"`) so the view calls `tr()` at display time — this is what
  lets a live language switch retranslate rows that were added before the
  switch. Don't bake display strings into the model.
- `app/ui/` — everything Qt/visual, one class per file:
  - `main_window.py` — `MainWindow`, the main window/queue/menu logic.
    `ConversionWorker` instances are dispatched onto `QThreadPool` from
    here; their `started`/`finished`/`failed` signals (cross-thread,
    queued by Qt automatically) drive UI updates and trigger
    `_auto_save_to_downloads()` on success. Empty state is a full-window
    drop canvas; the preview pane only appears once the queue has items.
    Retry lives in the queue context menu and Edit menu, not as primary
    buttons. Imports the widgets below rather than defining them.
  - `drop_zone.py` — `DropZone` (drag-and-drop + URL field + format
    chips). Browse/add-folder are explicit buttons; the canvas is not a
    click-to-open hit target. Switches between a large empty-queue
    canvas and a slim bar via `set_prominent()`. No `MainWindow`
    reference — takes plain callables in its constructor.
  - `queue_delegate.py` — `QueueItemDelegate` paints queue rows as
    activity lines (name + type/status), not spreadsheet cells. Type and
    status columns stay in the model but are hidden in the view.
  - `advanced_settings_dialog.py` — `AdvancedSettingsDialog`, the
    secondary settings panel opened from Edit > Advanced Settings. Takes
    a `MainWindow` reference to read/write its option attributes; that
    reference is a `TYPE_CHECKING`-only import (with `from __future__
    import annotations`) to avoid a real circular import with
    `main_window.py`.
  - `about_dialog.py` — `AboutDialog`. Reads the markitdown package
    version via `app.core.converter.get_markitdown_version()` rather
    than importing `markitdown` itself — `converter.py` is the only file
    allowed to import from the `markitdown` package directly; keep it
    that way if you touch this again.
  - `theme.py` — Inkbench token system (`Tokens`, `LIGHT`/`DARK`) compiled
    to QSS. `apply_fusion_palette()` keeps Fusion chrome in sync. Applied
    at the `QApplication` level, not per-widget. Do not fall back to a
    generic blue SaaS palette.

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

**Threading model**: conversions never block the UI thread. Each queue
item gets its own `ConversionWorker` (`QRunnable`) submitted to the
global `QThreadPool`; `WorkerSignals` (`started`/`finished`/`failed`) are
the only channel back to the GUI. Per-item exceptions are caught inside
`ConversionWorker.run()` and turned into a `failed` signal — one bad file
must never abort the rest of a batch.

**Cross-platform note**: `_open_containing_folder()` in `main_window.py`
dispatches on `sys.platform` (`explorer` / `open -R` / `xdg-open`). Any
new OS-shell-out needs the same three-way branch — don't assume Windows.

## CI/CD (all in `.github/workflows/`)

- `ci.yml` — on every push/PR to `main`: `ruff check .`, `python -m
  compileall`, and the headless smoke test above, matrixed across
  windows-latest/macos-latest/ubuntu-latest.
- `release.yml` — on any `vX.Y.Z` tag push: builds a PyInstaller
  `--onedir --windowed` bundle per OS (`--collect-all markitdown
  --collect-all magika`, needed because both do dynamic/plugin-style
  imports PyInstaller's static analysis can't see), zips it, and attaches
  it to the GitHub Release via `softprops/action-gh-release`.
- `dependabot.yml` — weekly PRs for `pip` and `github-actions` deps.

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
