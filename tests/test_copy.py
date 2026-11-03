"""Every string exists in both languages and follows the copy rules."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.i18n import LANG_EN, LANG_ES, TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
# tr("key") and tr('key'), with or without arguments.
_TR_CALL = re.compile(r"""\btr\(\s*["']([a-z0-9_.]+)["']""")
# Spaced dashes, slashes and middle dots used as separators. URLs are unaffected.
_SEPARATOR = re.compile(r" [-–—/] | · ")
# Rioplatense verb forms the product must never use.
_VOSEO = re.compile(r"\b(soltá|pegá|elegí|seleccioná|hacé|tenés|podés|querés|probá|ingresá|escribí|abrí)\b", re.IGNORECASE)
# Enum values and lookup tables also hold keys, outside a literal tr() call.
_KEY_LITERAL = re.compile(r"""["']((?:status|preview|type|column|button|menu|error)\.[a-z0-9_.]+)["']""")


def _sources() -> str:
    paths = [*ROOT.glob("app/**/*.py")]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.name != "i18n.py")


class TranslationTableTests(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(TRANSLATIONS[LANG_EN]), set(TRANSLATIONS[LANG_ES]))

    def test_every_key_the_code_asks_for_exists(self):
        source = _sources()
        used = set(_TR_CALL.findall(source)) | set(_KEY_LITERAL.findall(source))
        self.assertEqual(sorted(used - set(TRANSLATIONS[LANG_EN])), [])

    def test_no_key_is_dead(self):
        source = _sources()
        dead = [key for key in TRANSLATIONS[LANG_EN] if key not in source]
        self.assertEqual(dead, [])

    def test_placeholders_match_between_languages(self):
        field = re.compile(r"\{(\w+)\}")
        for key, english in TRANSLATIONS[LANG_EN].items():
            with self.subTest(key=key):
                self.assertEqual(
                    sorted(field.findall(english)),
                    sorted(field.findall(TRANSLATIONS[LANG_ES][key])),
                )


class CopyRuleTests(unittest.TestCase):
    def _all_strings(self):
        for language, table in TRANSLATIONS.items():
            for key, value in table.items():
                yield language, key, value

    def test_commas_not_dashes_as_separators(self):
        for language, key, value in self._all_strings():
            with self.subTest(language=language, key=key):
                self.assertIsNone(_SEPARATOR.search(value), value)

    def test_spanish_is_neutral(self):
        for key, value in TRANSLATIONS[LANG_ES].items():
            with self.subTest(key=key):
                self.assertIsNone(_VOSEO.search(value), value)

    def test_labels_use_sentence_case(self):
        # Product names and the file menu's mnemonics aside, one capital only.
        allowed = {"Markdown", "Downloads", "Descargas", "URL", "YouTube", "GitHub"}
        for language, key, value in self._all_strings():
            if not key.startswith(("button.", "menu.", "tab.", "advanced.title", "msgbox.")) or "text" in key:
                continue
            words = value.replace("&", "").replace("…", "").split()
            with self.subTest(language=language, key=key):
                capitalized = [w for w in words[1:] if w[:1].isupper() and w not in allowed]
                self.assertEqual(capitalized, [], value)

    def test_one_action_keeps_one_name(self):
        for table in TRANSLATIONS.values():
            self.assertEqual(table["button.add_files"], table["menu.add_files"])
            self.assertEqual(table["button.add_folder"], table["menu.add_folder"])
            self.assertEqual(table["button.open_file"], table["menu.open_file"])
            self.assertEqual(table["button.open_folder"], table["menu.open_folder"])
            self.assertEqual(table["button.add_files"], table["dialog.add_files"])


if __name__ == "__main__":
    unittest.main()
