"""
The engine against the synthetic book in data/ — the stories the generator
plants, asserted rather than eyeballed. If a change to a rule moves one of these,
the test says which story it broke.

    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

import build  # noqa: E402
from loader import Book  # noqa: E402


class Book_(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.bundle = build.build_bundle(Book(), build.narration(),
                                            build.recorded_translations())
        cls.F = {f["id"]: f for f in cls.bundle["findings"]}
        cls.rank = {r["client_id"]: r for r in cls.bundle["book"]}

    def test_every_dimension_has_something_to_find(self):
        dims = {f["dimension"] for f in self.bundle["findings"]}
        self.assertEqual(dims, {"mandate", "collateral", "funding", "purpose_fit",
                                "concentration", "life_event", "tax", "data_quality"})

    def test_the_bank_error_in_a_sustainable_mandate_ranks_first(self):
        top = self.bundle["book"][0]
        self.assertEqual(top["client_id"], "CL-0005")
        self.assertEqual(self.F["EXC-PF-0006"]["severity"], 98.0)

    def test_one_mandate_breaching_its_exclusions_is_one_finding(self):
        """Three excluded holdings in one portfolio are one problem with one fix:
        one card, one plan, one letter to the client."""
        exc = [f for f in self.bundle["findings"] if f["id"].startswith("EXC-")]
        self.assertEqual([f["id"] for f in exc], ["EXC-PF-0006"])
        f = exc[0]
        self.assertEqual(len(f["numbers"]["holdings"]), 3)
        self.assertNotIn("sustainability_excluded", f["detail"])
        plan = f["plan"]
        self.assertEqual({s["instrument_id"] for s in plan["sells"]},
                         {"INS-EQ-010", "INS-EQ-011"})
        self.assertEqual(plan["shortfall_usd"], plan["blocked"][0]["usd"])

    def test_tiers_are_not_saturated(self):
        acts = [r for r in self.bundle["book"] if r["tier"] == "act"]
        self.assertTrue(2 <= len(acts) <= 5, len(acts))

    def test_selling_collateral_to_fund_the_deposit_trips_the_margin_call(self):
        f = self.F["FUN-CL-0002"]
        self.assertTrue(f["numbers"]["blocked"])
        self.assertGreater(f["numbers"]["collateral"]["repay_first"], 0)
        # the life event is the same obligation and says so
        self.assertEqual(self.F["LIF-CN-002"]["same_fact_as"], "FUN-CL-0002")

    def test_a_breach_cured_by_the_market_is_still_reported(self):
        f = self.F["COL-CF-0002"]
        self.assertLess(f["numbers"]["ltv_pct"], f["numbers"]["trigger_pct"])
        self.assertGreaterEqual(f["severity"], 80.0)

    def test_a_written_waiver_governs_the_breach(self):
        f = self.F["MAN-PF-0008-COMM"]
        self.assertEqual(f["status"], "waived")
        self.assertIn("MAN-PF-0008-COMM", self.rank["CL-0007"]["governed_ids"])

    def test_capital_calls_count_when_their_window_opens_inside_twelve_months(self):
        items = self.F["FUN-CL-0008"]["numbers"]["items"]
        funds = {i["what"] for i in items if i["what"].startswith("Uncalled")}
        self.assertIn("Uncalled: Pan-Asia Logistics Real Estate Fund", funds)  # opens 2027 Q2

    def test_the_stale_mark_says_how_old_it_is(self):
        f = self.F["STA-CL-0004-INS-AL-007"]
        self.assertEqual(f["numbers"]["months_old"], 15)
        self.assertTrue(f["numbers"]["is_collateral"])

    def test_look_through_concentration_repeats_the_source_of_wealth(self):
        f = self.F["CON-CL-0002"]
        self.assertEqual(len(f["numbers"]["via"]), 3)   # shares, accumulator, perpetual
        self.assertTrue(f["numbers"]["same_bet_as_source_of_wealth"])

    def test_no_capital_gains_tax_is_a_non_recommendation(self):
        f = self.F["TAX-CL-0009"]
        self.assertFalse(f["numbers"]["cgt_regime"])
        self.assertEqual(f["severity"], 8.0)

    def test_protected_positions_are_never_proposed_for_sale(self):
        for fid, iid in (("LIM-PF-0002-INS-ST-001", "INS-ST-001"),
                         ("MAN-PF-0003-EQUI", "INS-ST-003"),
                         ("EXC-PF-0006", "INS-ST-009")):
            plan = self.F[fid]["plan"]
            self.assertNotIn(iid, [s["instrument_id"] for s in plan["sells"]], fid)
            self.assertIn(iid, [b["instrument_id"] for b in plan["blocked"]], fid)

    def test_exclusions_only_bind_where_the_mandate_has_them(self):
        plan = self.F["MAN-PF-0012-COMM"]["plan"]
        self.assertFalse(any(s["excluded"] for s in plan["sells"]))
        self.assertLessEqual(plan["raised_usd"], plan["excess_usd"] + 1)

    def test_custody_is_wealth_but_never_measured_against_a_band(self):
        self.assertIn("CON-CL-0020", self.F)
        self.assertFalse([f for f in self.F if f.startswith("MAN-PF-0023")
                          or f.startswith("LIM-PF-0023")])

    def test_finding_text_uses_each_clients_own_pronoun(self):
        """The engine writes about the client in the third person. It once said
        "he" of every client, women and a family office included."""
        self.assertIn("She is 66.", self.F["FIT-CL-0012"]["detail"])
        self.assertIn("plan she can outlive", self.F["FIT-CL-0012"]["action"])
        self.assertIn("He is 68.", self.F["FIT-CL-0001"]["detail"])
        self.assertIn("believe they are protecting", self.F["TAX-CL-0008"]["action"])
        self.assertIn("believe she is protecting", self.F["TAX-CL-0009"]["action"])
        self.assertIn("He would have to repay", self.F["FUN-CL-0002"]["detail"])

    def test_claudes_drafts_are_signed_and_say_where_they_were_written(self):
        """Every open finding ships with a draft that passed the figure check, the
        RM's sign-off in each language, and the place it was written."""
        import clientnote
        for f in self.bundle["findings"]:
            if f["status"] == "waived":
                continue
            d = f.get("draft")
            self.assertTrue(d, f["id"])
            self.assertEqual(d["unverified"], [], f["id"])
            self.assertTrue(d["english"].endswith(clientnote.SIGN["English"]), f["id"])
            self.assertTrue(d["client_language"].endswith(clientnote.SIGN[d["language"]]), f["id"])
            self.assertEqual(d["via"], "Claude Code", f["id"])

    def test_recorded_translations_carry_the_same_figures(self):
        rec = self.bundle["recorded_translations"]
        self.assertEqual({r["finding_id"] for r in rec}, {"FUN-CL-0002", "CON-CL-0011"})
        for r in rec:
            self.assertTrue(r["clean"], r["finding_id"])
            self.assertIn(r["amendment"], r["source"])

    def test_every_finding_has_a_note_in_english(self):
        for f in self.bundle["findings"]:
            self.assertIn("English", f.get("note", {}), f["id"])


    def test_the_committed_bundle_is_what_the_engine_builds(self):
        """app/findings.js is committed so the workbench opens with no Python. If
        data/ or engine/ changed and nobody re-ran engine/build.py, the page and
        the engine quietly disagree — this is the check for that."""
        with open(os.path.join(ROOT, "app", "findings.json"), encoding="utf-8") as fh:
            committed = json.load(fh)
        fresh = json.loads(json.dumps(self.bundle))      # same float formatting
        self.assertTrue(committed == fresh,
                        "app/findings.json is stale — run python3 engine/build.py")

    @unittest.skipIf(shutil.which("node") is None, "node is not installed")
    def test_the_browser_ranking_port_agrees_with_the_engine(self):
        """app/triage.js re-ranks in the browser when the RM retunes the weights.
        At the engine's own settings it must reproduce the engine exactly."""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("window.FINDINGS = " + json.dumps(self.bundle) + ";")
            path = fh.name
        script = ('global.window = {}; const fs = require("fs");'
                  'eval(fs.readFileSync(%s, "utf8"));'
                  'eval(fs.readFileSync(%s, "utf8") + ";global.parityCheck = parityCheck;");'
                  'console.log(JSON.stringify(parityCheck(window.FINDINGS)));'
                  % (json.dumps(path), json.dumps(os.path.join(ROOT, "app", "triage.js"))))
        try:
            out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                 timeout=60, check=True).stdout.strip().splitlines()[-1]
        finally:
            os.unlink(path)
        self.assertEqual(json.loads(out), [])


if __name__ == "__main__":
    unittest.main()
