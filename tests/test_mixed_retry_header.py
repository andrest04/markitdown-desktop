"""The header's Retry is there whenever Retry is, and Enter stays with its own row."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from qt_support import WindowTestCase, process_events, pump_until, settle

from app.core.queue_model import DisplayState, ItemStatus


class MixedSelectionTestCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        self.add_sources("good.txt")
        self.converter.release("good.txt")
        self.good = self.item_named("good.txt")
        self.assertTrue(pump_until(lambda: self.good.display_state == DisplayState.SAVED))
        self.converter.failures["bad.txt"] = "boom"
        self.add_sources("bad.txt")
        self.converter.release("bad.txt")
        self.bad = self.item_named("bad.txt")
        self.assertTrue(pump_until(lambda: self.bad.status == ItemStatus.ERROR))
        settle()
        del self.converter.failures["bad.txt"]

    def select_both_with_the_saved_row_first(self) -> None:
        self.window.table_view.selectAll()
        process_events()
        self.assertEqual(self.window._selected_row(), 0)

    def visible_primaries(self) -> list:
        return [
            button
            for button in (
                self.window.retry_header_btn,
                self.window.copy_btn,
                self.window.open_file_btn,
                self.window.reveal_btn,
            )
            if not button.isHidden() and button.property("tier") == "primary"
        ]


class HeaderRetryTests(MixedSelectionTestCase):
    def test_a_saved_row_first_still_shows_retry(self):
        self.select_both_with_the_saved_row_first()
        self.assertTrue(self.window.retry_action.isEnabled())
        self.assertFalse(self.window.retry_header_btn.isHidden())

    def test_one_primary_and_it_is_retry(self):
        self.select_both_with_the_saved_row_first()
        self.assertEqual(self.visible_primaries(), [self.window.retry_header_btn])

    def test_the_rest_of_the_header_still_describes_the_first_row(self):
        self.select_both_with_the_saved_row_first()
        self.assertFalse(self.window.open_file_btn.isHidden())
        self.assertIn("good", self.window.preview_header_status.text())

    def test_the_button_retries_only_the_row_that_needs_it(self):
        self.select_both_with_the_saved_row_first()
        self.converter.release_all()
        self.window.retry_header_btn.click()
        settle()
        self.assertEqual(self.converter.call_count("good.txt"), 1)
        self.assertEqual(self.converter.call_count("bad.txt"), 2)
        self.assertEqual(self.downloaded_names(), ["bad.md", "good.md"])

    def test_it_goes_away_when_nothing_selected_needs_it(self):
        self.window.table_view.selectRow(0)
        process_events()
        self.assertTrue(self.window.retry_header_btn.isHidden())
        self.assertEqual(self.visible_primaries(), [self.window.copy_btn])

    def test_it_goes_away_when_the_other_row_stops_needing_it(self):
        self.select_both_with_the_saved_row_first()
        self.converter.release_all()
        self.window.retry_header_btn.click()
        settle()
        self.assertFalse(self.window.retry_action.isEnabled())
        self.assertTrue(self.window.retry_header_btn.isHidden())

    def test_it_appears_when_the_other_row_comes_to_need_it(self):
        self.window.table_view.selectRow(1)
        self.converter.release_all()
        self.window._start_conversion([1])
        settle()
        self.converter.hold_all()
        self.assertTrue(self.bad.display_state == DisplayState.SAVED)

        self.select_both_with_the_saved_row_first()
        self.assertTrue(self.window.retry_header_btn.isHidden())
        self.converter.failures["bad.txt"] = "boom"
        self.converter.release("bad.txt")
        self.window.conversion_queue.enqueue([self.bad], self.window.conversion_options)
        self.assertTrue(pump_until(lambda: self.bad.status == ItemStatus.ERROR))
        settle()

        self.assertFalse(self.window.retry_header_btn.isHidden())


class EnterTests(MixedSelectionTestCase):
    def press_enter_on(self, row: int) -> None:
        self.select_both_with_the_saved_row_first()
        self.window.table_view.selectionModel().setCurrentIndex(
            self.window.model.index(row, 0), self.window.table_view.selectionModel().SelectionFlag.NoUpdate
        )
        self.window.table_view.setFocus()
        self.converter.release_all()
        QTest.keyClick(self.window.table_view, Qt.Key.Key_Return)
        settle()

    def test_enter_on_the_saved_row_does_nothing(self):
        self.press_enter_on(0)
        self.assertEqual(self.converter.call_count("good.txt"), 1)
        self.assertEqual(self.converter.call_count("bad.txt"), 1)

    def test_enter_on_the_failed_row_retries_that_row(self):
        self.press_enter_on(1)
        self.assertEqual(self.converter.call_count("good.txt"), 1)
        self.assertEqual(self.converter.call_count("bad.txt"), 2)

    def test_enter_retries_its_own_row_and_not_the_others_selected(self):
        self.converter.failures["worse.txt"] = "boom"
        self.add_sources("worse.txt")
        self.converter.release("worse.txt")
        self.assertTrue(pump_until(lambda: self.item_named("worse.txt").status == ItemStatus.ERROR))
        settle()
        del self.converter.failures["worse.txt"]

        self.press_enter_on(2)

        self.assertEqual(self.converter.call_count("worse.txt"), 2)
        self.assertEqual(self.converter.call_count("bad.txt"), 1)
        self.assertEqual(self.converter.call_count("good.txt"), 1)
