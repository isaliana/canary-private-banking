"""
Severity: the 0-100 number, and the arithmetic that produced it.

Two things get confused constantly, so they live apart:

  severity   how bad ONE finding is, 0-100, comparable across dimensions.
             Built here from the calibration table below. It is a property of
             the finding, so changing it means re-running engine/build.py.

  weight     how much a DIMENSION counts when ranking the book, plus the tier
             thresholds. Lives in engine/triage.py, is emitted into the bundle,
             and the workbench lets the RM retune it live with no rebuild.

Every severity is assembled through `Sev`, which records each step it took.
The workbench shows that ladder instead of asserting a total: a number the RM
cannot take apart is a number she cannot defend in front of a client.

    Sev.of("8.9pp over the commodity ceiling", "gap x 2.2 per point", 19.6)
       .times("discretionary mandate", 1.4)
       .cap(95)
"""

# ── calibration ───────────────────────────────────────────────────────────
# One visible block, as with WEIGHTS. Every constant that shapes a severity is
# here; no module invents its own. Ceilings are deliberately not saturating —
# an earlier calibration put nine clients in the act tier, which makes the tier
# meaningless.

MANDATE_BAND_PER_PP      = 2.2    # points of severity per pp outside the band
MANDATE_BAND_CEILING     = 95.0
DISCRETIONARY_X          = 1.4    # the bank chose the position, not the client
DIRECTED_X               = 0.7    # client asked for it and it is on file
WAIVED_X                 = 0.0    # waived in writing: governed, never raised

LIMIT_PER_PP             = 6.0    # single-position limit is a hard cap, so steeper
LIMIT_CEILING            = 90.0

EXCLUSION_DISCRETIONARY  = 98.0   # binding exclusion breached in a bank-run mandate
EXCLUSION_ADVISORY       = 80.0

COLLATERAL_RUNGS = [                       # by headroom to the margin trigger, pp
    (2.0,  95.0, "headroom 2pp or less to the trigger"),
    (6.0,  75.0, "headroom 6pp or less"),
    (12.0, 45.0, "headroom 12pp or less"),
    (1e9,  15.0, "headroom above 12pp"),
]
COLLATERAL_BREACH_FLOOR  = 80.0   # breached at any snapshot in the period
COLLATERAL_REPORT_AT     = 40.0   # below this and unbreached, not worth her time

FUNDING_BLOCKED          = 95.0   # funding the need trips a margin call
FUNDING_RUNGS = [                          # by cover = daily-liquid / 12m need
    (1.0,  85.0, "cover below 1.0x"),
    (1.5,  60.0, "cover below 1.5x"),
    (3.0,  35.0, "cover below 3.0x"),
    (1e9,  12.0, "cover at or above 3.0x"),
]
FUNDING_REPORT_AT        = 30.0

FIT_PER_PCT              = 2.0    # per % of wealth maturing beyond the horizon
FIT_PER_YEAR_BEYOND      = 0.5    # per year the furthest one overshoots
FIT_PERPETUAL_YEARS      = 40     # a perpetual is scored as 40 years beyond
FIT_MIN_SLEEVE           = 8.0    # fires above this share, and only underwater
FIT_CEILING              = 88.0

CON_RUNGS = [                              # by single-name share of total wealth
    (40.0, 88.0, "40% or more of wealth"),
    (30.0, 74.0, "30% or more"),
    (20.0, 60.0, "20% or more"),
    (12.0, 44.0, "12% or more"),
    (0.0,  20.0, "below 12%"),
]
CON_SAME_BET_BONUS       = 8.0    # repeats the source of wealth rather than diversifying
CON_CEILING              = 92.0
CON_REPORT_AT            = 44.0

LIFE_PER_PCT             = 2.6    # per % of wealth the obligation represents
LIFE_CONFIRMED_BONUS     = 12.0
LIFE_HEALTH_BONUS        = 10.0   # a health note in the file changes the clock
LIFE_CEILING             = 90.0

OBJECTIVE_CONFLICT       = 30.0   # two sources of truth; informs, never leads

STALE_PER_PCT            = 0.95   # per % of wealth carried at a stale mark
STALE_COLLATERAL_BONUS   = 15.0   # the stale mark also secures a facility
STALE_MIN_SHARE          = 3.0
STALE_CEILING            = 75.0

TAX_LOSS_SCALE           = 900.0  # (losses / wealth) x this
TAX_CEILING              = 80.0
TAX_NO_CGT               = 8.0    # domicile levies none: a non-recommendation


def _rung(value, rungs, mode):
    for thr, pts, label in rungs:
        if (value >= thr) if mode == "above" else (value <= thr):
            return pts, label
    return rungs[-1][1], rungs[-1][2]


class Sev:
    """A severity that remembers how it was built."""

    def __init__(self, driver, label, points):
        self.driver = driver
        self.value = float(points)
        self.ceiling = None
        self.capped = False
        self.steps = [{"label": label, "op": "", "value": round(float(points), 1)}]

    @classmethod
    def of(cls, driver, label, points):
        return cls(driver, label, points)

    @classmethod
    def ladder(cls, driver, value, rungs, mode="below"):
        """Threshold functions, which most of the modules use. `rungs` are
        ordered so the first one that matches wins, with a catch-all last."""
        pts, label = _rung(value, rungs, mode)
        return cls(driver, label, pts)

    def times(self, label, factor):
        if factor == 1.0:
            return self
        self.value *= factor
        self.steps.append({"label": label, "op": "x%g" % factor,
                           "value": round(self.value, 1)})
        return self

    def plus(self, label, points):
        if not points:
            return self
        self.value += points
        self.steps.append({"label": label, "op": "%+g" % points,
                           "value": round(self.value, 1)})
        return self

    def floor(self, label, points):
        if self.value >= points:
            return self
        self.value = float(points)
        self.steps.append({"label": label, "op": "at least %g" % points,
                           "value": round(self.value, 1)})
        return self

    def cap(self, ceiling):
        self.ceiling = float(ceiling)
        if self.value > ceiling:
            self.capped = True
            self.value = float(ceiling)
            self.steps.append({"label": "ceiling for this rule", "op": "cap %g" % ceiling,
                               "value": round(self.value, 1)})
        return self

    def basis(self):
        return {"driver": self.driver, "steps": self.steps, "ceiling": self.ceiling,
                "capped": self.capped, "result": round(self.value, 1)}


# What the workbench shows when the RM asks "where does this number come from".
# Derived from the constants above so the two can never drift apart.
CALIBRATION = [
    {"dimension": "mandate", "rule": "Asset-class band breach",
     "formula": "gap outside the band (pp) x %g, then the intent multiplier" % MANDATE_BAND_PER_PP,
     "ceiling": MANDATE_BAND_CEILING,
     "terms": [["per pp outside the band", MANDATE_BAND_PER_PP],
               ["discretionary mandate", DISCRETIONARY_X],
               ["client-directed, on file", DIRECTED_X],
               ["waived in writing", WAIVED_X]]},
    {"dimension": "mandate", "rule": "Single-position limit",
     "formula": "points over the cap (pp) x %g" % LIMIT_PER_PP,
     "ceiling": LIMIT_CEILING,
     "terms": [["per pp over the cap", LIMIT_PER_PP]]},
    {"dimension": "mandate", "rule": "Binding exclusion held",
     "formula": "flat: the instrument is either on the exclusion list or it is not",
     "ceiling": EXCLUSION_DISCRETIONARY,
     "terms": [["discretionary mandate", EXCLUSION_DISCRETIONARY],
               ["advisory mandate", EXCLUSION_ADVISORY]]},
    {"dimension": "collateral", "rule": "Headroom to the margin trigger",
     "formula": "step function on headroom in pp; a breach anywhere in the period floors it at %g"
                % COLLATERAL_BREACH_FLOOR,
     "ceiling": COLLATERAL_RUNGS[0][1],
     "terms": [[r[2], r[1]] for r in COLLATERAL_RUNGS]
              + [["breached at any snapshot", COLLATERAL_BREACH_FLOOR],
                 ["not reported below", COLLATERAL_REPORT_AT]]},
    {"dimension": "funding", "rule": "Twelve-month funding cover",
     "formula": "step function on cover = daily-liquid / need; %g if funding it trips a trigger"
                % FUNDING_BLOCKED,
     "ceiling": FUNDING_BLOCKED,
     "terms": [["funding it trips a margin call", FUNDING_BLOCKED]]
              + [[r[2], r[1]] for r in FUNDING_RUNGS]
              + [["not reported below", FUNDING_REPORT_AT]]},
    {"dimension": "purpose_fit", "rule": "Maturities beyond the horizon",
     "formula": "sleeve %% of wealth x %g + years of overshoot x %g" % (FIT_PER_PCT,
                                                                       FIT_PER_YEAR_BEYOND),
     "ceiling": FIT_CEILING,
     "terms": [["per % of wealth beyond the horizon", FIT_PER_PCT],
               ["per year of overshoot", FIT_PER_YEAR_BEYOND],
               ["a perpetual counts as this many years", FIT_PERPETUAL_YEARS],
               ["fires above this sleeve, underwater only", FIT_MIN_SLEEVE]]},
    {"dimension": "concentration", "rule": "Look-through single-name share",
     "formula": "step function on share of total wealth, aggregated through wrappers",
     "ceiling": CON_CEILING,
     "terms": [[r[2], r[1]] for r in CON_RUNGS]
              + [["repeats the source of wealth", CON_SAME_BET_BONUS],
                 ["not reported below", CON_REPORT_AT]]},
    {"dimension": "life_event", "rule": "Dated obligation against wealth",
     "formula": "obligation as %% of wealth x %g, plus certainty and health" % LIFE_PER_PCT,
     "ceiling": LIFE_CEILING,
     "terms": [["per % of wealth", LIFE_PER_PCT],
               ["recorded as Confirmed", LIFE_CONFIRMED_BONUS],
               ["a health note is on file", LIFE_HEALTH_BONUS]]},
    {"dimension": "life_event", "rule": "Objective contradicts the cash-needs row",
     "formula": "flat — it informs every other number for this client, but never leads",
     "ceiling": OBJECTIVE_CONFLICT,
     "terms": [["flat", OBJECTIVE_CONFLICT]]},
    {"dimension": "tax", "rule": "Loss harvesting",
     "formula": "losses / wealth x %g, gated on tax domicile" % TAX_LOSS_SCALE,
     "ceiling": TAX_CEILING,
     "terms": [["losses over wealth, scaled", TAX_LOSS_SCALE],
               ["domicile levies no CGT", TAX_NO_CGT]]},
    {"dimension": "data_quality", "rule": "Stale mark",
     "formula": "share of wealth at the stale mark x %g" % STALE_PER_PCT,
     "ceiling": STALE_CEILING,
     "terms": [["per % of wealth", STALE_PER_PCT],
               ["the mark also secures a facility", STALE_COLLATERAL_BONUS],
               ["fires above this share", STALE_MIN_SHARE]]},
]
