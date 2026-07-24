# Contributing

Thanks for considering a contribution to MarkItDown Desktop.

## Getting set up

```bash
git clone https://github.com/andrest04/markitdown-desktop.git
cd markitdown-desktop
python -m pip install -r requirements.txt
python main.py
```

See the [README](README.md) for platform-specific run instructions
(`run.bat` on Windows, `run.sh` on macOS/Linux).

## Project structure

```
main.py                    entry point
app/ui/main_window.py      main window, drop zone, advanced settings dialog
app/ui/theme.py             light/dark QSS stylesheets
app/core/converter.py      MarkItDown wrapper, background worker, auto-save logic
app/core/queue_model.py    queue table data model
app/i18n.py                English/Spanish translation layer
```

## Making a change

1. Open an issue first for anything non-trivial (new feature, behavior
   change) so we can agree on the approach before you write code.
2. Keep pull requests focused — one change per PR is easier to review.
3. Match the existing code style: idiomatic PySide6 (signals/slots), no
   dead code, no TODOs left in.
4. If you touch user-facing strings, add both English and Spanish entries
   in `app/i18n.py` — see the existing keys for the pattern.
5. Actually run the app and exercise the change before opening the PR.
   There's no automated test suite yet, so manual verification matters.

## Reporting bugs / requesting features

Use the issue templates — they ask for the information needed to
reproduce a bug or evaluate a feature request.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you agree to abide by it.
