"""What each state shows: one primary action, reachable actions, deliberate selection."""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, Qt, QUrl
from PySide6.QtGui import QColor, QDragMoveEvent, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
)
from qt_support import WindowTestCase, process_events, pump_until

from app.core.queue_model import DisplayState, ItemStatus, QueueItem, SourceKind
from app.i18n import LANG_EN, LANG_ES, TRANSLATIONS, tr
from app.i18n import manager as i18n_manager
from app.ui.queue_delegate import ROW_HEIGHT, QueueItemDelegate, status_style
from app.ui.theme import READING_WIDTH, tokens_for


def make_item(name, status=ItemStatus.PENDING, saved="", save_error="", error="", result=None):
    return QueueItem(
        source=f"/somewhere/{name}",
        kind=SourceKind.FILE,
        display_name=name,
        detected_type="TXT",
        status=status,
        saved_path=saved,
        save_error=save_error,
        error_message=error,
        markdown_result=result,
    )


SAVED = {"status": ItemStatus.DONE, "saved": "/x/a.md", "result": "# a"}
SAVE_FAILED = {"status": ItemStatus.DONE, "save_error": "disk full", "result": "# a"}
FAILED = {"status": ItemStatus.ERROR, "error": "boom"}


class LayoutTestCase(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.resize(1000, 700)
        self.window.show()
        process_events()

    def add_and_select(self, **fields):
        self.window.model.add_item(make_item("a.txt", **fields))
        self.window._update_drop_zone_prominence()
        self.window.table_view.selectRow(self.window.model.rowCount() - 1)
        process_events()

    def visible_primaries(self):
        return [
            button
            for button in self.window.findChildren(QPushButton)
            if button.isVisible() and button.property("tier") == "primary"
        ]


class PrimaryActionTests(LayoutTestCase):
    def test_empty_queue_primary_is_add_files(self):
        self.assertEqual(self.visible_primaries(), [self.window.drop_zone.browse_btn])

    def test_saved_primary_is_copy(self):
        self.add_and_select(**SAVED)
        self.assertEqual(self.visible_primaries(), [self.window.copy_btn])
        self.assertTrue(self.window.open_file_btn.isVisible())
        self.assertTrue(self.window.reveal_btn.isVisible())

    def test_failures_primary_is_retry(self):
        for fields in (FAILED, SAVE_FAILED):
            with self.subTest(fields=fields):
                self.window.model.clear()
                self.add_and_select(**fields)
                self.assertEqual(self.visible_primaries(), [self.window.retry_header_btn])

    def test_a_save_failure_can_still_copy_but_a_failure_cannot(self):
        self.add_and_select(**SAVE_FAILED)
        self.assertTrue(self.window.copy_btn.isVisible())
        self.window.model.clear()
        self.add_and_select(**FAILED)
        self.assertFalse(self.window.copy_btn.isVisible())

    def test_nothing_to_do_while_waiting_or_converting(self):
        for status in (ItemStatus.PENDING, ItemStatus.CONVERTING):
            with self.subTest(status=status):
                self.window.model.clear()
                self.add_and_select(status=status)
                self.assertEqual(self.visible_primaries(), [])


class ReachabilityTests(LayoutTestCase):
    def _all_menu_actions(self):
        menus = [self.window.file_menu, self.window.edit_menu, self.window.view_menu, self.window.help_menu]
        return {action for menu in menus for action in menu.actions()}

    def test_every_capability_has_a_menu_action(self):
        window = self.window
        for name in (
            "add_files_action", "add_folder_action", "add_url_action", "open_file_action",
            "reveal_action", "save_copy_action", "export_all_action", "copy_action",
            "retry_action", "remove_action", "clear_action", "advanced_settings_action",
        ):
            with self.subTest(action=name):
                self.assertIn(getattr(window, name), self._all_menu_actions())

    def test_more_holds_the_secondary_item_actions(self):
        actions = self.window.more_btn.menu().actions()
        for action in (self.window.save_copy_action, self.window.export_all_action, self.window.remove_action):
            self.assertIn(action, actions)

    def test_actions_follow_the_selected_item(self):
        window = self.window
        self.add_and_select(**SAVED)
        self.assertTrue(window.copy_action.isEnabled())
        self.assertTrue(window.open_file_action.isEnabled())
        self.assertFalse(window.retry_action.isEnabled())
        window.model.clear()
        self.add_and_select(**FAILED)
        self.assertFalse(window.copy_action.isEnabled())
        self.assertFalse(window.open_file_action.isEnabled())
        self.assertTrue(window.retry_action.isEnabled())

    def test_buttons_take_keyboard_focus_only_from_tab(self):
        for button in self.window.findChildren(QPushButton):
            with self.subTest(button=button.text()):
                self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.TabFocus)


class SelectionPaintTests(LayoutTestCase):
    def _viewport_image(self) -> QImage:
        return self.window.table_view.viewport().grab().toImage()

    def _assert_row_color(self, image, row, expected):
        top = row * ROW_HEIGHT
        width = image.width()
        for x, y in (
            (0, top), (width - 1, top), (0, top + ROW_HEIGHT - 1), (width - 1, top + ROW_HEIGHT - 1),
            (width // 2, top + 1),
        ):
            with self.subTest(x=x, y=y):
                self.assertEqual(image.pixelColor(x, y), QColor(expected))

    def test_selected_row_fill_is_one_clean_band_with_no_bleed(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                self.window._set_theme_preference(theme)
                self.window.model.clear()
                for name in ("a.txt", "b.txt", "c.txt"):
                    self.window.model.add_item(make_item(name))
                self.window._update_drop_zone_prominence()
                self.window.table_view.selectRow(1)
                process_events()
                tokens = tokens_for(theme)
                image = self._viewport_image()
                self._assert_row_color(image, 1, tokens.wash)
                self._assert_row_color(image, 0, tokens.desk)
                self._assert_row_color(image, 2, tokens.desk)
                # The first empty pixel below the last row is plain desk too.
                self.assertEqual(image.pixelColor(0, 3 * ROW_HEIGHT), QColor(tokens.desk))

    def test_keyboard_focus_on_a_row_is_visible(self):
        # Offscreen windows never become active, so paint the row directly.
        self.add_and_select(**SAVED)
        view = self.window.table_view
        index = self.window.model.index(0, 0)

        def paint(extra_state):
            option = QStyleOptionViewItem()
            option.initFrom(view.viewport())
            option.rect = QRect(0, 0, 300, ROW_HEIGHT)
            option.state = QStyle.StateFlag.State_Selected | extra_state
            image = QImage(300, ROW_HEIGHT, QImage.Format.Format_RGB32)
            painter = QPainter(image)
            view.itemDelegate().paint(painter, option, index)
            painter.end()
            return image

        ink = QColor(tokens_for("light").ink)
        fill = QColor(tokens_for("light").wash)
        self.assertEqual(paint(QStyle.StateFlag.State_None).pixelColor(150, 0), fill)
        self.assertEqual(paint(QStyle.StateFlag.State_HasFocus).pixelColor(150, 0), ink)


class StatusNeverByColorAloneTests(unittest.TestCase):
    def test_each_state_has_its_own_glyph(self):
        glyphs = {state: status_style(state).glyph for state in DisplayState}
        self.assertEqual(len(set(glyphs.values())), len(DisplayState))

    def test_only_links_show_a_type_because_a_file_name_has_one(self):
        delegate = QueueItemDelegate()
        self.assertEqual(delegate._type_label(make_item("a.txt")), "")
        link = QueueItem.from_url("https://www.youtube.com/watch?v=x")
        self.assertEqual(delegate._type_label(link), "YouTube")

    def test_failure_keeps_its_color_on_a_selected_row(self):
        delegate = QueueItemDelegate()
        tokens = tokens_for("light")
        _, color = delegate._status_parts(make_item("a.txt", **FAILED), tokens)
        self.assertEqual(color, tokens.danger)


class DropAnywhereTests(LayoutTestCase):
    def _url_mime(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.make_source("a.txt"))])
        return mime

    def test_the_overlay_answers_a_held_file(self):
        window = self.window
        self.assertFalse(window.drag_overlay.isVisible())
        window.drop_zone.set_drag_active(True)
        self.assertTrue(window.drag_overlay.isVisible())
        self.assertEqual(window.drag_overlay.geometry(), window.centralWidget().rect())
        window.drop_zone.set_drag_active(False)
        self.assertFalse(window.drag_overlay.isVisible())

    def test_the_overlay_never_takes_the_drop(self):
        self.assertTrue(self.window.drag_overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_drag_move_is_accepted_over_views_that_would_refuse_it(self):
        self.window.model.add_item(make_item("a.txt"))
        self.window._update_drop_zone_prominence()
        mime = self._url_mime()
        for name, widget in (("table", self.window.table_view.viewport()), ("raw", self.window.raw_view.viewport())):
            with self.subTest(widget=name):
                event = QDragMoveEvent(
                    QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                )
                event.ignore()
                # QApplication drops DragMove unless a real drag is running, so
                # go through the filter the way Qt would during one.
                self.assertTrue(self.window.drop_zone._drop_filter.eventFilter(widget, event))
                self.assertTrue(event.isAccepted())

    def test_a_text_drag_still_reaches_the_markdown_editor(self):
        mime = QMimeData()
        mime.setText("plain")
        event = QDragMoveEvent(
            QPoint(1, 1), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        filter_ = self.window.drop_zone._drop_filter
        self.assertFalse(filter_.eventFilter(self.window.raw_view.viewport(), event))


class ProminenceTests(LayoutTestCase):
    def test_nothing_is_ringed_on_launch(self):
        self.assertNotIsInstance(self.window.focusWidget(), (QPushButton, QLineEdit))

    def test_empty_has_no_status_strip_and_populated_does(self):
        self.assertFalse(self.window.status_bar.isVisible())
        self.add_and_select(**SAVED)
        self.assertTrue(self.window.status_bar.isVisible())

    def test_empty_shows_the_instruction_and_no_list(self):
        zone = self.window.drop_zone
        self.assertTrue(zone._title.isVisible())
        self.assertTrue(zone.browse_btn.isVisible())
        self.assertFalse(self.window.table_view.isVisible())
        self.assertFalse(self.window.preview_panel.isVisible())

    def test_populated_keeps_only_the_link_field_above_the_list(self):
        self.add_and_select(**SAVED)
        zone = self.window.drop_zone
        self.assertFalse(zone._title.isVisible())
        self.assertFalse(zone.browse_btn.isVisible())
        self.assertTrue(zone.url_edit.isVisible())
        self.assertTrue(self.window.table_view.isVisible())
        self.assertTrue(self.window.add_files_btn.isVisible())
        self.assertTrue(self.window.clear_btn.isVisible())

    def _settle_layout(self):
        # A layout change posts a LayoutRequest that posts another for its parent.
        for _ in range(4):
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            process_events()

    def _minimum_width_with_name(self, name):
        self.window.model.clear()
        self.window.model.add_item(make_item(name, **SAVED))
        self.window._update_drop_zone_prominence()
        self.window.table_view.selectRow(0)
        self._settle_layout()
        return self.window.minimumSizeHint().width()

    def test_a_long_unbroken_name_does_not_widen_the_window(self):
        short = self._minimum_width_with_name("a.pdf")
        self.assertEqual(self._minimum_width_with_name("x" * 400 + ".pdf"), short)
        self.window.resize(800, 600)
        self._settle_layout()
        title = self.window.preview_header_name
        self.assertIn("…", title.text())
        self.assertTrue(title.text().endswith(".pdf"))
        self.assertLessEqual(title.fontMetrics().horizontalAdvance(title.text()), title.width())

    def test_the_action_row_never_clips_at_the_narrow_width(self):
        for language in (LANG_EN, LANG_ES):
            with self.subTest(language=language):
                i18n_manager.set_language(language, self.window.settings)
                self.window.model.clear()
                self.add_and_select(**SAVED)
                # Whatever a font needs, the window grows rather than clip.
                self.window.resize(800, 600)
                self._settle_layout()
                for button in (self.window.copy_btn, self.window.open_file_btn, self.window.reveal_btn):
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())

    def test_rendered_markdown_stops_at_the_reading_measure(self):
        self.add_and_select(**SAVED)
        self.window.resize(1600, 800)
        process_events()
        view = self.window.rendered_view
        self.assertGreater(view.viewport().width(), READING_WIDTH)
        self.assertEqual(view.lineWrapColumnOrWidth(), READING_WIDTH)
        self.window.resize(800, 600)
        process_events()
        self.assertLessEqual(view.lineWrapColumnOrWidth(), view.viewport().width())


class SpinnerTests(LayoutTestCase):
    def _convert_one(self):
        self.add_sources("a.txt")
        self.wait_started(1)
        return self.window._spinner

    def test_ticks_only_while_something_converts(self):
        with mock.patch.object(QApplication, "isEffectEnabled", return_value=True):
            spinner = self._convert_one()
            self.assertTrue(pump_until(spinner.isActive))
            self.converter.release("a.txt")
            self.assertTrue(pump_until(lambda: not spinner.isActive()))

    def test_holds_still_when_system_effects_are_off(self):
        with mock.patch.object(QApplication, "isEffectEnabled", return_value=False):
            spinner = self._convert_one()
            self.assertTrue(pump_until(lambda: self.item_named("a.txt").status == ItemStatus.CONVERTING))
            self.assertFalse(spinner.isActive())


class RetranslateTests(LayoutTestCase):
    def test_new_controls_follow_a_live_language_switch(self):
        self.add_and_select(**SAVED)
        i18n_manager.set_language(LANG_ES, self.window.settings)
        window = self.window
        for widget, key in (
            (window.more_btn, "button.more"),
            (window.add_files_btn, "button.add_files"),
            (window.clear_btn, "button.clear_all"),
            (window.copy_btn, "button.copy_raw"),
            (window.drag_overlay, "overlay.drop"),
            (window.drop_zone.browse_btn, "button.add_files"),
        ):
            self.assertEqual(widget.text(), TRANSLATIONS[LANG_ES][key])
        self.assertEqual(window.copy_action.text(), TRANSLATIONS[LANG_ES]["button.copy_raw"])


class CopyFeedbackTests(LayoutTestCase):
    def test_copy_confirms_on_the_button_then_restores(self):
        self.add_and_select(**SAVED)
        self.window.action_copy_raw()
        self.assertEqual(self.window.copy_btn.text(), tr("button.copied"))
        self.window._copy_feedback.timeout.emit()
        self.assertEqual(self.window.copy_btn.text(), tr("button.copy_raw"))


if __name__ == "__main__":
    unittest.main()
