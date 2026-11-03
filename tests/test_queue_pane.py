"""The list pane answers its question: is it ready, and does anything need me?"""
from __future__ import annotations

import unittest
from itertools import combinations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
)
from qt_support import WindowTestCase, process_events, pump_until

from app.core.queue_model import DisplayState, ItemStatus, QueueItem, SourceKind
from app.i18n import LANG_EN, LANG_ES, tr
from app.i18n import manager as i18n_manager
from app.ui.queue_delegate import ROW_HEIGHT, paint_status_glyph, status_style
from app.ui.theme import tokens_for


def make_item(name="a.txt", status=ItemStatus.PENDING, saved="", save_error="", error="", result=None):
    return QueueItem(
        source=f"/somewhere/{name}",
        kind=SourceKind.FILE,
        display_name=name,
        status=status,
        saved_path=saved,
        save_error=save_error,
        error_message=error,
        markdown_result=result,
    )


def saved(name="a.txt"):
    return make_item(name, ItemStatus.DONE, saved=f"/x/{name}.md", result="# a")


def not_saved(name="b.txt"):
    return make_item(name, ItemStatus.DONE, save_error="disk full", result="# b")


def failed(name="c.txt", error="boom"):
    return make_item(name, ItemStatus.ERROR, error=error)


def converting(name="d.txt"):
    return make_item(name, ItemStatus.CONVERTING)


def waiting(name="e.txt"):
    return make_item(name)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, i18n_manager, "_language", LANG_EN)
        i18n_manager._language = LANG_EN

    def summary(self, *items):
        from app.ui.queue_delegate import queue_summary

        return queue_summary(list(items))

    def test_an_empty_queue_has_no_summary(self):
        self.assertIsNone(self.summary())

    def test_failures_come_first_and_the_rest_follows(self):
        summary = self.summary(saved(), not_saved(), failed(), converting(), waiting())
        self.assertEqual(summary.headline, "1 failed, 1 not saved")
        self.assertEqual(summary.detail, "1 ready, 1 converting, 1 waiting")
        self.assertTrue(summary.attention)
        self.assertEqual(summary.glyph, "failed")

    def test_a_save_failure_alone_uses_the_not_saved_mark(self):
        summary = self.summary(saved(), not_saved())
        self.assertEqual(summary.headline, "1 not saved")
        self.assertEqual(summary.glyph, "warning")

    def test_a_real_zero_is_printed(self):
        summary = self.summary(converting(), waiting())
        self.assertEqual(summary.headline, "0 of 2 ready")
        self.assertEqual(summary.detail, "1 converting, 1 waiting")
        self.assertFalse(summary.attention)
        self.assertEqual(summary.glyph, "working")

    def test_everything_saved_says_so_in_one_line(self):
        self.assertEqual(self.summary(saved("a"), saved("b"), saved("c")).headline, "All 3 saved to Downloads")
        self.assertEqual(self.summary(saved()).headline, "1 saved to Downloads")
        summary = self.summary(saved())
        self.assertEqual(summary.detail, "")
        self.assertEqual(summary.glyph, "saved")

    def test_converted_not_yet_saved_is_ready_but_not_called_saved(self):
        summary = self.summary(saved(), make_item("z", ItemStatus.DONE, result="# z"))
        self.assertEqual(summary.headline, "2 of 2 ready")

    def test_spanish_has_real_plurals(self):
        i18n_manager._language = LANG_ES
        self.assertEqual(self.summary(failed("a"), failed("b")).headline, "2 fallaron")
        self.assertEqual(self.summary(failed()).headline, "1 falló")
        self.assertEqual(self.summary(saved("a"), saved("b")).headline, "Los 2 guardados en Descargas")
        self.assertEqual(self.summary(failed(), waiting(), saved()).detail, "1 listo, 1 en espera")


class RowReasonTests(unittest.TestCase):
    def setUp(self):
        i18n_manager._language = LANG_EN

    def test_a_failed_row_gives_its_reason(self):
        from app.ui.queue_delegate import row_status_text

        self.assertEqual(row_status_text(failed(error="file is encrypted")), "Failed: file is encrypted")
        self.assertEqual(row_status_text(not_saved()), "Not saved: disk full")
        self.assertEqual(row_status_text(saved()), tr("status.done_saved"))

    def test_a_failure_with_no_message_still_says_failed(self):
        from app.ui.queue_delegate import row_status_text

        self.assertEqual(row_status_text(failed(error="")), tr("status.error"))

    def test_the_reason_skips_the_preamble_markitdown_puts_first(self):
        from app.ui.queue_delegate import brief_error

        message = (
            "File conversion failed after 1 attempts:\n"
            " - PdfConverter threw PDFSyntaxError with message: No /Root object\n"
        )
        self.assertEqual(brief_error(message), "No /Root object")

    def test_the_reason_drops_the_system_error_number(self):
        from app.ui.queue_delegate import brief_error

        self.assertEqual(brief_error("[Errno 28] No space left on device"), "No space left on device")
        self.assertEqual(brief_error("[WinError 5] Access is denied"), "Access is denied")

    def test_the_reason_keeps_a_plain_message_and_cuts_a_long_one(self):
        from app.ui.queue_delegate import brief_error

        self.assertEqual(brief_error("Disk full\nmore detail"), "Disk full")
        self.assertEqual(brief_error(""), "")
        self.assertTrue(brief_error("x" * 500).endswith("…"))


class StateMarkTests(unittest.TestCase):
    """Marks must read apart at a glance and in greyscale, with color removed."""

    SIZE = 64

    def _coverage(self, glyph) -> list[bool]:
        image = QImage(self.SIZE, self.SIZE, QImage.Format.Format_Grayscale8)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_status_glyph(painter, QRect(0, 0, self.SIZE, self.SIZE), glyph, "#000000", "#FFFFFF")
        painter.end()
        return [
            image.pixelColor(x, y).lightness() < 128
            for y in range(self.SIZE)
            for x in range(self.SIZE)
        ]

    def _glyphs(self):
        return {state: status_style(state).glyph for state in DisplayState}

    def test_every_pair_of_marks_differs_in_shape(self):
        glyphs = self._glyphs()
        for (first, a), (second, b) in combinations(glyphs.items(), 2):
            with self.subTest(first=first, second=second):
                changed = sum(x != y for x, y in zip(self._coverage(a), self._coverage(b)))
                self.assertGreater(changed / self.SIZE ** 2, 0.12)

    def test_failure_is_the_heaviest_mark_and_saved_stays_calm(self):
        glyphs = self._glyphs()
        weight = {state: sum(self._coverage(glyph)) for state, glyph in glyphs.items()}
        self.assertGreater(weight[DisplayState.ERROR], 2 * weight[DisplayState.SAVED])
        self.assertGreater(weight[DisplayState.ERROR], 1.5 * weight[DisplayState.SAVE_FAILED])
        self.assertEqual(max(weight, key=weight.get), DisplayState.ERROR)


class PaneTestCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window._set_theme_preference("light")
        self.window.resize(1000, 700)
        self.window.show()
        process_events()

    def add(self, *items):
        for item in items:
            self.window.model.add_item(item)
        self.window._update_drop_zone_prominence()
        process_events()


class SummaryWiringTests(PaneTestCase):
    def test_the_line_follows_the_model(self):
        window = self.window
        self.assertFalse(window.queue_summary.isVisible())
        item = waiting()
        self.add(item)
        self.assertTrue(window.queue_summary.isVisible())
        self.assertEqual(window.summary_headline.text(), "0 of 1 ready")
        item.mark_failed("boom")
        window.model.refresh_row(0)
        self.assertEqual(window.summary_headline.text(), "1 failed")
        self.assertTrue(window.summary_headline.property("attention"))
        window.model.clear()
        self.assertFalse(window.queue_summary.isVisible())

    def test_it_retranslates_live(self):
        self.add(failed())
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertEqual(self.window.summary_headline.text(), "1 falló")


class RetryOnTheRowTests(PaneTestCase):
    def _action_point(self, row):
        from app.ui.queue_delegate import retry_rect

        view = self.window.table_view
        cell = view.visualRect(self.window.model.index(row, 0))
        rect = retry_rect(cell, self.window.model.item_at(row))
        self.assertIsNotNone(rect, "this row should carry the action")
        return rect.center()

    def test_only_rows_that_need_it_carry_the_action(self):
        from app.ui.queue_delegate import retry_rect

        cell = QRect(0, 0, 340, ROW_HEIGHT)
        for item, expected in (
            (failed(), True), (not_saved(), True), (saved(), False), (converting(), False), (waiting(), False),
        ):
            with self.subTest(state=item.display_state):
                self.assertEqual(retry_rect(cell, item) is not None, expected)

    def test_the_action_sits_in_one_column_at_one_pitch(self):
        self.add(failed("a"), saved("b"), not_saved("c"))
        first, third = self._action_point(0), self._action_point(2)
        self.assertEqual(first.x(), third.x())
        self.assertEqual(third.y() - first.y(), 2 * ROW_HEIGHT)

    def test_the_target_is_large_enough_to_hit(self):
        from app.ui.queue_delegate import retry_rect

        rect = retry_rect(QRect(0, 0, 340, ROW_HEIGHT), failed())
        self.assertGreaterEqual(rect.height(), 24)

    def test_clicking_it_retries_that_row(self):
        self.add(failed("a.txt"), failed("b.txt"))
        viewport = self.window.table_view.viewport()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self._action_point(1))
        self.assertTrue(pump_until(lambda: self.converter.call_count("b.txt") == 1))
        self.assertEqual(self.converter.call_count("a.txt"), 0)

    def test_clicking_elsewhere_on_the_row_only_selects_it(self):
        self.add(failed("a.txt"))
        viewport = self.window.table_view.viewport()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 10))
        process_events()
        self.assertEqual(self.window._selected_row(), 0)
        self.assertEqual(self.converter.call_count(), 0)

    def test_one_set_of_retry_states_serves_every_place_retry_appears(self):
        from app.ui.queue_delegate import RETRY_STATES

        self.assertEqual(RETRY_STATES, {DisplayState.ERROR, DisplayState.SAVE_FAILED})


class SelectionStrokeTests(PaneTestCase):
    def _paint(self, state):
        self.add(saved("a-file-name.pdf"))
        view = self.window.table_view
        option = QStyleOptionViewItem()
        option.initFrom(view.viewport())
        option.rect = QRect(0, 0, 340, ROW_HEIGHT)
        option.state = state
        image = QImage(340, ROW_HEIGHT, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        view.itemDelegate().paint(painter, option, self.window.model.index(0, 0))
        painter.end()
        return image

    def test_the_stroke_marks_the_name_and_not_the_whole_row(self):
        tokens = tokens_for("light")
        image = self._paint(QStyle.StateFlag.State_Selected)
        marked = sum(
            image.pixelColor(x, y) == QColor(tokens.mark)
            for x in range(image.width())
            for y in range(image.height())
        )
        self.assertGreater(marked, 300, "the selected name must carry the highlighter")
        self.assertLess(marked / (340 * ROW_HEIGHT), 0.2)
        self.assertEqual(image.pixelColor(339, 0), QColor(tokens.wash))

    def test_selected_and_hovered_rows_read_apart(self):
        selected = self._paint(QStyle.StateFlag.State_Selected).pixelColor(339, 0)
        hovered = self._paint(QStyle.StateFlag.State_MouseOver).pixelColor(339, 0)
        self.assertNotEqual(selected, hovered)


class ShellTests(PaneTestCase):
    def test_the_product_is_named_when_empty_and_when_populated(self):
        window = self.window
        self.assertTrue(window.brand_name.isVisible())
        self.assertEqual(window.brand_name.text(), tr("window.title"))
        self.add(saved())
        self.assertTrue(window.brand_name.isVisible())

    def test_the_mark_is_drawn_in_the_highlighter(self):
        tokens = tokens_for("light")
        image = self.window.brand_mark.grab().toImage()
        colors = {
            image.pixelColor(x, y).name().upper()
            for x in range(image.width())
            for y in range(image.height())
        }
        self.assertIn(tokens.mark.upper(), colors)
        self.assertIn(tokens.ink.upper(), colors)

    def test_the_status_strip_says_where_files_go_at_rest(self):
        self.add(saved())
        label = self.window.saving_to_label
        self.assertTrue(label.isVisible())
        self.assertIn(str(self.downloads), label.text())
        i18n_manager.set_language(LANG_ES, self.window.settings)
        self.assertEqual(label.text(), tr("statusbar.saving_to", path=str(self.downloads)))

    def test_a_message_replaces_it_for_a_moment_without_moving_anything(self):
        self.add(saved())
        bar = self.window.status_bar
        height = bar.height()
        bar.showMessage("hello", 1000)
        process_events()
        self.assertEqual(bar.currentMessage(), "hello")
        self.assertEqual(bar.height(), height)

    def test_empty_column_centers_in_the_window_and_the_name_shares_its_edge(self):
        for width in (1280, 1600):
            with self.subTest(width=width):
                self.window.resize(width, 800)
                for _ in range(4):
                    QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
                    process_events()
                from app.ui.drop_zone import empty_column_left

                title = self.window.drop_zone._title
                left = title.mapTo(self.window, QPoint(0, 0)).x()
                zone = self.window.drop_zone
                self.assertLessEqual(abs(left - empty_column_left(width, zone.column_width())), 2)
                brand = self.window.brand_mark.mapTo(self.window, QPoint(0, 0)).x()
                self.assertLessEqual(abs(brand - left), 2)
                self.assertGreater(left, 56)

    def test_the_column_never_caps_the_instruction_in_either_language(self):
        zone = self.window.drop_zone
        for language in (LANG_EN, LANG_ES):
            with self.subTest(language=language):
                i18n_manager.set_language(language, self.window.settings)
                self.assertGreaterEqual(zone._column.maximumWidth(), zone._title.sizeHint().width())

    def test_a_wide_empty_window_can_still_shrink(self):
        self.window.resize(1600, 800)
        process_events()
        self.assertLess(self.window.minimumSizeHint().width(), 800)

    def test_tab_order_follows_the_pane_from_top_to_bottom(self):
        self.add(saved())
        window = self.window
        chain = []
        widget = window.table_view
        for _ in range(40):
            widget = widget.nextInFocusChain()
            if isinstance(widget, (QLineEdit, QPushButton)) and widget.isVisible():
                chain.append(widget)
            if len(chain) == 4:
                break
        zone = window.drop_zone
        self.assertEqual(chain, [zone.url_edit, zone.add_url_btn, window.add_files_btn, window.clear_btn])


if __name__ == "__main__":
    unittest.main()
