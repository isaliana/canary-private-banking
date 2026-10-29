"""
The numeric check in engine/narrate.py — the rule that no number reaches a
client unless the engine produced it. Standard library only; calls nothing.

    python3 -m unittest discover tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "engine"))

import narrate as N  # noqa: E402


class Verify(unittest.TestCase):

    def test_invented_figure_in_chinese_is_caught(self):
        # 770 and 99 are glued to Chinese characters; \w would have hidden both
        draft = {"english": "You have about USD 7.7m due.",
                 "client_language": "您約有770萬美元的款項到期，約佔資產的99%。"}
        self.assertEqual(N.verify(draft, ["7.7"]), ["770", "99"])

    def test_invented_figure_in_japanese_is_caught(self):
        draft = {"english": "", "client_language": "ご資産の約45%を占めております。"}
        self.assertEqual(N.verify(draft, ["35"]), ["45"])

    def test_faithful_draft_passes(self):
        draft = {"english": "Your facility is at 69.4% against a 70% trigger.",
                 "client_language": "您的信貸額度已動用至69.4%，而補繳水平為70%。"}
        self.assertEqual(N.verify(draft, ["69.4", "70"]), [])

    def test_identifier_digits_are_still_not_figures(self):
        draft = {"english": "CF-0002 in PF-0016", "client_language": ""}
        self.assertEqual(N.verify(draft, []), [])


class Scrub(unittest.TestCase):
    """What leaves the machine for narration. Clients are from the synthetic book."""

    RAYMOND = {"client_name": "Raymond Wong Ka Lok", "age": "57"}
    LIM_FO = {"client_name": "Lim Heng Family Office", "age": ""}

    def test_age_is_banded_but_a_decimal_containing_it_is_not(self):
        # 57.3% is a loan-to-value; it once went out as "55-59.3%"
        out = N.scrub("He is 57. LTV ran 56.9% -> 57.3% -> 74.4%.", self.RAYMOND)
        self.assertEqual(out, "He is in the 55-59 band. LTV ran 56.9% -> 57.3% -> 74.4%.")

    def test_a_figure_equal_to_the_age_is_not_banded(self):
        # a 50-year-old's 25–50% mandate band once went out as "25–50-54%"
        fatima = {"client_name": "Fatima Al-Suwaidi", "age": "50"}
        out = N.scrub("PF-0011 runs 23.0% against a 25–50% band. At 50, she", fatima)
        self.assertEqual(out, "PF-0011 runs 23.0% against a 25–50% band. At 50-54, she")

    def test_two_letter_name_parts_are_identifiers(self):
        out = N.scrub("Raymond spoke to Mr Wong and Ka Lok's brother.", self.RAYMOND)
        self.assertNotIn("Wong", out)
        self.assertNotIn("Ka Lok", out)

    def test_generic_words_in_an_entity_name_are_not(self):
        out = N.scrub("Family shipping and port logistics business, sold in 2018", self.LIM_FO)
        self.assertEqual(out, "Family shipping and port logistics business, sold in 2018")
        self.assertEqual(N.scrub("Mr Lim Heng called.", self.LIM_FO), "Mr [[FIRST_NAME]] called.")


class ImportDrafts(unittest.TestCase):
    """Drafts written outside the API go through the same door: the schema, the
    figure check, and the cache key a live call would use."""

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "findings.json"), encoding="utf-8") as fh:
            cls.bundle = json.load(fh)
        cls.f = next(f for f in cls.bundle["findings"] if f["id"] == "FUN-CL-0002")

    def run_import(self, draft):
        with tempfile.TemporaryDirectory() as tmp:
            saved, N.CACHE_DIR = N.CACHE_DIR, tmp
            try:
                path = os.path.join(tmp, "drafts.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump({self.f["id"]: draft}, fh)
                out = N.import_drafts(self.bundle, [self.f], path, "Claude Code")
                key = N.cache_key(N.payload_for(self.bundle, self.f))
                return out[self.f["id"]], os.path.exists(os.path.join(tmp, key + ".json"))
            finally:
                N.CACHE_DIR = saved

    def draft(self, english):
        return {"subject": "s", "english": english, "client_language": english, "raises": "r"}

    def test_a_faithful_draft_is_recorded_under_the_live_calls_key(self):
        rec, stored = self.run_import(self.draft("About USD 34.0m could be sold; 68.8% today."))
        self.assertEqual(rec["unverified"], [])
        self.assertEqual(rec["via"], "Claude Code")
        self.assertEqual(rec["usage"]["model"], N.MODEL)
        self.assertTrue(stored)

    def test_an_invented_figure_is_marked_as_a_live_draft_would_be(self):
        rec, _ = self.run_import(self.draft("You could raise USD 41.5m."))
        self.assertEqual(rec["unverified"], ["41.5"])

    def test_a_draft_off_the_schema_is_refused(self):
        bad = dict(self.draft("x"), signature="Clara")
        with self.assertRaises(SystemExit):
            self.run_import(bad)


if __name__ == "__main__":
    unittest.main()
