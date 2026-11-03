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
main.py                       entry point
app/core/converter.py         MarkItDown wrapper, background worker, auto-save
app/core/conversion_queue.py  runs items through convert, then save
app/core/queue_model.py       queue items, their states, the table model
app/ui/main_window.py         main window, menus, list and detail panes
app/ui/drop_zone.py           empty-window instruction, add buttons, link field
app/ui/queue_delegate.py      paints the queue rows
app/ui/queue_text.py          the words for the queue summary and detail header
app/ui/status_mark.py         one mark per status
app/ui/brand_mark.py          the app's mark
app/ui/advanced_settings_dialog.py, about_dialog.py
app/ui/theme.py               palette and stylesheets, light and dark
app/i18n.py                   English and Spanish translations
tests/                        unittest suite
docs/                         landing page and screenshots
```

## Making a change

1. Open an issue first for anything non-trivial (new feature, behavior
   change) so we can agree on the approach before you write code.
2. Keep pull requests focused — one change per PR is easier to review.
3. Match the existing code style: idiomatic PySide6 (signals/slots), no
   dead code, no TODOs left in.
4. If you touch user-facing strings, add both English and Spanish entries
   in `app/i18n.py` — see the existing keys for the pattern.
5. Add or update tests for behavior changes, and run the suite. It uses only
   the standard library's `unittest`, a temporary home folder, and fake
   settings, so it never touches your Downloads or saved preferences:

   ```bash
   QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
   ```

   On Windows PowerShell, run `$env:QT_QPA_PLATFORM = "offscreen"` first.
6. Run `ruff check .`, and actually run the app and exercise the change before
   opening the PR. CI repeats the suite and the lint on Windows, macOS, and Linux.

## Reporting bugs / requesting features

Use the issue templates — they ask for the information needed to
reproduce a bug or evaluate a feature request.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you agree to abide by it.
