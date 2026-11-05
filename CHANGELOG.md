# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Closing the window with conversions unfinished now asks first, with the count.
  Keep converting is the default and loses nothing. Close anyway cancels what has
  not started and ends the app without waiting for what is running.

### Fixed

- Closing during a conversion silently lost the result, and the app kept running
  without a window until the conversion ended.
- On Linux with Python 3.11, the app could abort after about 20 conversions in
  one session. PySide6 is now held below 6.12.
- Clicking a relative or `file:` link in the preview blanked it or replaced it
  with that local file. Links inside the text still scroll, web and mail links
  still open outside the app, and anything else now does nothing.
- A link whose server accepts the connection and never answers kept its item
  converting forever. It now fails as a connection problem after 10 seconds to
  connect or 60 seconds without data. Large downloads with steady data are not
  cut off.
- The preview no longer reads local files or network shares for images and
  stylesheets that converted text points at. Images embedded in the text still
  show.

## [1.4.0] - 2026-11-02

### Added

- App icon: the landing page's mark now identifies the app in the window, the
  taskbar, the Windows `.exe`, and the Windows installer.
- Copy button on the landing page's run-from-source commands.
- The window opens small for the empty screen, grows when the first file
  arrives, and goes back when the list is cleared. Your own working size is
  remembered.
- Windows installer (`markitdown-desktop-setup.exe`), built with Inno Setup
  and attached to each GitHub Release alongside the existing portable
  `.exe` and zipped build. Installs per-user (no admin rights required),
  adds a Start Menu shortcut, an optional desktop shortcut, and a proper
  uninstaller.
- A line above the queue answers whether everything is ready and what needs
  attention, for example "1 failed, 2 ready".
- A Retry button on each row that needs one, with its reason on the row.
  Enter on the focused row does the same.
- Failure reasons in English and Spanish, such as "damaged or unreadable file"
  or "disk full", that follow a live language switch. The library's own text
  stays in the detail pane and the row tooltip.
- The detail header names the file actually saved and its word count.
- Screen readers get each row's name and status.
- "Follow system theme" also follows changes made while the app is open.
- CI runs the test suite on Windows, macOS, and Linux.

### Changed

- Redesigned the desktop UI as ink on paper with one highlighter: a list and
  detail layout with one primary action per state, a marker stroke on the file
  you are working on, and a distinct mark for each status that reads without
  color. Files can be dropped anywhere in the window.
- The preview caps prose at a readable line length, with new typography for
  lists, quotes, tables, and code, and a thinner scrollbar.
- Redesigned the landing page, now in English and Spanish.
- The README and landing page show screenshots of the current interface and describe
  its flows, instead of the old demo.

### Fixed

- A document that yields no text now fails with "no text found" instead of
  saving an empty `.md`. An earlier saved file stays if a retry finds none.
  That includes output with only invisible characters, such as an empty text
  file with a byte order mark.
- The Delete key removes rows only while the list has focus, so it no longer
  removes one while a button has focus.
- Delete works right after dropping files, without clicking the row first.
  A drop leaves focus alone while you type in the link field or a dialog is open.
- Removing a row selects the one that takes its place, or the new last row, so
  Delete can be pressed again.
- A save failure on the last file running stays in the status bar instead of
  being replaced by "All conversions finished". That message now also counts
  what failed earlier, for example "All conversions finished, 1 failed".
- Export no longer overwrites existing files, and reports the ones it could
  not write.
- Results land on the right row when the list changes during a conversion, and
  progress stays correct across overlapping batches.
- Removing a file that has not started cancels it. Removing one that is running
  discards its result and any failure message.
- "Save a copy" no longer writes old text from a file whose retry failed.
- Switching from dark to "Follow system theme" no longer stays dark.
- "Show in folder" works on file names containing `%` or `&`, without a shell.
- File > Exit shows `Ctrl+Q` instead of the word "Exit" as its shortcut on
  Windows.

### Removed

- Dependabot configuration, so no more automatic dependency update branches.

### Known issues

- On Linux, the test suite aborts at interpreter exit under Python 3.11
  (`bool_dealloc`), the Python version release builds use. The cause is still
  under investigation, and the Linux build may hit it when closing the app.
  Files already converted stay saved.

## [1.3.0] - 2026-08-13

### Added

- Release workflow: Windows builds now also produce a standalone
  single-file `markitdown-desktop.exe`, attached to the GitHub Release
  alongside the existing zipped binaries — no extraction needed to run it.

## [1.2.0] - 2026-07-24

### Added

- CI workflow: lint (ruff) + syntax check + headless smoke test on every
  push/PR, run on Windows, macOS, and Linux.
- Dependabot: weekly dependency update PRs for pip and GitHub Actions.
- Release workflow: pushing a `vX.Y.Z` tag now builds a standalone binary
  for Windows, macOS, and Linux with PyInstaller and attaches each as a
  release asset automatically — no Python installation required to run
  the app anymore.

## [1.1.0] - 2026-07-24

### Added

- Landing page (GitHub Pages) with feature overview, screenshot, supported
  formats, and per-OS install instructions.
- "Star on GitHub" button with a live star count on the landing page.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), and
  GitHub issue/pull request templates.
- `SECURITY.md` with a private vulnerability-reporting process.
- Release, platform, and license badges in the README, plus a security
  callout and a Contributing section linking to the new files.
- `CHANGELOG.md` following Keep a Changelog.
- Branch protection on `main`: external contributors must go through a
  reviewed pull request.

## [1.0.0] - 2026-07-24

### Added

- Drag-and-drop, click-to-browse, and paste-a-URL (webpage or YouTube)
  input — conversion starts automatically, no separate "Convert" step.
- Auto-save of converted `.md` files straight to the Downloads folder,
  with collision-safe numeric-suffix naming.
- Rendered and raw Markdown preview tabs, with optional "save a copy
  elsewhere" / "export all" actions.
- Advanced settings dialog: plugins, `keep_data_uris`, Azure Document
  Intelligence, Azure Content Understanding, and per-item format hints.
- Light/dark theme support following the system, with a hover-animated
  drop zone.
- English/Spanish (neutral) UI, switchable live from the menu bar.
- Cross-platform support: Windows (`run.bat`), macOS/Linux (`run.sh`);
  "open containing folder" dispatches to `explorer`/`open -R`/`xdg-open`
  per OS.

[Unreleased]: https://github.com/andrest04/markitdown-desktop/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/andrest04/markitdown-desktop/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/andrest04/markitdown-desktop/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/andrest04/markitdown-desktop/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/andrest04/markitdown-desktop/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/andrest04/markitdown-desktop/releases/tag/v1.0.0
