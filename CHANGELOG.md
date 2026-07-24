# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/andrest04/markitdown-desktop/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/andrest04/markitdown-desktop/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/andrest04/markitdown-desktop/releases/tag/v1.0.0
