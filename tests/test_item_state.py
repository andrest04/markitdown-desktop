"""Every consumer must agree on what an item's state means."""
from __future__ import annotations

import unittest
from unittest import mock

from qt_support import WindowTestCase, pump_until, settle

from app.core.queue_model import COLUMN_STATUS, ItemStatus, QueueItem, SourceKind
from app.i18n import tr
from app.ui.queue_delegate import QueueItemDelegate
from app.ui.theme import tokens_for

SAVED_PATH = "/somewhere/saved.md"

# status, saved_path, save_error -> what each consumer must show.
# text: table status text and delegate text. header: preview header text.
MATRIX = [
    {
        "item": (ItemStatus.PENDING, "", ""),
        "text": "status.pending",
        "color": "muted",
        "header": "preview.pending", "kind": "pending", "open": False, "retry": False,
    },
    {
        "item": (ItemStatus.CONVERTING, "", ""),
        "text": "status.converting",
        "color": "muted",
        "header": "preview.converting", "kind": "converting", "open": False, "retry": False,
    },
    {
        # A retry of an item that was saved earlier.
        "item": (ItemStatus.CONVERTING, SAVED_PATH, ""),
        "text": "status.converting",
        "color": "muted",
        "header": "preview.converting", "kind": "converting", "open": False, "retry": False,
    },
    {
        "item": (ItemStatus.DONE, SAVED_PATH, ""),
        "text": "status.done_saved",
        "color": "muted",
        "header": None, "header_text": tr("status.saved_as", name="saved.md"), "kind": "saved", "open": True, "retry": False,
    },
    {
        "item": (ItemStatus.DONE, "", "disk full"),
        "text": "status.done_save_failed",
        "color": "danger",
        "header": None, "header_text": tr("status.save_failed_detail", error=tr("error.save_generic")), "kind": "error", "open": False, "retry": True,
    },
    {
        # Transient: converted, auto-save has not reported yet.
        "item": (ItemStatus.DONE, "", ""),
        "text": "status.done",
        "color": "muted",
        "header": "status.done", "kind": "pending", "open": False, "retry": False,
    },
    {
        "item": (ItemStatus.ERROR, "", ""),
        "text": "status.error",
        "color": "danger",
        "header": None, "kind": "error", "open": False, "retry": True,
    },
    {
        # A failed retry: the earlier file still exists, but the item shows failed.
        "item": (ItemStatus.ERROR, SAVED_PATH, ""),
        "text": "status.error",
        "color": "danger",
        "header": None, "kind": "error", "open": False, "retry": True,
    },
]


def make_item(status, saved_path, save_error) -> QueueItem:
    return QueueItem(
        source="/somewhere/a.txt",
        kind=SourceKind.FILE,
        display_name="a.txt",
        status=status,
        error_message="boom" if status == ItemStatus.ERROR else "",
        saved_path=saved_path,
        save_error=save_error,
    )


class ConsumerMatrixTests(WindowTestCase):
    """Characterization: the model, delegate and preview header for every state."""

    def test_model_status_text(self):
        for case in MATRIX:
            with self.subTest(item=case["item"]):
                self.window.model.clear()
                self.window.model.add_item(make_item(*case["item"]))
                index = self.window.model.index(0, COLUMN_STATUS)
                self.assertEqual(self.window.model.data(index), tr(case["text"]))

    def test_delegate_parts(self):
        delegate = QueueItemDelegate()
        tokens = tokens_for("light")
        for case in MATRIX:
            with self.subTest(item=case["item"]):
                item = make_item(*case["item"])
                self.assertEqual(
                    delegate._status_parts(item, tokens),
                    (tr(case["text"]), getattr(tokens, case["color"])),
                )

    def test_preview_header(self):
        for case in MATRIX:
            with self.subTest(item=case["item"]):
                self.window._update_preview_header(make_item(*case["item"]))
                expected = case.get("header_text", "Conversion error") if case["header"] is None else tr(case["header"])
                self.assertEqual(self.window.preview_header_status.text(), expected)
                self.assertEqual(self.window.preview_header_status.property("kind"), case["kind"])
                self.assertEqual(not self.window.open_file_btn.isHidden(), case["open"])
                self.assertEqual(not self.window.reveal_btn.isHidden(), case["open"])
                self.assertEqual(not self.window.retry_header_btn.isHidden(), case["retry"])

    def test_preview_header_falls_back_when_an_error_has_no_message(self):
        item = make_item(ItemStatus.ERROR, "", "")
        item.error_message = ""
        self.window._update_preview_header(item)
        self.assertEqual(self.window.preview_header_status.text(), tr("preview.failed"))


class FailedRetryTests(WindowTestCase):
    """A failed retry keeps `saved_path`, because the earlier file still exists."""

    def _item_saved_then_failed_retry(self):
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
        settle()
        item = self.item_named("a.txt")
        self.assertTrue(item.saved_path)

        self.converter.failures["a.txt"] = "boom"
        self.window.table_view.selectRow(0)
        self.window.action_convert_selected()
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR))
        settle()
        return item

    def test_saved_path_survives_and_the_item_shows_failed(self):
        item = self._item_saved_then_failed_retry()
        self.assertTrue(item.saved_path.endswith("a.md"))
        self.assertEqual(item.error_message, "boom")
        self.assertEqual(self.window.preview_header_status.property("kind"), "error")
        self.assertTrue(self.window.open_file_btn.isHidden())
        self.assertEqual(self.downloaded_names(), ["a.md"])

    def test_double_click_still_opens_the_earlier_file(self):
        item = self._item_saved_then_failed_retry()
        with mock.patch.object(self.window, "_open_file") as open_file:
            self.window._on_row_double_clicked(self.window.model.index(0, 0))
        open_file.assert_called_once_with(item.saved_path)


class StaleResultTests(WindowTestCase):
    """An item that is not currently converted has nothing current to save."""

    def _item_saved_then_failed_retry(self):
        self.add_sources("a.txt")
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
        settle()
        item = self.item_named("a.txt")
        self.converter.failures["a.txt"] = "boom"
        self.window.table_view.selectRow(0)
        self.window.action_convert_selected()
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.ERROR))
        settle()
        return item

    def test_saving_a_failed_item_refuses_and_writes_nothing(self):
        item = self._item_saved_then_failed_retry()
        self.assertIsNotNone(item.markdown_result, "the stale text is what must not be written")
        target = self.tmp / "copy.md"
        with (
            mock.patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")) as dialog,
            mock.patch("app.ui.main_window.QMessageBox.information") as information,
        ):
            self.window.action_save_current()
        dialog.assert_not_called()
        information.assert_called_once()
        self.assertEqual(information.call_args.args[1], tr("msgbox.nothing_to_save.title"))
        self.assertFalse(target.exists())

    def test_the_action_is_off_in_every_menu_that_holds_it(self):
        self._item_saved_then_failed_retry()
        self.assertFalse(self.window.save_copy_action.isEnabled())
        self.assertIn(self.window.save_copy_action, self.window.file_menu.actions())
        self.assertIn(self.window.save_copy_action, self.window.more_menu.actions())

    def test_saving_a_retry_in_progress_refuses_too(self):
        item = self._item_saved_then_failed_retry()
        del self.converter.failures["a.txt"]
        self.window.action_convert_selected()
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.CONVERTING))
        self.assertFalse(self.window.save_copy_action.isEnabled())
        with (
            mock.patch("app.ui.main_window.QFileDialog.getSaveFileName") as dialog,
            mock.patch("app.ui.main_window.QMessageBox.information"),
        ):
            self.window.action_save_current()
        dialog.assert_not_called()

    def test_saving_works_again_after_a_successful_retry(self):
        item = self._item_saved_then_failed_retry()
        del self.converter.failures["a.txt"]
        self.window.action_convert_selected()
        self.converter.release("a.txt")
        self.assertTrue(pump_until(lambda: item.status == ItemStatus.DONE))
        settle()
        self.assertTrue(self.window.save_copy_action.isEnabled())


class SaveFailureTests(WindowTestCase):
    def test_save_failure_stays_done_with_save_error(self):
        source = self.make_source("a.txt")
        with mock.patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            self.window._add_paths([source])
            self.converter.release("a.txt")
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.DONE))
            settle()
        item = self.item_named("a.txt")
        self.assertEqual(item.save_error, "disk full")
        self.assertEqual(item.saved_path, "")
        self.assertEqual(item.markdown_result, "# converted a.txt")


class DisplayStateTests(unittest.TestCase):
    def test_values_are_translation_keys_in_every_language(self):
        from app.core.queue_model import DisplayState
        from app.i18n import TRANSLATIONS

        for state in DisplayState:
            for language, table in TRANSLATIONS.items():
                with self.subTest(state=state, language=language):
                    self.assertIn(state.value, table)

    def test_derivation(self):
        from app.core.queue_model import DisplayState

        expected = {
            (ItemStatus.PENDING, "", ""): DisplayState.PENDING,
            (ItemStatus.CONVERTING, "", ""): DisplayState.CONVERTING,
            (ItemStatus.CONVERTING, SAVED_PATH, ""): DisplayState.CONVERTING,
            (ItemStatus.DONE, SAVED_PATH, ""): DisplayState.SAVED,
            (ItemStatus.DONE, "", "disk full"): DisplayState.SAVE_FAILED,
            (ItemStatus.DONE, "", ""): DisplayState.DONE,
            (ItemStatus.ERROR, "", ""): DisplayState.ERROR,
            (ItemStatus.ERROR, SAVED_PATH, ""): DisplayState.ERROR,
        }
        for fields, state in expected.items():
            with self.subTest(fields=fields):
                self.assertIs(make_item(*fields).display_state, state)

    def test_transitions(self):
        from app.core.queue_model import DisplayState

        item = make_item(ItemStatus.PENDING, "", "")
        self.assertIs(item.display_state, DisplayState.PENDING)

        item.mark_converting()
        self.assertIs(item.display_state, DisplayState.CONVERTING)

        item.mark_converted("# text")
        self.assertIs(item.display_state, DisplayState.DONE)
        self.assertEqual(item.markdown_result, "# text")
        self.assertEqual(item.error_message, "")

        item.mark_saved("/out/a.md")
        self.assertIs(item.display_state, DisplayState.SAVED)
        self.assertEqual(item.saved_path, "/out/a.md")
        self.assertEqual(item.save_error, "")

        item.mark_failed("boom")
        self.assertIs(item.display_state, DisplayState.ERROR)
        self.assertEqual(item.error_message, "boom")
        self.assertEqual(item.saved_path, "/out/a.md", "a failed retry keeps the earlier file")

        item.mark_converted("# text")
        item.mark_save_failed("disk full")
        self.assertIs(item.display_state, DisplayState.SAVE_FAILED)
        self.assertEqual(item.saved_path, "")
        self.assertEqual(item.save_error, "disk full")


if __name__ == "__main__":
    unittest.main()
