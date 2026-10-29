"""
Tests for engine/translate.py that need no key, no network and no SDK.

    python3 -m unittest discover tests

The call itself is replaced by a fake client that records exactly what would
have left the machine, so the perimeter can be asserted on rather than assumed.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "engine"))

import translate as T  # noqa: E402

# Clients from the synthetic book in data/ — invented people
HO = {"client_id": "CL-0012", "client_name": "Vivian Ho Wai Man", "age": "66",
      "reporting_language": "Traditional Chinese"}
DANIEL = {"client_id": "CL-0018", "client_name": "Daniel Okafor-Lee", "age": "36",
          "reporting_language": "English"}
ARJUN = {"client_id": "CL-0004", "client_name": "Arjun Mehta", "age": "39",
         "reporting_language": "English"}
LIM_FO = {"client_id": "CL-0008", "client_name": "Lim Heng Family Office", "age": "",
          "reporting_language": "English"}


class Figures(unittest.TestCase):

    def test_plain_figures(self):
        self.assertEqual(T.figures("USD 7.7m against a 70% trigger, at 69.4%"),
                         {"7.7", "70", "69.4"})

    def test_thousands_separators_normalise(self):
        self.assertEqual(T.figures("USD 1,280,000"), T.figures("USD 1280000"))

    def test_trailing_zeros_normalise(self):
        self.assertEqual(T.figures("7.70 and 13.0x"), {"7.7", "13"})

    def test_figure_glued_to_cjk_is_seen(self):
        # the whole point of the narrow lookbehind: \\w would hide these
        self.assertEqual(T.figures("您有約768萬美元的款項"), {"768"})
        self.assertEqual(T.figures("自2027年起"), {"2027"})

    def test_figure_glued_to_latin_is_seen(self):
        self.assertEqual(T.figures("USD7.7m"), {"7.7"})

    def test_identifiers_are_not_figures(self):
        self.assertEqual(T.figures("CF-0002 in PF-0016 and INS-AL-007"), set())

    def test_both_ends_of_a_range(self):
        self.assertEqual(T.figures("a 30-55% band"), {"30", "55"})

    def test_iso_date_is_one_figure(self):
        self.assertEqual(T.figures("marked 2025-09-30"), {"2025-09-30"})

    def test_counting_numbers_are_exempt(self):
        # "twelve months" may fairly become 12個月
        self.assertEqual(T.figures("12個月 and 2 children"), set())

    def test_tokens_are_not_figures(self):
        self.assertEqual(T.figures("Dear [[NAME_2]], USD 15m"), {"15"})


class Check(unittest.TestCase):

    def test_unit_conversion_is_caught(self):
        r = T.check("You have about USD 7.7m falling due.", "您約有770萬美元到期。")
        self.assertEqual(r["added"], ["770"])
        self.assertEqual(r["dropped"], ["7.7"])
        self.assertFalse(T.clean(r))

    def test_faithful_translation_is_clean(self):
        r = T.check("Your facility is drawn at 69.4% against a 70% trigger.",
                    "您的信貸額度已動用至69.4%，而補繳水平為70%。")
        self.assertTrue(T.clean(r), r)

    def test_lost_and_invented_names(self):
        r = T.check("Dear [[FIRST_NAME]],\n\n[[RM_NAME]]", "親愛的[[NAME_1]]：")
        self.assertEqual(r["names_lost"], ["[[FIRST_NAME]]", "[[RM_NAME]]"])
        self.assertEqual(r["names_invented"], ["[[NAME_1]]"])


class Identifiers(unittest.TestCase):

    def test_cjk_salutation_is_the_whole_name(self):
        text, restore = T.tokenise("Dear Vivian Ho Wai Man,\n\nMrs Ho asked about it.", HO)
        self.assertEqual(text, "Dear [[FIRST_NAME]],\n\nMrs [[NAME_1]] asked about it.")
        self.assertEqual(restore, {"[[FIRST_NAME]]": "Vivian Ho Wai Man", "[[NAME_1]]": "Ho"})

    def test_name_glued_to_chinese_is_still_caught(self):
        text, _ = T.tokenise("Vivian Ho Wai Man您好：", HO)
        self.assertEqual(text, "[[FIRST_NAME]]您好：")

    def test_western_salutation_is_the_first_name(self):
        text, restore = T.tokenise("Dear Arjun,\n\nThe Mehta trust...", ARJUN)
        self.assertEqual(text, "Dear [[FIRST_NAME]],\n\nThe [[NAME_1]] trust...")
        self.assertEqual(restore["[[FIRST_NAME]]"], "Arjun")

    def test_hyphenated_surname(self):
        text, _ = T.tokenise("Mr Okafor-Lee", DANIEL)
        self.assertNotIn("Okafor", text)

    def test_an_entity_is_greeted_by_its_whole_name(self):
        self.assertEqual(T.salutation_for(LIM_FO), "Lim Heng Family Office")
        # and the generic words in its name are not treated as identifiers
        text, _ = T.tokenise("Dear Lim Heng Family Office,\n\nYour family office...", LIM_FO)
        self.assertEqual(text, "Dear [[FIRST_NAME]],\n\nYour family office...")

    def test_exact_age_is_tokenised_but_figures_are_not(self):
        text, restore = T.tokenise("At 66 she draws 66% less.", HO)
        self.assertEqual(text, "At [[AGE]] she draws 66% less.")
        self.assertEqual(restore["[[AGE]]"], "66")
        text, _ = T.tokenise("At 66, not USD 66,000 or 66.5.", HO)
        self.assertEqual(text, "At [[AGE]], not USD 66,000 or 66.5.")

    def test_rm_and_bank_signature_in_every_form(self):
        text, _ = T.tokenise("順頌時祺\n張慧玲\n翰登銀行", HO)
        self.assertEqual(text, "順頌時祺\n[[RM_NAME]]\n[[BANK]]")
        text, _ = T.tokenise("With best regards,\nClara Teo\nHalden Rowe", HO)
        self.assertEqual(text, "With best regards,\n[[RM_NAME]]\n[[BANK]]")

    def test_restore_uses_the_target_languages_form(self):
        _, restore = T.tokenise("Dear Vivian Ho Wai Man,", HO)
        out = T.restore_names("[[FIRST_NAME]] 您好：\n\n順頌時祺\n[[RM_NAME]]\n[[BANK]]",
                              restore, "Traditional Chinese")
        self.assertEqual(out, "Vivian Ho Wai Man 您好：\n\n順頌時祺\n張慧玲\n翰登銀行")
        out = T.restore_names("[[RM_NAME]], [[BANK]]", {}, "Japanese")
        self.assertEqual(out, "クララ・テオ, ハルデン・ロウ")
        # Korean has no letter frames, but a translated letter still signs properly
        out = T.restore_names("[[RM_NAME]]\n[[BANK]]", {}, "Korean")
        self.assertEqual(out, "클라라 테오\n할든 로우")


class FakeClient:
    """Stands in for anthropic.Anthropic(). Records every request."""

    def __init__(self, translation, note="", stop_reason="end_turn"):
        self.requests = []
        body = json.dumps({"translation": translation, "translator_note": note},
                          ensure_ascii=False)
        self._resp = SimpleNamespace(
            stop_reason=stop_reason, stop_details=SimpleNamespace(category="test"),
            model=T.MODEL,
            content=[SimpleNamespace(type="thinking", text=""),
                     SimpleNamespace(type="text", text=body)])
        fake = self

        class _Messages:
            def create(self, **kw):
                fake.requests.append(kw)
                return fake._resp
        self.beta = SimpleNamespace(messages=_Messages())
        self.messages = _Messages()


class EndToEnd(unittest.TestCase):

    ENGLISH = ("Dear Vivian Ho Wai Man,\n\nAbout 26% of your wealth is in bonds that "
               "mature after 2034. At 66, I would rather we talked.\n\n"
               "With best regards,\nClara Teo\nHalden Rowe")

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self._old = T.CACHE_DIR
        T.CACHE_DIR = self.cache

    def tearDown(self):
        T.CACHE_DIR = self._old
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_round_trip_and_perimeter(self):
        client = FakeClient("[[FIRST_NAME]] 您好：\n\n您約26%的資產投資於2034年之後才到期的債券。"
                            "您現年[[AGE]]歲，我希望與您面談。\n\n順頌時祺\n[[RM_NAME]]\n[[BANK]]")
        out = T.translate(self.ENGLISH, "English", "Traditional Chinese", HO, client)

        sent = json.dumps(client.requests[0], ensure_ascii=False)
        for secret in ("Vivian", "Ho ", "Wai Man", "Clara", "Teo", "Halden", " 66"):
            self.assertNotIn(secret, sent, "%r left the perimeter" % secret)
        self.assertIn("output_config", client.requests[0])

        self.assertTrue(out["clean"], out["check"])
        self.assertFalse(out["cached"])
        self.assertTrue(out["text"].startswith("Vivian Ho Wai Man 您好："))
        self.assertIn("現年66歲", out["text"])
        self.assertTrue(out["text"].endswith("張慧玲\n翰登銀行"))

        again = T.translate(self.ENGLISH, "English", "Traditional Chinese", HO,
                            FakeClient("should not be called"))
        self.assertTrue(again["cached"])
        self.assertEqual(again["text"], out["text"])

    def test_converted_amount_is_returned_but_marked(self):
        client = FakeClient("[[FIRST_NAME]] 您好：\n\n約三成半的資產……\n\n[[RM_NAME]]\n[[BANK]]")
        out = T.translate(self.ENGLISH, "English", "Traditional Chinese", HO, client)
        self.assertFalse(out["clean"])
        self.assertIn("26", out["check"]["dropped"])

    def test_refusal_is_an_error_the_rm_can_read(self):
        client = FakeClient("", stop_reason="refusal")
        with self.assertRaises(T.TranslateError) as cm:
            T.translate(self.ENGLISH, "English", "Traditional Chinese", HO, client)
        self.assertEqual(cm.exception.status, 422)

    def test_only_english_and_the_clients_language(self):
        with self.assertRaises(T.TranslateError):
            T.translate(self.ENGLISH, "English", "Japanese", HO, FakeClient("x"))
        with self.assertRaises(T.TranslateError):
            T.translate(self.ENGLISH, "English", "English", HO, FakeClient("x"))

    def test_empty_and_oversized_notes(self):
        with self.assertRaises(T.TranslateError):
            T.translate("   ", "English", "Traditional Chinese", HO, FakeClient("x"))
        with self.assertRaises(T.TranslateError):
            T.translate("x" * (T.MAX_CHARS + 1), "English", "Traditional Chinese", HO,
                        FakeClient("x"))


if __name__ == "__main__":
    unittest.main()
