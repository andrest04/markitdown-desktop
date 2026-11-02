"""WCAG contrast, computed from the real theme tokens in both themes."""
from __future__ import annotations

import unittest

from app.ui.theme import tokens_for

TEXT_AA = 4.5
NON_TEXT_AA = 3.0

# (foreground token, background token): every pairing the UI actually paints.
TEXT_PAIRS = [
    # Body and secondary text on each surface.
    ("ink", "paper"),
    ("ink", "desk"),
    ("ink", "hover"),
    ("ink", "wash"),
    ("ink", "wash_strong"),
    ("muted", "paper"),
    ("muted", "desk"),
    ("muted", "hover"),
    ("muted", "wash"),
    # Failure text wherever a status can appear.
    ("danger", "paper"),
    ("danger", "desk"),
    ("danger", "hover"),
    ("danger", "wash"),
    # Primary action in each of its states.
    ("primary_fg", "ink"),
    ("primary_fg", "primary_hover"),
    ("primary_fg", "primary_pressed"),
    # Anything on the highlighter: the selected name, text selection, the empty
    # state instruction, the drag overlay, a focused primary action.
    ("on_mark", "mark"),
]

# WCAG 1.4.11: control boundaries and meaningful graphics.
NON_TEXT_PAIRS = [
    ("edge", "paper"),
    ("edge", "desk"),
    # Focus ring on a quiet control or a row, selected or not; the product mark.
    ("ink", "desk"),
    ("ink", "paper"),
    ("ink", "wash"),
    ("on_mark", "mark"),
    # State marks and the row's retry outline, on every row fill.
    ("muted", "desk"),
    ("muted", "hover"),
    ("muted", "wash"),
    ("danger", "desk"),
    ("danger", "hover"),
    ("danger", "wash"),
    ("edge", "hover"),
    ("edge", "wash"),
    # Progress bar chunk on its track.
    ("ink", "wash"),
]


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class ContrastHelperTests(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(contrast("#000000", "#FFFFFF"), 21.0)
        self.assertAlmostEqual(contrast("#777777", "#FFFFFF"), 4.48, places=2)


class ThemeContrastTests(unittest.TestCase):
    def _assert_pairs(self, pairs, minimum):
        for theme in ("light", "dark"):
            tokens = tokens_for(theme)
            for foreground, background in pairs:
                with self.subTest(theme=theme, foreground=foreground, background=background):
                    ratio = contrast(getattr(tokens, foreground), getattr(tokens, background))
                    self.assertGreaterEqual(ratio, minimum, f"{ratio:.2f}:1")

    def test_text_meets_aa(self):
        self._assert_pairs(TEXT_PAIRS, TEXT_AA)

    def test_controls_and_graphics_meet_aa(self):
        self._assert_pairs(NON_TEXT_PAIRS, NON_TEXT_AA)

    def test_the_mark_stands_out_from_both_surfaces_in_dark(self):
        # On a light sheet the stroke is carried by its hue and the ink on top
        # of it; on the dark sheet it must also clearly read as a band.
        tokens = tokens_for("dark")
        self.assertGreaterEqual(contrast(tokens.mark, tokens.paper), NON_TEXT_AA)
        self.assertGreaterEqual(contrast(tokens.mark, tokens.desk), NON_TEXT_AA)


if __name__ == "__main__":
    unittest.main()
