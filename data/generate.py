"""
Generates the synthetic book in data/.

    python3 data/generate.py        # rewrites every file in data/, deterministically

Everything in the book is invented: the bank (Halden Rowe), its relationship
manager, the twenty clients, every instrument and issuer, every price, and the
market events of the year it covers. Nothing here describes a real person, a
real company or a real market.

The book is written as stories first and numbers second. Each client is a few
positions at a stated weight and a stated gain or loss *today*; this script
works out the quantities, a price for every instrument at every snapshot, cost
bases struck at the exchange rate of the day they were bought, lending values,
loan-to-value on every facility, income, fees and cash movements, so that every
file agrees with every other. The stories are planted so that each of the
engine's rules has something real to find, and a few traps a careful engine has
to get right — they are listed at the end of docs/DATA_DICTIONARY.md.

Standard library only, like the engine.
"""
import csv
import json
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
RNG = random.Random(20260930)

# ── the calendar ──────────────────────────────────────────────────────────
DATES = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
TODAY = DATES[-1]
LABELS = ["Q3 2025 baseline", "Year-end 2025",
          "Q1 2026, after the Hong Kong developer default", "Half-year 2026", "Current"]

RM = {"rm_id": "RM-SG-021", "rm_name": "Clara Teo",
      "rm_desk": "Asia desk - Singapore and Hong Kong booking centres"}

# ── currencies: market convention per pair, value at each snapshot ────────
# (series id, quoted as USD per unit?) — EURUSD is USD per EUR, USDSGD is SGD per USD
FX = {
    "SGD": ("USDSGD", False, [1.290, 1.285, 1.310, 1.300, 1.280]),
    "HKD": ("USDHKD", False, [7.780, 7.790, 7.830, 7.820, 7.800]),
    "EUR": ("EURUSD", True, [1.170, 1.160, 1.120, 1.140, 1.160]),
    "GBP": ("GBPUSD", True, [1.340, 1.330, 1.300, 1.320, 1.340]),
    "CHF": ("USDCHF", False, [0.800, 0.810, 0.830, 0.820, 0.800]),
    "JPY": ("USDJPY", False, [148.0, 152.0, 147.0, 142.0, 136.0]),
    "CNH": ("USDCNH", False, [7.120, 7.200, 7.280, 7.220, 7.160]),
    "THB": ("USDTHB", False, [32.40, 33.00, 34.20, 33.60, 33.10]),
    "INR": ("USDINR", False, [88.00, 88.90, 89.60, 90.10, 89.40]),
    "KRW": ("USDKRW", False, [1390.0, 1420.0, 1460.0, 1410.0, 1370.0]),
    "AED": ("USDAED", False, [3.6725] * 5),
    "MYR": ("USDMYR", False, [4.220, 4.250, 4.310, 4.280, 4.200]),
    "AUD": ("AUDUSD", True, [0.660, 0.650, 0.630, 0.650, 0.670]),
}
FX_NAMES = {"SGD": "Singapore dollar", "HKD": "Hong Kong dollar", "EUR": "Euro",
            "GBP": "Pound sterling", "CHF": "Swiss franc", "JPY": "Japanese yen",
            "CNH": "Offshore renminbi", "THB": "Thai baht", "INR": "Indian rupee",
            "KRW": "Korean won", "AED": "UAE dirham", "MYR": "Malaysian ringgit",
            "AUD": "Australian dollar"}


def usd_per(ccy, k):
    """USD for one unit of `ccy` at snapshot k."""
    if ccy == "USD":
        return 1.0
    _, per_unit, vals = FX[ccy]
    return vals[k] if per_unit else 1.0 / vals[k]


def convert(amount, frm, to, k):
    return amount * usd_per(frm, k) / usd_per(to, k)


# ── the year, as factor returns between snapshots (%) ─────────────────────
# Q4 2025, Q1 2026, Q2 2026, Q3 2026. One line per theme in the invented market.
FACTORS = {
    "flat":       [0.0, 0.0, 0.0, 0.0],
    "mmf":        [1.0, 0.9, 0.9, 0.9],
    "dm_eq":      [4.0, -3.5, 5.0, 2.5],
    "us_tech":    [2.0, -6.0, 7.0, 4.0],
    "semis":      [-9.0, -12.0, 10.0, 6.0],
    "asia_eq":    [1.5, -6.0, 4.0, 3.0],
    "china_eq":   [3.0, -9.0, 2.0, 5.0],
    "japan_eq":   [3.0, -2.0, 4.0, -1.0],
    "europe_eq":  [2.5, -3.0, 3.5, 1.5],
    "hk_prop":    [-4.0, -22.0, 3.0, 9.0],
    "hk_reit":    [-2.0, -14.0, 2.0, 5.0],
    "fin_asia":   [1.0, -8.0, 3.0, 3.0],
    "ev_battery": [5.0, -10.0, 12.0, 3.0],
    "healthcare": [2.0, 1.0, -3.0, 4.0],
    "industrial": [2.0, -4.0, 3.0, 2.0],
    "logistics":  [1.0, -6.0, -4.0, 2.0],
    "coal":       [2.0, 6.0, -3.0, -8.0],
    "palm":       [3.0, -1.0, 2.0, -2.0],
    "defence":    [3.0, 4.0, 2.0, 1.0],
    "energy":     [1.0, -2.0, -4.0, -12.0],
    "commodity":  [1.0, 0.5, -1.0, -4.0],
    "gold":       [6.0, 4.0, 5.0, 2.0],
    "ust_long":   [1.0, -1.0, -5.5, 3.5],
    "ust_mid":    [0.8, -0.3, -1.8, 1.6],
    "tips":       [0.7, 0.2, -1.2, 1.4],
    "jgb_long":   [-5.0, -3.0, -2.5, -3.0],
    "jgb_mid":    [-1.5, -1.0, -0.8, -1.0],
    "sgs":        [0.6, -0.4, -1.0, 1.2],
    "bund":       [0.5, -0.8, -1.2, 1.0],
    "ig":         [0.8, -1.2, -1.5, 1.8],
    "ig_eur":     [0.6, -1.0, -1.0, 1.4],
    "hy":         [1.0, -2.5, 0.5, 1.5],
    "emd":        [0.5, -2.0, 0.5, 1.5],
    "short_dur":  [0.7, 0.4, 0.5, 0.7],
    "perp_bank":  [0.5, -3.0, -1.0, 1.5],
    "perp_prop":  [-3.0, -25.0, 4.0, 6.0],
    "infra_debt": [0.6, -1.5, -2.0, 1.5],
    "hedge":      [1.0, -1.0, 2.0, 1.0],
    "hedge_asia": [1.5, -3.0, 2.5, 1.5],
    "pe":         [2.0, 1.0, 1.5, 1.0],
    "pcredit":    [1.5, -4.0, -1.0, 0.5],
    "private_re": [0.0, -2.0, -1.0, 0.0],
    "structured": [0.5, -2.0, 1.0, 1.0],
}

# How much a price wobbles around its theme each quarter, by kind of instrument.
NOISE = {"stock": 2.0, "fund": 0.5, "bond": 0.25, "cash": 0.0, "sp": 1.0, "alt": 0.3}


# ── the instrument universe ───────────────────────────────────────────────
INSTRUMENTS = []


def inst(iid, name, cls, sub, sector, region, ccy, tier, factor, price, adv,
         beta=1.0, kind="fund", income=0.0, under="", excl="N", conc="N", stale=None):
    """price is the price today; history is walked back from it."""
    INSTRUMENTS.append(dict(
        instrument_id=iid, instrument_name=name, asset_class=cls, sub_asset_class=sub,
        sector=sector, region=region, currency=ccy, liquidity_tier=tier,
        underlying_reference=under, sustainability_excluded=excl,
        concentration_limit_applies=conc, _factor=factor, _beta=beta, _kind=kind,
        _price=price, _adv=adv, _income=income, _stale=stale))


C, FI, EQ, AL, CM, SP = ("Cash and Equivalents", "Fixed Income", "Equity",
                         "Alternatives", "Commodities", "Structured Products")

# cash and liquidity
inst("INS-CA-001", "USD Call Deposit", C, "Deposit", "Cash", "Global", "USD", "Daily", "flat", 1.0, 95, kind="cash", income=3.9)
inst("INS-CA-002", "SGD Call Deposit", C, "Deposit", "Cash", "Singapore", "SGD", "Daily", "flat", 1.0, 95, kind="cash", income=1.9)
inst("INS-CA-003", "HKD Call Deposit", C, "Deposit", "Cash", "Hong Kong", "HKD", "Daily", "flat", 1.0, 95, kind="cash", income=3.2)
inst("INS-CA-004", "EUR Call Deposit", C, "Deposit", "Cash", "Europe", "EUR", "Daily", "flat", 1.0, 95, kind="cash", income=1.8)
inst("INS-CA-005", "JPY Call Deposit", C, "Deposit", "Cash", "Japan", "JPY", "Daily", "flat", 1.0, 95, kind="cash", income=0.4)
inst("INS-CA-006", "CHF Call Deposit", C, "Deposit", "Cash", "Europe", "CHF", "Daily", "flat", 1.0, 95, kind="cash", income=0.2)
inst("INS-CA-007", "USD Liquidity Fund", C, "Money Market", "Cash", "Global", "USD", "Daily", "mmf", 104.30, 90)
inst("INS-CA-008", "SGD Liquidity Fund", C, "Money Market", "Cash", "Singapore", "SGD", "Daily", "mmf", 12.84, 90)

# government bonds — the year is in the name, which is how the engine finds it
inst("INS-FI-001", "US Treasury 4.25% due 2030", FI, "Government Bond", "Sovereign", "North America", "USD", "Daily", "ust_mid", 100.6, 90, kind="bond", income=4.25)
inst("INS-FI-002", "US Treasury 3.875% due 2049", FI, "Government Bond", "Sovereign", "North America", "USD", "Daily", "ust_long", 84.9, 90, beta=1.0, kind="bond", income=3.875)
inst("INS-FI-003", "Japan Government Bond 1.4% due 2044", FI, "Government Bond", "Sovereign", "Japan", "JPY", "Daily", "jgb_long", 78.4, 90, kind="bond", income=1.4)
inst("INS-FI-004", "Japan Government Bond 0.6% due 2033", FI, "Government Bond", "Sovereign", "Japan", "JPY", "Daily", "jgb_mid", 91.7, 90, kind="bond", income=0.6)
inst("INS-FI-005", "Singapore Government Securities 3.0% due 2032", FI, "Government Bond", "Sovereign", "Singapore", "SGD", "Daily", "sgs", 101.8, 90, kind="bond", income=3.0)
inst("INS-FI-006", "German Bund 2.5% due 2035", FI, "Government Bond", "Sovereign", "Europe", "EUR", "Daily", "bund", 97.2, 90, kind="bond", income=2.5)
inst("INS-FI-007", "US Treasury Inflation-Protected 1.75% due 2034", FI, "Inflation Linked", "Sovereign", "North America", "USD", "Daily", "tips", 98.6, 85, kind="bond", income=1.75)
# credit
inst("INS-FI-010", "Global Investment Grade Credit Fund", FI, "Investment Grade Credit", "Corporate", "Global", "USD", "Daily", "ig", 108.4, 80, income=4.6)
inst("INS-FI-011", "Asia Investment Grade Credit Fund", FI, "Investment Grade Credit", "Corporate", "Asia", "USD", "Daily", "ig", 96.2, 80, income=4.9)
inst("INS-FI-012", "Euro Investment Grade Corporate Fund", FI, "Investment Grade Credit", "Corporate", "Europe", "EUR", "Daily", "ig_eur", 52.7, 80, income=3.4)
inst("INS-FI-013", "Global High Yield Credit Fund", FI, "High Yield Credit", "Corporate", "Global", "USD", "Weekly", "hy", 88.3, 60, income=7.1)
inst("INS-FI-014", "Emerging Market Debt Fund", FI, "Emerging Market Debt", "Sovereign", "Emerging Markets", "USD", "Weekly", "emd", 74.6, 60, income=6.4)
inst("INS-FI-015", "Short Duration Bond Fund (SGD)", FI, "Short Duration", "Corporate", "Singapore", "SGD", "Daily", "short_dur", 10.52, 85, income=3.1)
inst("INS-FI-016", "Asia Infrastructure Finance 5.1% due 2046", FI, "Investment Grade Credit", "Infrastructure", "Asia", "USD", "Daily", "ig", 87.8, 75, beta=1.6, kind="bond", income=5.1, conc="Y")
inst("INS-FI-017", "Straits Commercial Bank 5.0% Perpetual", FI, "Subordinated Perpetual", "Financials", "Singapore", "USD", "Daily", "perp_bank", 96.4, 60, kind="bond", income=5.0, conc="Y")
inst("INS-FI-018", "Harbourline Property 6.25% Perpetual", FI, "Subordinated Perpetual", "Real Estate", "Hong Kong", "USD", "Daily", "perp_prop", 61.5, 40, kind="bond", income=6.25, conc="Y")

# equity funds
inst("INS-EQ-001", "World Developed Equity Index Fund", EQ, "Developed Market Equity", "Diversified", "Global", "USD", "Daily", "dm_eq", 241.7, 70, income=1.6)
inst("INS-EQ-002", "US Large Cap Equity Fund", EQ, "Developed Market Equity", "Diversified", "North America", "USD", "Daily", "dm_eq", 412.3, 70, beta=1.1, income=1.3)
inst("INS-EQ-003", "US Technology Leaders Fund", EQ, "Developed Market Equity", "Information Technology", "North America", "USD", "Daily", "us_tech", 188.6, 65, income=0.5)
inst("INS-EQ-004", "Asia ex-Japan Equity Fund", EQ, "Emerging Market Equity", "Diversified", "Asia ex-Japan", "USD", "Daily", "asia_eq", 102.4, 60, income=2.1)
inst("INS-EQ-005", "Japan Equity Fund", EQ, "Developed Market Equity", "Diversified", "Japan", "JPY", "Daily", "japan_eq", 3215.0, 65, income=2.0)
inst("INS-EQ-006", "Europe Equity Income Fund", EQ, "Developed Market Equity", "Diversified", "Europe", "EUR", "Daily", "europe_eq", 61.3, 65, income=3.4)
inst("INS-EQ-007", "China A-Share Growth Fund", EQ, "Emerging Market Equity", "Diversified", "Greater China", "CNH", "Daily", "china_eq", 8.92, 50, income=1.2)
inst("INS-EQ-008", "Global Semiconductor Equity Fund", EQ, "Developed Market Equity", "Information Technology", "Global", "USD", "Daily", "semis", 57.8, 60, income=0.4)
inst("INS-EQ-009", "Global Renewable Infrastructure Fund", EQ, "Developed Market Equity", "Utilities", "Global", "USD", "Daily", "dm_eq", 23.6, 60, beta=0.6, income=3.0)
inst("INS-EQ-010", "Global Energy Producers Fund", EQ, "Developed Market Equity", "Energy", "Global", "USD", "Daily", "energy", 44.1, 60, income=4.2, excl="Y")
inst("INS-EQ-011", "Global Defence Equity Fund", EQ, "Developed Market Equity", "Industrials", "Global", "USD", "Daily", "defence", 31.9, 60, income=1.4, excl="Y")
inst("INS-EQ-012", "Asia Pacific REIT Fund", EQ, "Real Estate Securities", "Real Estate", "Asia Pacific", "SGD", "Daily", "hk_reit", 1.072, 50, beta=0.6, income=5.6)
inst("INS-EQ-013", "Global Healthcare Equity Fund", EQ, "Developed Market Equity", "Health Care", "Global", "USD", "Daily", "healthcare", 64.5, 65, income=1.2)
# single stocks
inst("INS-ST-001", "Harbourline Property Holdings Ltd", EQ, "Single Stock", "Real Estate", "Hong Kong", "HKD", "Daily", "hk_prop", 11.86, 40, beta=1.2, kind="stock", income=4.8, conc="Y")
inst("INS-ST-002", "Straits Commercial Bank Ltd", EQ, "Single Stock", "Financials", "Singapore", "SGD", "Daily", "fin_asia", 21.40, 50, beta=0.8, kind="stock", income=5.2, conc="Y")
inst("INS-ST-003", "Lindenhof Antriebstechnik AG", EQ, "Single Stock", "Industrials", "Europe", "EUR", "Daily", "industrial", 74.20, 50, kind="stock", income=2.8, conc="Y")
inst("INS-ST-004", "Veltrion Semiconductor Inc", EQ, "Single Stock", "Information Technology", "North America", "USD", "Daily", "semis", 142.30, 50, beta=1.3, kind="stock", income=0.6, conc="Y")
inst("INS-ST-005", "Qinghe Battery Technology Co Ltd", EQ, "Single Stock", "Industrials", "Greater China", "HKD", "Daily", "ev_battery", 38.65, 40, beta=1.2, kind="stock", income=1.1, conc="Y")
inst("INS-ST-006", "Kitaura Precision Industries KK", EQ, "Single Stock", "Industrials", "Japan", "JPY", "Daily", "japan_eq", 4870.0, 50, beta=1.2, kind="stock", income=2.2, conc="Y")
inst("INS-ST-007", "Sahraa Logistics PJSC", EQ, "Single Stock", "Industrials", "Middle East", "AED", "Daily", "logistics", 5.62, 40, kind="stock", income=3.6, conc="Y")
inst("INS-ST-008", "Barrow Ridge Thermal Coal Ltd", EQ, "Single Stock", "Energy", "Asia Pacific", "AUD", "Daily", "coal", 4.18, 40, kind="stock", income=8.5, excl="Y", conc="Y")
inst("INS-ST-009", "Rimba Lestari Plantations Bhd", EQ, "Single Stock", "Consumer Staples", "Southeast Asia", "MYR", "Daily", "palm", 6.34, 40, kind="stock", income=3.9, excl="Y", conc="Y")
inst("INS-ST-010", "Corlane Medical Systems Inc", EQ, "Single Stock", "Health Care", "North America", "USD", "Daily", "healthcare", 218.40, 50, beta=1.3, kind="stock", income=0.9, conc="Y")

# alternatives
inst("INS-AL-001", "Global Macro Hedge Fund", AL, "Hedge Fund", "Macro", "Global", "USD", "Monthly", "hedge", 1384.0, 30, kind="alt")
inst("INS-AL-002", "Asia Equity Long Short Fund", AL, "Hedge Fund", "Equity Long Short", "Asia", "USD", "Monthly", "hedge_asia", 1127.0, 30, kind="alt")
inst("INS-AL-003", "Northfield Private Equity Partners IX", AL, "Private Equity", "Multi", "Global", "USD", "Illiquid", "pe", 1.236, 0, kind="alt", conc="Y")
inst("INS-AL-004", "Serai Private Credit Fund II", AL, "Private Credit", "Corporate", "Asia", "USD", "Quarterly Gate", "pcredit", 0.962, 0, kind="alt", income=8.0)
inst("INS-AL-005", "Pan-Asia Logistics Real Estate Fund", AL, "Private Real Estate", "Real Estate", "Asia Pacific", "USD", "Illiquid", "private_re", 1.041, 0, kind="alt", income=4.0)
inst("INS-AL-006", "Infrastructure Debt Fund III", AL, "Private Credit", "Infrastructure", "Global", "USD", "Illiquid", "infra_debt", 0.988, 0, kind="alt", income=6.5)
inst("INS-AL-007", "Unlisted Holding - Lumora Analytics Pte Ltd", AL, "Private Equity", "Information Technology", "Singapore", "USD", "Illiquid", "flat", 41.20, 20, kind="alt", conc="Y", stale="2025-06-30",
     under="Series C preference shares, last priced round Jun-2025")

# commodities
inst("INS-CM-001", "Gold Bullion ETF", CM, "Precious Metals", "Gold", "Global", "USD", "Daily", "gold", 372.4, 70)
inst("INS-CM-002", "Allocated Gold Account (Singapore)", CM, "Precious Metals", "Gold", "Singapore", "USD", "Daily", "gold", 3986.0, 70, under="Gold spot, allocated bars, Singapore vault")
inst("INS-CM-003", "Diversified Commodity Index Fund", CM, "Diversified Commodities", "Multi", "Global", "USD", "Daily", "commodity", 18.7, 50, excl="Y")

# structured products — the wrapper's asset class says what it is; the reference says what you hold
inst("INS-SP-001", "Accumulator ref. Harbourline Property Holdings, 12M", SP, "Accumulator", "Real Estate", "Hong Kong", "HKD", "Illiquid", "hk_prop", 71.4, 0, beta=1.6, kind="sp", conc="Y",
     under="Single underlying: Harbourline Property Holdings Ltd, daily accumulation at strike HKD 11.40, knock-out HKD 13.10, double-up below strike")
inst("INS-SP-002", "Equity Linked Note ref. Qinghe Battery Technology, 10.5% p.a., 6M", SP, "Yield Enhancement", "Industrials", "Greater China", "USD", "Illiquid", "ev_battery", 93.1, 0, beta=0.6, kind="sp", conc="Y",
     under="Single underlying: Qinghe Battery Technology Co Ltd")
inst("INS-SP-003", "Fixed Coupon Note ref. Basket Q, 9.0% p.a., 12M", SP, "Yield Enhancement", "Multi", "Asia", "USD", "Illiquid", "semis", 88.4, 0, beta=0.5, kind="sp", conc="Y",
     under="Worst-of basket: Veltrion Semiconductor Inc / Qinghe Battery Technology Co Ltd / Straits Commercial Bank Ltd")
inst("INS-SP-004", "Capital Protected Note ref. Gold, 24M", SP, "Capital Protected", "Gold", "Global", "USD", "Illiquid", "gold", 109.6, 0, beta=0.5, kind="sp", conc="Y",
     under="Underlying: Gold spot, 100% capital protection at maturity, 65% participation")
inst("INS-SP-005", "Autocallable ref. Japan Exporters Basket, 7.2% p.a.", SP, "Yield Enhancement", "Multi", "Japan", "JPY", "Illiquid", "japan_eq", 96.3, 0, beta=0.6, kind="sp", conc="Y",
     under="Worst-of basket: three Japanese exporters, autocall observation quarterly")

I = {i["instrument_id"]: i for i in INSTRUMENTS}


def price_path(i):
    """Five prices, walked back from today's through the instrument's theme."""
    if i["_stale"] or i["_kind"] == "cash":
        return [i["_price"]] * 5
    f = FACTORS[i["_factor"]]
    sigma = NOISE[i["_kind"]]
    p = [0.0] * 5
    p[4] = i["_price"]
    for k in range(3, -1, -1):
        r = (i["_beta"] * f[k] + RNG.gauss(0, sigma)) / 100.0
        p[k] = p[k + 1] / (1 + r)
    digits = 4 if i["_price"] < 5 else 2
    return [round(x, digits) for x in p]


for _i in INSTRUMENTS:
    _i["_path"] = price_path(_i)


# ── mandates ──────────────────────────────────────────────────────────────
ORDER = [C, FI, EQ, AL, CM, SP]
MANDATES = {
    # code: (name, single-position cap, notes, {class: (min, target, max)})
    "CONS": ("Conservative", 10.0, "Capital preservation first. No single position above 10%.",
             {C: (5, 10, 20), FI: (50, 65, 80), EQ: (10, 20, 30), AL: (0, 5, 10), CM: (0, 0, 5), SP: (0, 0, 5)}),
    "INC": ("Income", 10.0, "Income from a diversified bond core. No single position above 10%.",
            {C: (2, 8, 15), FI: (45, 60, 75), EQ: (15, 25, 35), AL: (0, 5, 10), CM: (0, 2, 5), SP: (0, 0, 10)}),
    "BAL": ("Balanced", 12.0, "Balanced growth and income.",
            {C: (2, 5, 15), FI: (25, 35, 50), EQ: (30, 45, 60), AL: (0, 10, 15), CM: (0, 5, 10), SP: (0, 0, 10)}),
    "SUSBAL": ("Sustainable Balanced", 12.0,
               "Balanced allocation with binding exclusions: thermal coal mining, oil and gas "
               "exploration and production, controversial weapons, and palm oil producers without "
               "certified supply chains.",
               {C: (2, 5, 15), FI: (25, 35, 50), EQ: (30, 45, 60), AL: (0, 10, 15), CM: (0, 0, 5), SP: (0, 0, 10)}),
    "BALG": ("Balanced Growth", 15.0, "Growth tilt with a meaningful bond buffer.",
             {C: (0, 5, 10), FI: (15, 25, 40), EQ: (40, 55, 70), AL: (0, 10, 20), CM: (0, 5, 10), SP: (0, 0, 10)}),
    "GROW": ("Growth", 15.0, "Long-horizon equity growth.",
             {C: (0, 3, 10), FI: (5, 15, 30), EQ: (55, 70, 85), AL: (0, 10, 20), CM: (0, 2, 10), SP: (0, 0, 15)}),
    "ALTS": ("Alternatives Sleeve", 25.0, "Private markets and hedge funds. No single fund above 25%.",
             {C: (0, 5, 20), FI: (0, 0, 30), EQ: (0, 0, 20), AL: (60, 90, 100), CM: (0, 0, 10), SP: (0, 0, 10)}),
}


# ── the clients ───────────────────────────────────────────────────────────
CLIENTS, PORTFOLIOS, FACILITIES, COMMITMENTS, NEEDS, SPECIAL_TX = [], [], [], [], [], []


def client(cid, name, age, gender, nat, res, dom, centre, base, life, sow, risk, score,
           horizon, liq, objectives, since, kyc, lang, pep="No"):
    CLIENTS.append(dict(client_id=cid, client_name=name, age=age, gender=gender,
                        nationality=nat, country_of_residence=res, tax_domicile=dom,
                        booking_centre=centre, base_currency=base, life_stage=life,
                        source_of_wealth=sow, risk_profile=risk, risk_tolerance_score=score,
                        investment_horizon_years=horizon, liquidity_needs=liq,
                        objectives=objectives, client_since=since, kyc_review_due=kyc,
                        pep_status=pep, reporting_language=lang))


def portfolio(pid, cid, name, code, model, base, inception, usd, holdings):
    """holdings: (instrument, weight % today, unrealised % today, acquired, options)."""
    PORTFOLIOS.append(dict(portfolio_id=pid, client_id=cid, portfolio_name=name,
                           mandate_code=code, service_model=model, base_currency=base,
                           inception_date=inception, _usd=usd, _holdings=holdings))


def h(iid, weight, pnl, acquired, **opt):
    return (iid, weight, pnl, acquired, opt)


def need(nid, cid, what, ccy, amount, due_from, due_to, recurrence, certainty):
    NEEDS.append(dict(need_id=nid, client_id=cid, description=what, currency=ccy,
                      amount=amount, due_from=due_from, due_to=due_to,
                      recurrence=recurrence, certainty=certainty))


def tx(day, pid, kind, ccy, amount, narrative, iid="", qty="", price=""):
    SPECIAL_TX.append(dict(trade_date=day, portfolio_id=pid, transaction_type=kind,
                           instrument_id=iid, quantity=qty, price_local=price,
                           currency=ccy, amount=amount, narrative=narrative))


# CL-0001 · a retired founder whose bond ladder outlives his plan
client("CL-0001", "Takeshi Morimoto", 68, "M", "Japan", "Singapore", "Japan", "Singapore", "JPY",
       "Retired", "Founder - precision machine tools manufacturer, sold in 2019",
       "Income", 3, 10, "Medium",
       "Draw about USD 0.5m a year for living costs in Singapore and Japan; keep the capital "
       "intact for two grandchildren's education trusts; avoid selling anything at a loss",
       "2019-11-04", "2027-03-31", "Japanese")
portfolio("PF-0001", "CL-0001", "Retirement Income Mandate", "INC", "Discretionary", "JPY", "2019-11-15", 31.4e6, [
    h("INS-FI-003", 22, -18.0, "2021-02-15"),
    h("INS-FI-004", 8, -6.5, "2021-02-15"),
    h("INS-FI-002", 12, -14.0, "2020-08-10"),
    h("INS-FI-017", 7, -4.5, "2022-05-20"),
    h("INS-FI-010", 9, 2.5, "2019-11-20"),
    h("INS-EQ-005", 14, 36.0, "2019-11-20"),
    h("INS-ST-006", 8, 64.0, "2014-06-01"),
    h("INS-EQ-001", 8, 41.0, "2019-11-20"),
    h("INS-CA-005", 6, 0.0, "2025-09-01"),
    h("INS-SP-005", 4, -2.5, "2025-06-12"),
    h("INS-CA-007", 2, 3.6, "2024-01-10"),
])
need("CN-001", "CL-0001", "Living costs, Singapore and Japan", "JPY", 60_000_000, "2026-01-31", "2036-01-31", "Annual", "Confirmed")
for d in ("2025-10-31", "2026-01-30", "2026-04-30", "2026-07-31"):
    tx(d, "PF-0001", "Withdrawal", "JPY", -15_000_000, "Quarterly living expense transfer to Singapore account.")

# CL-0002 · the Lombard loan, the land deposit and the family developer
client("CL-0002", "Raymond Wong Ka Lok", 57, "M", "Hong Kong SAR", "Hong Kong SAR", "Hong Kong SAR",
       "Hong Kong", "HKD", "Business owner - second generation",
       "Family property development group, Hong Kong", "Growth", 7, 15, "Medium",
       "Fund a land-bank deposit for the family company in early 2027; keep the Lombard line "
       "available for opportunities; stay invested in Hong Kong property",
       "2012-05-18", "2026-11-20", "Traditional Chinese")
portfolio("PF-0002", "CL-0002", "Advisory Growth Portfolio", "GROW", "Advisory", "HKD", "2012-06-01", 38.6e6, [
    h("INS-ST-001", 24, -28.0, "2018-03-12"),
    h("INS-SP-001", 8, -34.0, "2026-01-12", start=2),
    h("INS-FI-018", 6, -31.0, "2021-09-07"),
    h("INS-EQ-012", 5, -12.0, "2020-02-14"),
    h("INS-ST-002", 6, 18.0, "2019-07-02"),
    h("INS-EQ-004", 12, 9.0, "2017-04-21"),
    h("INS-EQ-003", 10, 47.0, "2019-03-08"),
    h("INS-EQ-001", 9, 38.0, "2016-10-11"),
    h("INS-FI-010", 7, 1.5, "2021-01-19"),
    h("INS-FI-013", 4, 4.0, "2022-11-03"),
    h("INS-CA-003", 3, 0.0, "2025-06-01"),
    h("INS-CM-001", 3, 41.0, "2023-02-27"),
    h("INS-EQ-008", 3, 22.0, "2023-08-15"),
])
FACILITIES.append(dict(facility_id="CF-0001", client_id="CL-0002", collateral_portfolio_id="PF-0002",
                       facility_type="Lombard Credit Facility", facility_ccy="HKD",
                       credit_limit=160_000_000, interest_rate_pct=5.85, margin_call_ltv_pct=70.0,
                       _drawn=[94_000_000, 94_000_000, 110_000_000, 110_000_000, 110_000_000],
                       _target_ltv_today=68.85))
need("CN-002", "CL-0002", "Land-bank deposit for the family company", "HKD", 80_000_000,
     "2027-02-15", "2027-02-15", "One-off", "Confirmed")
tx("2026-01-12", "PF-0002", "Structured Product Subscription", "HKD", "", "12-month accumulator on "
   "Harbourline Property Holdings. Strike HKD 11.40, knock-out HKD 13.10, double-up below strike.",
   iid="INS-SP-001")
tx("2026-01-12", "PF-0002", "Facility Drawdown", "HKD", None,
   "Drawdown on CF-0001 to settle the accumulator subscription.")

# CL-0003 · an inherited stake that broke a conservative mandate
client("CL-0003", "Elisabeth Brandt", 61, "F", "Germany", "Singapore", "Germany", "Singapore", "EUR",
       "Recently widowed - consolidating", "Inheritance - late husband's shareholding in a German "
       "drive-technology manufacturer", "Conservative", 3, 12, "Medium",
       "Simplify and de-risk what she inherited; secure a stable income; plan for German "
       "inheritance tax on the next transfer to her two children",
       "2024-05-06", "2026-08-15", "German")
portfolio("PF-0003", "CL-0003", "Conservative Mandate", "CONS", "Discretionary", "EUR", "2024-05-15", 24.2e6, [
    h("INS-ST-003", 17, 9.0, "2026-02-16", start=2),
    h("INS-EQ-006", 14, 6.0, "2024-05-20"),
    h("INS-EQ-001", 12, 11.0, "2024-05-20"),
    h("INS-EQ-002", 7, 13.0, "2026-02-16", start=2),
    h("INS-EQ-005", 4, 5.0, "2026-02-16", start=2),
    h("INS-FI-006", 12, -2.0, "2024-05-20"),
    h("INS-FI-012", 14, 1.0, "2024-05-20"),
    h("INS-FI-010", 6, 0.5, "2024-05-20"),
    h("INS-CA-004", 10, 0.0, "2024-05-20"),
    h("INS-CM-001", 4, 18.0, "2024-05-20"),
])
tx("2026-02-16", "PF-0003", "Transfer In", "EUR", 9_400_000,
   "Shares and cash transferred in from the late Mr Brandt's estate.")

# CL-0004 · a founder carried at a fifteen-month-old mark, which also secures his loan
client("CL-0004", "Arjun Mehta", 39, "M", "India", "Singapore", "Singapore", "Singapore", "USD",
       "Founder - pre-liquidity", "Founder - Lumora Analytics, enterprise AI software",
       "Growth", 8, 20, "High",
       "Bridge personal liquidity until a secondary sale or listing of Lumora shares; diversify "
       "after the event; set up a family trust", "2021-09-13", "2027-01-31", "English")
portfolio("PF-0004", "CL-0004", "Advisory Growth Portfolio", "GROW", "Advisory", "USD", "2021-10-01", 19.8e6, [
    h("INS-EQ-001", 30, 24.0, "2021-10-05"),
    h("INS-EQ-002", 22, 31.0, "2021-10-05"),
    h("INS-EQ-004", 14, 4.0, "2022-03-14"),
    h("INS-EQ-013", 8, 9.0, "2023-06-02"),
    h("INS-FI-010", 12, -1.0, "2021-10-05"),
    h("INS-AL-001", 8, 7.0, "2022-06-30"),
    h("INS-CA-001", 6, 0.0, "2025-01-15"),
])
portfolio("PF-0005", "CL-0004", "Founder Holdings Account", "CUSTODY", "Custody", "USD", "2021-09-20", 30.9e6, [
    h("INS-AL-007", 75, 312.0, "2021-09-20"),
    h("INS-EQ-008", 14, 18.0, "2023-11-08"),
    h("INS-EQ-003", 8, 26.0, "2023-11-08"),
    h("INS-CA-007", 3, 2.0, "2024-04-02"),
])
FACILITIES.append(dict(facility_id="CF-0002", client_id="CL-0004", collateral_portfolio_id="PF-0005",
                       facility_type="Lombard Credit Facility", facility_ccy="USD",
                       credit_limit=12_000_000, interest_rate_pct=6.40, margin_call_ltv_pct=72.0,
                       _drawn=[6_600_000] * 5, _target_ltv_today=68.4))
for d in ("2025-12-15", "2026-03-16", "2026-06-15", "2026-09-15"):
    tx(d, "PF-0005", "Valuation Update", "USD", 0.0, "Quarterly review of the Lumora holding. No new "
       "priced round; carrying value left at the Jun-2025 Series C price.", iid="INS-AL-007", price=41.20)

# CL-0005 · a values-based mandate that holds what it excludes
client("CL-0005", "Nurul Aisyah binti Hamzah", 52, "F", "Malaysia", "Singapore", "Singapore", "Singapore", "SGD",
       "Peak earning years", "Founder - halal food manufacturing group, Malaysia and Singapore",
       "Balanced", 5, 15, "Low",
       "Invest in line with her values: no thermal coal, no weapons, no uncertified palm oil; "
       "fund two children's university education abroad; endow a family foundation",
       "2016-02-29", "2027-02-28", "English")
portfolio("PF-0006", "CL-0005", "Sustainable Balanced Mandate", "SUSBAL", "Discretionary", "SGD", "2016-03-15", 21.3e6, [
    h("INS-EQ-001", 20, 44.0, "2016-03-20"),
    h("INS-EQ-004", 9, 6.0, "2018-07-11"),
    h("INS-EQ-009", 8, -4.0, "2021-05-04"),
    h("INS-EQ-013", 5, 12.0, "2022-08-19"),
    h("INS-EQ-010", 4, -9.0, "2025-11-10", start=1),
    h("INS-EQ-011", 3, 11.0, "2024-02-05"),
    h("INS-ST-009", 3, 62.0, "2011-01-01"),
    h("INS-FI-005", 12, 1.0, "2020-01-22"),
    h("INS-FI-011", 14, 0.5, "2019-04-30"),
    h("INS-FI-015", 10, 2.0, "2023-03-01"),
    h("INS-AL-002", 6, 9.0, "2021-11-10"),
    h("INS-CA-002", 6, 0.0, "2025-01-01"),
])
need("CN-003", "CL-0005", "University fees, two children (Australia)", "AUD", 210_000,
     "2027-02-01", "2031-02-01", "Annual", "Confirmed")
tx("2025-11-10", "PF-0006", "Buy", "USD", "", "Discretionary purchase by the portfolio manager: "
   "Global Energy Producers Fund, added for income.", iid="INS-EQ-010")

# CL-0006 · an entrepreneur whose portfolio repeats her business
client("CL-0006", "Chen Jia Hui", 45, "F", "China", "Hong Kong SAR", "China", "Hong Kong", "USD",
       "Entrepreneur - peak earning", "Co-founder - battery technology supplier to electric "
       "vehicle makers", "Growth", 8, 15, "Low",
       "Grow wealth outside mainland China; stay invested in the electric-vehicle supply chain "
       "she knows; buy a home in Hong Kong", "2020-07-07", "2027-05-31", "Simplified Chinese")
portfolio("PF-0007", "CL-0006", "Advisory Growth Portfolio", "GROW", "Advisory", "USD", "2020-07-20", 30.2e6, [
    h("INS-ST-005", 19, -17.0, "2021-11-18", qty=[0.78, 0.78, 0.78, 1, 1]),
    h("INS-SP-002", 6, -8.0, "2026-04-08", start=3),
    h("INS-SP-003", 4, -6.0, "2025-12-02", start=1),
    h("INS-EQ-002", 18, 27.0, "2020-07-24"),
    h("INS-EQ-001", 14, 22.0, "2020-07-24"),
    h("INS-EQ-007", 9, -21.0, "2021-02-10"),
    h("INS-EQ-003", 10, 35.0, "2022-01-18"),
    h("INS-FI-011", 10, -2.0, "2021-06-09"),
    h("INS-CA-001", 5, 0.0, "2025-01-01"),
    h("INS-CM-001", 5, 30.0, "2023-04-11"),
])
need("CN-004", "CL-0006", "Apartment purchase, Mid-Levels, Hong Kong", "HKD", 46_000_000,
     "2027-03-31", "2027-03-31", "One-off", "Likely")
tx("2026-05-06", "PF-0007", "Buy", "HKD", "", "Client-directed purchase of Qinghe Battery Technology "
   "shares after first-quarter results.", iid="INS-ST-005")

# CL-0007 · a waiver on file, a foundation and a health note
client("CL-0007", "Edward Ashworth", 73, "M", "United Kingdom", "Hong Kong SAR", "United Kingdom", "Hong Kong", "USD",
       "Retired - succession planning", "Former partner, commodities trading house",
       "Balanced", 5, 8, "Medium",
       "Endow a charitable foundation in 2027; keep gold as insurance; pass the remainder to "
       "three children in trust", "2006-10-02", "2027-04-30", "English")
portfolio("PF-0008", "CL-0007", "Balanced Mandate", "BAL", "Discretionary", "USD", "2006-10-15", 44.1e6, [
    h("INS-CM-002", 11, 58.0, "2019-05-06"),
    h("INS-CM-001", 6, 34.0, "2026-03-20", start=2),
    h("INS-EQ-001", 18, 63.0, "2008-11-20"),
    h("INS-EQ-002", 10, 71.0, "2010-03-02"),
    h("INS-EQ-006", 6, 12.0, "2015-07-14"),
    h("INS-EQ-004", 5, 3.0, "2018-01-29"),
    h("INS-FI-001", 14, -1.5, "2023-10-25"),
    h("INS-FI-010", 11, 0.5, "2019-09-09"),
    h("INS-FI-007", 7, 2.5, "2022-04-04"),
    h("INS-AL-001", 6, 15.0, "2017-02-21"),
    h("INS-CA-001", 6, 0.0, "2025-01-01"),
])
need("CN-005", "CL-0007", "Initial endowment of the Ashworth charitable foundation", "USD", 7_500_000,
     "2027-05-03", "2027-05-03", "One-off", "Confirmed")
tx("2026-03-20", "PF-0008", "Buy", "USD", "", "Client-instructed purchase of gold, taken above the "
   "mandate ceiling against advice. Suitability waiver signed.", iid="INS-CM-001")

# CL-0008 · a family office whose alternatives cannot fund their own calls
client("CL-0008", "Lim Heng Family Office", "", "", "Singapore", "Singapore", "Singapore", "Singapore", "USD",
       "Family office - third generation", "Family shipping and port logistics business, sold in 2018",
       "Balanced", 6, 20, "Medium",
       "Meet private markets capital calls without forced selling; preserve purchasing power "
       "across generations; keep a strategic alternatives programme", "2009-01-12", "2027-01-31", "English")
portfolio("PF-0009", "CL-0008", "Family Office Core Mandate", "BAL", "Discretionary", "USD", "2009-02-01", 41.0e6, [
    h("INS-EQ-001", 26, 52.0, "2012-05-14"),
    h("INS-EQ-004", 10, 8.0, "2016-09-12"),
    h("INS-EQ-002", 8, 44.0, "2014-01-06"),
    h("INS-FI-001", 10, -1.0, "2023-11-02"),
    h("INS-FI-010", 6, 1.0, "2019-04-15"),
    h("INS-FI-013", 12, 3.0, "2021-03-22"),
    h("INS-FI-014", 11, -6.0, "2021-03-22"),
    h("INS-AL-001", 8, 11.0, "2015-06-30"),
    h("INS-AL-002", 5, 6.0, "2019-10-31"),
    h("INS-CA-001", 4, 0.0, "2025-01-01"),
])
portfolio("PF-0010", "CL-0008", "Alternatives Sleeve", "ALTS", "Advisory", "USD", "2013-04-01", 36.0e6, [
    h("INS-AL-003", 33, 23.0, "2022-03-01"),
    h("INS-AL-004", 24, -5.0, "2023-01-16"),
    h("INS-AL-005", 15, 4.0, "2021-07-01"),
    h("INS-AL-001", 12, 9.0, "2018-02-28"),
    h("INS-AL-006", 11, -1.5, "2024-02-01"),
    h("INS-CA-007", 5, 2.0, "2024-01-01"),
])
COMMITMENTS.extend([
    dict(commitment_id="COM-001", client_id="CL-0008", portfolio_id="PF-0010",
         fund_name="Northfield Private Equity Partners IX", currency="USD", committed=26_000_000,
         called_to_date=15_500_000, uncalled=10_500_000, expected_call_window="2026 Q4 to 2028 Q2"),
    dict(commitment_id="COM-002", client_id="CL-0008", portfolio_id="PF-0010",
         fund_name="Infrastructure Debt Fund III", currency="USD", committed=10_000_000,
         called_to_date=6_000_000, uncalled=4_000_000, expected_call_window="2026 Q4 to 2027 Q3"),
    dict(commitment_id="COM-003", client_id="CL-0008", portfolio_id="PF-0010",
         fund_name="Pan-Asia Logistics Real Estate Fund", currency="USD", committed=8_000_000,
         called_to_date=4_500_000, uncalled=3_500_000, expected_call_window="2027 Q2 to 2028 Q4"),
])
need("CN-006", "CL-0008", "Annual distributions to family beneficiaries", "USD", 3_200_000,
     "2026-12-15", "2045-12-15", "Annual", "Confirmed")
tx("2026-02-20", "PF-0010", "Capital Call", "USD", -2_400_000, "Northfield Private Equity Partners IX "
   "capital call. USD 12.9m remains uncalled.")
tx("2026-05-18", "PF-0010", "Capital Call", "USD", -1_500_000, "Infrastructure Debt Fund III capital call.")
tx("2026-08-24", "PF-0010", "Capital Call", "USD", -2_400_000, "Northfield Private Equity Partners IX "
   "capital call. USD 10.5m remains uncalled.")
tx("2026-04-02", "PF-0010", "Redemption Request", "USD", 0.0, "Full redemption requested from Serai "
   "Private Credit Fund II. Manager applied the gate; request queued with no settlement date.",
   iid="INS-AL-004")

# CL-0009 · large losses in a domicile with no capital gains tax
client("CL-0009", "Fatima Al-Suwaidi", 50, "F", "United Arab Emirates", "United Arab Emirates",
       "United Arab Emirates", "Singapore", "USD", "Business owner",
       "Family real estate and hospitality group, Dubai", "Balanced", 5, 12, "Low",
       "Diversify away from Gulf real estate; keep income steady; consider a Singapore family "
       "office in 2028", "2018-03-05", "2027-03-31", "English")
portfolio("PF-0011", "CL-0009", "Advisory Balanced Portfolio", "BAL", "Advisory", "USD", "2018-03-20", 27.3e6, [
    h("INS-FI-002", 16, -17.0, "2021-01-12"),
    h("INS-FI-011", 7, -3.0, "2021-01-12"),
    h("INS-EQ-007", 9, -24.0, "2021-02-17"),
    h("INS-ST-007", 6, -27.0, "2022-04-04"),
    h("INS-EQ-012", 9, -19.0, "2021-08-30"),
    h("INS-EQ-001", 24, 39.0, "2018-03-22"),
    h("INS-EQ-002", 10, 46.0, "2018-03-22"),
    h("INS-AL-001", 8, 6.0, "2020-06-30"),
    h("INS-CM-001", 6, 37.0, "2022-10-14"),
    h("INS-CA-001", 5, 0.0, "2025-01-01"),
])

# CL-0010 · a house in Tuscany, and gold she asked for
client("CL-0010", "Giulia Ferraro", 47, "F", "Italy", "Singapore", "Italy", "Singapore", "EUR",
       "Executive - relocated to Asia", "Former chief financial officer, luxury goods group; vested "
       "equity awards", "Balanced Growth", 6, 15, "Medium",
       "Buy a family home in Tuscany in 2027; keep the portfolio growing; return to Italy by 2030",
       "2019-09-23", "2027-06-30", "Italian")
portfolio("PF-0012", "CL-0010", "Advisory Balanced Growth Portfolio", "BALG", "Advisory", "EUR", "2019-10-01", 19.1e6, [
    h("INS-EQ-001", 24, 33.0, "2019-10-08"),
    h("INS-EQ-006", 14, 9.0, "2019-10-08"),
    h("INS-EQ-002", 12, 29.0, "2020-04-15"),
    h("INS-EQ-004", 6, 1.0, "2021-03-09"),
    h("INS-FI-012", 14, -0.5, "2019-10-08"),
    h("INS-FI-006", 9, -1.5, "2022-09-05"),
    h("INS-CM-001", 9, 26.0, "2023-02-14", qty=[0.6, 0.6, 1, 1, 1]),
    h("INS-CM-003", 4, -6.0, "2022-01-10"),
    h("INS-AL-001", 4, 5.0, "2021-06-30"),
    h("INS-CA-004", 4, 0.0, "2025-01-01"),
])
need("CN-007", "CL-0010", "Purchase of a family home in Tuscany", "EUR", 2_850_000,
     "2027-04-30", "2027-04-30", "One-off", "Confirmed")
tx("2026-03-12", "PF-0012", "Buy", "USD", "", "Client-directed addition to the gold ETF, above the "
   "commodity limit. Instruction confirmed in writing.", iid="INS-CM-001")

# CL-0011 · a chip-equipment founder who still owns the chip cycle, and reads Korean
client("CL-0011", "Park Hyun-woo", 44, "M", "South Korea", "Singapore", "South Korea", "Singapore", "USD",
       "Founder - post-exit", "Founder - semiconductor equipment maker, sold to a strategic "
       "buyer in 2023", "Growth", 8, 20, "Low",
       "Rebuild a diversified portfolio after the sale; keep some exposure to the chip cycle he "
       "knows; fund a gift to his university", "2023-07-17", "2027-07-31", "Korean")
portfolio("PF-0013", "CL-0011", "Advisory Growth Portfolio", "GROW", "Advisory", "USD", "2023-08-01", 33.4e6, [
    h("INS-ST-004", 26, -16.0, "2023-08-07"),
    h("INS-SP-003", 5, -6.0, "2025-12-02", start=1),
    h("INS-EQ-008", 8, -9.0, "2024-06-10"),
    h("INS-EQ-001", 18, 21.0, "2023-08-07"),
    h("INS-EQ-002", 10, 19.0, "2023-08-07"),
    h("INS-EQ-004", 7, -2.0, "2023-08-07"),
    h("INS-FI-010", 12, -0.5, "2023-08-07"),
    h("INS-FI-001", 6, -1.0, "2023-10-30"),
    h("INS-AL-002", 4, 4.0, "2024-03-28"),
    h("INS-CA-001", 4, 0.0, "2025-01-01"),
])
need("CN-008", "CL-0011", "Endowed scholarship gift to his alma mater", "KRW", 3_000_000_000,
     "2027-06-30", "2027-06-30", "One-off", "Likely")

# CL-0012 · a retiree's income sleeve that matures after she needs it, and no tax to save
client("CL-0012", "Vivian Ho Wai Man", 66, "F", "Hong Kong SAR", "Hong Kong SAR", "Hong Kong SAR", "Hong Kong", "HKD",
       "Retired", "Former managing director, garment exports; proceeds from selling the business",
       "Conservative", 3, 8, "Medium",
       "Live on portfolio income; keep enough in cash for two grandchildren's school fees; avoid "
       "anything she cannot explain to her son", "2011-08-08", "2027-02-28", "Traditional Chinese")
portfolio("PF-0014", "CL-0012", "Income Mandate", "INC", "Discretionary", "HKD", "2011-08-20", 23.6e6, [
    h("INS-FI-002", 14, -15.0, "2021-03-15"),
    h("INS-FI-018", 7, -32.0, "2021-11-02"),
    h("INS-FI-017", 5, -3.0, "2022-06-14"),
    h("INS-FI-011", 15, -2.0, "2019-05-27"),
    h("INS-FI-005", 8, 0.5, "2022-01-10"),
    h("INS-FI-010", 7, 1.0, "2019-05-27"),
    h("INS-CA-003", 10, 0.0, "2025-01-01"),
    h("INS-EQ-012", 8, -14.0, "2019-05-27"),
    h("INS-EQ-004", 11, 5.0, "2015-02-11"),
    h("INS-EQ-001", 12, 47.0, "2013-07-08"),
    h("INS-CM-001", 3, 39.0, "2022-11-21"),
])
need("CN-009", "CL-0012", "School fees, two grandchildren", "HKD", 1_250_000,
     "2026-08-20", "2032-08-20", "Annual", "Confirmed")
tx("2026-08-20", "PF-0014", "Withdrawal", "HKD", -1_250_000, "Annual school fees, two grandchildren.")

# CL-0013 · the same structural problem as CL-0012, in a domicile where the losses are worth something
client("CL-0013", "Pornthip Srisuk", 63, "F", "Thailand", "Thailand", "Thailand", "Singapore", "USD",
       "Pre-retirement", "Founder - frozen seafood exporter", "Income", 4, 10, "Medium",
       "Replace her salary with portfolio income from 2027; hand the business to her daughter; "
       "keep a reserve in US dollars", "2015-11-30", "2027-11-30", "English")
portfolio("PF-0015", "CL-0013", "Income Advisory Portfolio", "INC", "Advisory", "USD", "2015-12-10", 26.1e6, [
    h("INS-FI-002", 11, -15.0, "2021-04-20"),
    h("INS-FI-016", 10, -12.0, "2021-09-13"),
    h("INS-FI-007", 6, 2.0, "2022-02-03"),
    h("INS-FI-010", 14, 1.0, "2016-01-11"),
    h("INS-FI-011", 9, -1.5, "2018-05-21"),
    h("INS-FI-014", 8, -8.0, "2020-11-24"),
    h("INS-EQ-001", 14, 48.0, "2016-01-11"),
    h("INS-EQ-004", 10, 7.0, "2017-08-03"),
    h("INS-CA-007", 14, 2.0, "2024-01-01"),
    h("INS-CM-001", 4, 33.0, "2022-08-29"),
])

# CL-0014 · two big asks next year against a modest liquid pool
client("CL-0014", "Tran Minh Chau", 55, "M", "Vietnam", "Singapore", "Singapore", "Singapore", "SGD",
       "Business owner", "Founder - coffee export and roasting company", "Balanced", 5, 12, "High",
       "Pay for two children's university education in the UK; build an investment property "
       "portfolio in Singapore; keep a cash buffer for the business", "2017-04-03", "2027-04-30", "English")
portfolio("PF-0016", "CL-0014", "Advisory Balanced Portfolio", "BAL", "Advisory", "SGD", "2017-04-15", 16.2e6, [
    h("INS-EQ-001", 22, 31.0, "2017-04-20"),
    h("INS-EQ-004", 12, 5.0, "2018-02-26"),
    h("INS-EQ-012", 8, -9.0, "2019-11-04"),
    h("INS-FI-005", 10, 0.0, "2022-05-16"),
    h("INS-FI-015", 10, 2.0, "2023-01-09"),
    h("INS-FI-013", 9, 2.5, "2021-08-23"),
    h("INS-FI-014", 6, -5.0, "2021-08-23"),
    h("INS-AL-005", 8, 2.0, "2021-07-01"),
    h("INS-AL-002", 6, 5.0, "2022-02-28"),
    h("INS-CA-002", 6, 0.0, "2025-01-01"),
    h("INS-CM-001", 3, 28.0, "2023-05-02"),
])
need("CN-010", "CL-0014", "University fees, two children (United Kingdom)", "GBP", 185_000,
     "2026-09-01", "2030-09-01", "Annual", "Confirmed")
need("CN-011", "CL-0014", "Working capital injection into the coffee business", "USD", 4_000_000,
     "2027-03-31", "2027-03-31", "One-off", "Likely")
need("CN-012", "CL-0014", "Deposit on a Singapore investment property", "SGD", 3_600_000,
     "2027-01-15", "2027-01-15", "One-off", "Likely")
tx("2026-09-01", "PF-0016", "Withdrawal", "SGD", -317_000, "University fees, two children, first year.")

# CL-0015 · an apartment for his parents, paid in renminbi
client("CL-0015", "Liu Zhen", 58, "M", "China", "Singapore", "China", "Singapore", "USD",
       "Pre-retirement", "Former senior executive, internet platform company; vested shares",
       "Balanced Growth", 6, 12, "Medium",
       "Buy an apartment in Shanghai for his parents; diversify out of Chinese technology shares; "
       "retire in Singapore", "2020-01-20", "2027-01-31", "Simplified Chinese")
portfolio("PF-0017", "CL-0015", "Advisory Balanced Growth Portfolio", "BALG", "Advisory", "USD", "2020-02-01", 18.3e6, [
    h("INS-EQ-007", 13, -19.0, "2020-02-05"),
    h("INS-EQ-003", 12, 52.0, "2020-02-05"),
    h("INS-EQ-001", 20, 37.0, "2020-02-05"),
    h("INS-EQ-004", 10, 1.0, "2021-05-18"),
    h("INS-FI-010", 16, -1.0, "2020-02-05"),
    h("INS-FI-001", 10, -0.5, "2023-10-30"),
    h("INS-AL-001", 6, 8.0, "2021-06-30"),
    h("INS-CM-001", 5, 34.0, "2022-11-07"),
    h("INS-CA-001", 8, 0.0, "2025-01-01"),
])
need("CN-013", "CL-0015", "Apartment purchase for his parents, Shanghai", "CNH", 14_500_000,
     "2027-02-26", "2027-02-26", "One-off", "Confirmed")

# CL-0016 · content, retired, and nearly inside every line
client("CL-0016", "Klaus Reinhardt", 70, "M", "Switzerland", "Singapore", "Switzerland", "Singapore", "CHF",
       "Retired", "Former owner, Swiss precision instruments distributor", "Balanced", 4, 10, "Medium",
       "Live comfortably between Singapore and Lucerne; keep the capital for his grandchildren; "
       "no surprises", "2013-06-24", "2027-06-30", "German")
portfolio("PF-0018", "CL-0016", "Balanced Mandate", "BAL", "Discretionary", "CHF", "2013-07-01", 28.4e6, [
    h("INS-EQ-001", 22, 57.0, "2013-07-05"),
    h("INS-EQ-006", 12, 14.0, "2016-11-14"),
    h("INS-EQ-002", 8, 49.0, "2015-02-23"),
    h("INS-FI-006", 14, -2.5, "2022-09-05"),
    h("INS-FI-010", 12, 1.0, "2018-04-16"),
    h("INS-FI-012", 10, -0.5, "2018-04-16"),
    h("INS-CM-002", 11, 52.0, "2019-08-12"),
    h("INS-AL-001", 5, 13.0, "2017-03-31"),
    h("INS-CA-006", 6, 0.0, "2025-01-01"),
])

# CL-0017 · bonds below the floor after a good year for equities
client("CL-0017", "Siddharth Rao", 48, "M", "India", "India", "India", "Singapore", "USD",
       "Peak earning years", "Partner, Mumbai law firm; inherited family property", "Balanced Growth", 6, 15, "Low",
       "Build an offshore portfolio for the children's education abroad; keep it simple and "
       "low-cost", "2021-02-08", "2027-02-28", "English")
portfolio("PF-0019", "CL-0017", "Advisory Balanced Growth Portfolio", "BALG", "Advisory", "USD", "2021-02-15", 14.9e6, [
    h("INS-EQ-001", 36, 33.0, "2021-02-18"),
    h("INS-EQ-002", 18, 37.0, "2021-02-18"),
    h("INS-EQ-004", 12, 2.0, "2021-02-18"),
    h("INS-FI-010", 10, -1.0, "2021-02-18"),
    h("INS-AL-001", 9, 8.0, "2021-06-30"),
    h("INS-CM-001", 7, 31.0, "2022-06-13"),
    h("INS-CA-001", 8, 0.0, "2025-01-01"),
])

# CL-0018, CL-0019 · nothing outstanding — the book should say so, not stay blank
client("CL-0018", "Daniel Okafor-Lee", 36, "M", "United Kingdom", "Singapore", "Singapore", "Singapore", "SGD",
       "Wealth accumulation", "Co-founder, payments start-up; part-exit in 2024", "Growth", 8, 25, "Low",
       "Grow the portfolio for the long term; buy a home in Singapore around 2028", "2024-08-12",
       "2027-08-31", "English")
portfolio("PF-0020", "CL-0018", "Advisory Growth Portfolio", "GROW", "Advisory", "SGD", "2024-08-20", 9.2e6, [
    h("INS-EQ-001", 38, 16.0, "2024-08-22"),
    h("INS-EQ-002", 18, 21.0, "2024-08-22"),
    h("INS-EQ-004", 12, 3.0, "2024-08-22"),
    h("INS-EQ-003", 8, 24.0, "2025-02-03"),
    h("INS-FI-010", 12, 0.5, "2024-08-22"),
    h("INS-AL-001", 6, 4.0, "2025-01-31"),
    h("INS-CA-008", 6, 2.0, "2024-08-22"),
])

client("CL-0019", "Ananya Krishnan", 31, "F", "Singapore", "Singapore", "Singapore", "Singapore", "SGD",
       "Recently inherited", "Inheritance from her grandparents' textile business", "Balanced", 5, 30, "Low",
       "Learn how the portfolio works before changing anything; give regularly to education "
       "charities", "2025-07-14", "2026-12-31", "English")
portfolio("PF-0021", "CL-0019", "Balanced Mandate", "BAL", "Discretionary", "SGD", "2025-07-20", 11.4e6, [
    h("INS-EQ-001", 28, 7.0, "2025-07-24"),
    h("INS-EQ-004", 10, 4.0, "2025-07-24"),
    h("INS-EQ-013", 6, 2.0, "2025-07-24"),
    h("INS-FI-005", 14, 0.5, "2025-07-24"),
    h("INS-FI-011", 14, 1.0, "2025-07-24"),
    h("INS-FI-015", 10, 1.5, "2025-07-24"),
    h("INS-AL-001", 7, 3.0, "2025-07-31"),
    h("INS-CM-001", 4, 14.0, "2025-07-24"),
    h("INS-CA-002", 7, 0.0, "2025-07-24"),
])
need("CN-014", "CL-0019", "Seed an education scholarship fund", "SGD", 600_000, "2029-01-15", "2029-01-15",
     "One-off", "Aspirational")

# CL-0020 · custody is wealth but not mandate: the concentration sits where no band can see it
client("CL-0020", "Benjamin Cho", 42, "M", "Singapore", "Singapore", "Singapore", "Singapore", "USD",
       "Peak earning years", "Orthopaedic surgeon; private healthcare practice", "Growth", 7, 20, "Medium",
       "Grow wealth steadily; fund the children's education; avoid single-stock risk",
       "2019-05-06", "2027-05-31", "English")
portfolio("PF-0022", "CL-0020", "Advisory Growth Portfolio", "GROW", "Advisory", "USD", "2019-05-15", 11.2e6, [
    h("INS-EQ-001", 34, 41.0, "2019-05-20"),
    h("INS-EQ-002", 20, 47.0, "2019-05-20"),
    h("INS-EQ-004", 10, 6.0, "2020-09-14"),
    h("INS-FI-010", 15, 0.5, "2019-05-20"),
    h("INS-AL-001", 8, 9.0, "2021-06-30"),
    h("INS-CM-001", 4, 30.0, "2022-04-04"),
    h("INS-CA-001", 9, 0.0, "2025-01-01"),
])
portfolio("PF-0023", "CL-0020", "Transferred Shares Custody Account", "CUSTODY", "Custody", "USD", "2026-04-02", 2.6e6, [
    h("INS-ST-010", 92, 34.0, "2017-03-01", start=3),
    h("INS-CA-001", 8, 0.0, "2026-04-02", start=3),
])
tx("2026-04-02", "PF-0023", "Transfer In", "USD", 2_400_000,
   "Corlane Medical Systems shares transferred in from a US brokerage account.")


# ── the RM's notes ────────────────────────────────────────────────────────
# Written the way an RM writes: partial, subjective, sometimes the only place a
# fact exists. The engine reads these for waivers, refusals, protected positions
# and the like, and quotes the sentence it acted on.
NOTES = [
    ("CL-0001", "2025-11-12", "Meeting", "Quarterly review with Mr Morimoto at the Singapore office. He follows the yen closely and asked twice about the long JGB position, which is now well below what he paid. He would rather wait for the bonds to come back than sell at a loss; he described selling as admitting a mistake. Living costs are drawn quarterly in yen and he wants that to continue unchanged."),
    ("CL-0001", "2026-07-08", "Call", "Mr Morimoto asked for a view on whether the Bank of Japan will keep raising rates and what that means for his bonds. Told him we do not forecast rates, but that we would show him the ladder against his own spending plan. His granddaughter starts university in 2030."),
    ("CL-0002", "2025-10-20", "Meeting", "Lunch with Raymond at the family office in Central. The group is bidding for a land parcel in the New Territories and he expects to fund the deposit personally in early 2027 - he called it certain if they win. He likes the Lombard line and wants it kept open."),
    ("CL-0002", "2026-01-15", "Call", "Raymond subscribed to a 12-month accumulator on Harbourline shares, funded from the Lombard line. I explained the double-up below strike; he acknowledged the risk but proceeded. He will not sell the Harbourline shares - it is the family company and his father still chairs it."),
    ("CL-0002", "2026-03-24", "Call", "Margin warning on the Lombard facility after Hong Kong property sold off. Credit granted a standstill while Raymond looks at options; nothing was sold and nothing was repaid. This needs a proper conversation before the next review."),
    ("CL-0002", "2026-08-28", "Meeting", "Raymond says the land deal is now confirmed for February. He asked for a view on what happens to the Lombard line if Hong Kong property falls again. We have not yet replied with numbers."),
    ("CL-0003", "2026-02-18", "Meeting", "First meeting since Mrs Brandt's husband passed away in December. The Lindenhof shares have been transferred into her conservative mandate from the estate. She wants to keep a meaningful part of the Lindenhof stake for sentimental reasons - her husband ran the company for thirty years. Otherwise she asked us to make it boring."),
    ("CL-0003", "2026-06-10", "Email", "Mrs Brandt's tax adviser in Munich asked for realised and unrealised positions for the German return; sent. The mandate has still not been rebalanced since the transfer in February. This needs a proper conversation with the portfolio manager."),
    ("CL-0004", "2025-10-30", "Meeting", "Arjun is busy with Lumora's next funding round. He was surprised how much of his net worth our statement attributes to Lumora - we still carry the June 2025 Series C price. He expects the next round to be priced much higher; the CFO has not confirmed a date."),
    ("CL-0004", "2026-03-05", "Call", "The semiconductor sell-off took the facility on the founder account past its trigger at the quarter-end check. Arjun asked that nothing in the account be sold; credit agreed to wait for the June valuation."),
    ("CL-0004", "2026-09-12", "Email", "Requested an updated valuation of the Lumora preference shares from the company. Nothing received yet. The mark we carry is fifteen months old and part of the facility's lending value rests on it."),
    ("CL-0005", "2026-01-09", "Meeting", "Annual review with Puan Nurul. She was not aware that her sustainable mandate held the Global Energy Producers Fund until she read the year-end statement, and asked how it got there. Escalated to the portfolio manager the same day."),
    ("CL-0005", "2026-04-16", "Meeting", "The Rimba Lestari position is a family holding from her late father's estate. She has asked that it is not sold without first speaking to her brother, who is the executor. She accepts it does not belong in the mandate."),
    ("CL-0006", "2026-05-06", "Call", "Ms Chen instructed an additional purchase of Qinghe shares after their first-quarter results. She knows the company's customers better than we do and was firm. Confirmed the instruction in writing."),
    ("CL-0006", "2026-08-19", "Meeting", "Ms Chen is looking at flats in Mid-Levels and expects to buy within six months, funded from the portfolio. Discussed how much of the portfolio moves with Qinghe; she had not added up the linked note and the structured basket."),
    ("CL-0007", "2026-03-18", "Meeting", "Edward wants more physical gold, taking the allocation well above the balanced mandate ceiling. Explained the breach in detail and he signed. Suitability waiver on file for the gold allocation."),
    ("CL-0007", "2026-07-22", "Call", "Call with Edward and his wife. She mentioned his declining health and that he wants the foundation endowed while he can attend the signing. The trust deed is ready; the endowment is planned for May 2027."),
    ("CL-0008", "2026-02-25", "Meeting", "Quarterly meeting with Mr Lim Wei Jian, the family office's investment director. Northfield has called again; more calls are expected through 2027 and the infrastructure fund will draw the rest of its commitment within a year."),
    ("CL-0008", "2026-04-07", "Email", "The Serai manager has now gated redemptions for a second consecutive quarter. Our request sits in the queue with no date. Recommend involving the alternatives team before the next capital call."),
    ("CL-0009", "2026-01-21", "Meeting", "Ms Al-Suwaidi wants less dependence on Gulf property and is comfortable taking losses on the long Treasury if it helps. Explained that the UAE does not tax capital gains, so realising the loss brings no tax benefit; the decision is about the allocation alone."),
    ("CL-0010", "2026-03-11", "Meeting", "Signora Ferraro has found the house in Tuscany; completion is April 2027 and the price is agreed. She wants more gold in the meantime. She confirmed the instruction in writing despite the commodity limit."),
    ("CL-0011", "2026-02-12", "Call", "Mr Park called during the export-control headlines. He is not worried - he sold these machines for twenty years - and wants to keep the Veltrion position. He asked for a view on whether the chip cycle has turned; told him we do not call cycles."),
    ("CL-0011", "2026-09-03", "Email", "Mr Park prefers Korean for written correspondence; his assistant translates our English letters today. He asked whether we can write to him in Korean directly."),
    ("CL-0012", "2026-02-02", "Meeting", "Mrs Ho asked why her income portfolio fell in January. Walked her through the Harbourline perpetual. She would rather wait for it to recover than sell; her late husband did business with the family."),
    ("CL-0012", "2026-08-14", "Call", "School fees for both grandchildren paid from the portfolio as usual. Mrs Ho's son may take over the relationship next year and will want to understand the long Treasury."),
    ("CL-0013", "2026-04-24", "Meeting", "Khun Pornthip steps back from the business next spring and wants the portfolio to replace her salary. She was not aware that losses on the bonds could be set against gains for Thai tax; her accountant has asked for the figures."),
    ("CL-0014", "2026-06-19", "Meeting", "Mr Tran expects to put working capital into the coffee business early next year, probably USD 4m. He is also bidding on an investment property in Singapore. Both depend on how the harvest goes."),
    ("CL-0015", "2026-05-28", "Call", "Mr Liu confirmed the Shanghai apartment for his parents; payment is due in February. He wants it paid in renminbi and asked about conversion timing. Told him we do not time currencies."),
    ("CL-0016", "2026-03-30", "Meeting", "Herr Reinhardt is content. He asked us to keep gold near ten percent and to write to him in German. Nothing to action."),
    ("CL-0017", "2026-01-27", "Call", "Mr Rao wants the portfolio kept simple and cheap and prefers index funds. Bonds have slipped below the mandate floor after a good year for equities; raise at the next review."),
    ("CL-0018", "2026-06-02", "Message", "Daniel checked in after the start-up's new funding round. Nothing needed; may look at a home purchase in 2028."),
    ("CL-0019", "2025-11-18", "Meeting", "First meeting with Ms Krishnan after the estate settled. She wants to understand the portfolio before changing anything and plans regular gifts to education charities."),
    ("CL-0020", "2026-04-09", "Meeting", "Dr Cho moved his Corlane shares into a custody account with us. He knows they are a large part of his wealth and says he will diversify after the next earnings."),
]


# ── the year, in the market ───────────────────────────────────────────────
# Invented events. Each names the channels it travelled through, in words the
# instrument universe uses, so the engine can place it beside the holdings it
# could have reached — and say how.
EVENTS = [
    ("2025-10-29", "Policy", "North America", "The Federal Reserve cuts its policy rate by 25bp and signals a pause.", "Government bonds, investment grade credit", "Medium"),
    ("2025-11-20", "Market", "Global", "Semiconductor shares fall 14% in nine sessions after two of the largest cloud providers trim their 2026 capital spending plans.", "Semiconductor, information technology", "High"),
    ("2025-12-19", "Policy", "Japan", "The Bank of Japan raises its policy rate to 0.75%; the ten-year government bond yield reaches 2.0%.", "Japan government bonds", "High"),
    ("2026-01-14", "Credit", "Hong Kong", "A large Hong Kong developer misses a coupon on its offshore perpetual bonds. Hong Kong property shares fall 11% in a week.", "Hong Kong property, real estate securities, perpetual bonds", "Severe"),
    ("2026-02-11", "Geopolitical", "Global", "New export controls restrict sales of advanced chip-making equipment to several Asian markets.", "Semiconductor, information technology", "High"),
    ("2026-03-06", "Market", "Hong Kong", "One-month HIBOR jumps to 4.6% as banks pull back from property lending; Hong Kong bank shares fall 8%.", "Financials, Hong Kong property", "High"),
    ("2026-03-26", "Credit", "Global", "Two mid-sized private credit managers restrict redemptions after marking down loans to property and consumer borrowers.", "Private credit", "Medium"),
    ("2026-04-22", "Market", "Global", "Gold sets a new record as central banks keep buying.", "Gold, precious metals", "Medium"),
    ("2026-05-14", "Market", "North America", "The US Treasury long end sells off on higher deficit projections; the 30-year yield rises 45bp in a month.", "Government bonds, investment grade credit, technology", "High"),
    ("2026-06-17", "Policy", "North America", "The Federal Reserve holds, and its projections push the next cut into the autumn.", "Government bonds, technology", "Medium"),
    ("2026-07-09", "Policy", "Greater China", "A state-backed funding facility for property developers is announced; Hong Kong property shares rebound 9%.", "Hong Kong property, real estate securities", "Medium"),
    ("2026-08-12", "Commodity", "Global", "Major oil producers end voluntary output cuts and Brent falls 14% in two weeks.", "Energy, commodity", "Medium"),
    ("2026-09-16", "Policy", "North America", "The Federal Reserve cuts by 25bp.", "Government bonds, investment grade credit", "Medium"),
    ("2026-09-24", "Policy", "Japan", "The Bank of Japan raises its policy rate to 1.0% and the yen strengthens past 136 per dollar.", "Japan government bonds, Japan equity", "Medium"),
]


def factor_level(name, base):
    out, v = [base], base
    for r in FACTORS[name]:
        v *= 1 + r / 100.0
        out.append(v)
    return out


def blend(a, b, wa):
    return [x * wa + y * (1 - wa) for x, y in zip(a, b)]


MARKET = [
    ("SPX", "S&P 500 Index", "Equity index", "points", factor_level("dm_eq", 6610.0)),
    ("NDX", "Nasdaq-100 Index", "Equity index", "points", factor_level("us_tech", 24380.0)),
    ("SOX", "Philadelphia Semiconductor Index", "Equity index", "points", factor_level("semis", 6240.0)),
    ("MSCI_ASIA_XJP", "MSCI Asia ex-Japan Index", "Equity index", "points", factor_level("asia_eq", 842.0)),
    ("HSI", "Hang Seng Index", "Equity index", "points",
     blend(factor_level("asia_eq", 26100.0), factor_level("hk_prop", 26100.0), 0.75)),
    ("HS_PROP", "Hang Seng Properties Index", "Equity index", "points", factor_level("hk_prop", 21450.0)),
    ("N225", "Nikkei 225 Index", "Equity index", "points", factor_level("japan_eq", 44300.0)),
    ("STI", "Straits Times Index", "Equity index", "points", factor_level("fin_asia", 4310.0)),
    ("GOLD_USD_OZ", "Gold spot", "Commodity", "USD/troy oz", factor_level("gold", 3810.0)),
    ("BRENT_USD_BBL", "Brent crude", "Commodity", "USD/barrel", [68.4, 70.1, 71.6, 66.9, 57.2]),
    ("UST_2Y_PCT", "US Treasury 2-year yield", "Rates", "percent", [3.62, 3.48, 3.55, 3.81, 3.52]),
    ("UST_10Y_PCT", "US Treasury 10-year yield", "Rates", "percent", [4.14, 4.09, 4.26, 4.82, 4.51]),
    ("UST_30Y_PCT", "US Treasury 30-year yield", "Rates", "percent", [4.71, 4.68, 4.86, 5.38, 5.04]),
    ("JGB_10Y_PCT", "Japan Government Bond 10-year yield", "Rates", "percent", [1.64, 2.01, 2.19, 2.36, 2.55]),
    ("FED_FUNDS_UPPER_PCT", "Fed funds target, upper bound", "Rates", "percent", [4.25, 4.00, 4.00, 4.00, 3.75]),
    ("BOJ_POLICY_PCT", "Bank of Japan policy rate", "Rates", "percent", [0.50, 0.75, 0.75, 0.75, 1.00]),
    ("HIBOR_1M_PCT", "Hong Kong one-month HIBOR", "Rates", "percent", [3.56, 3.81, 4.62, 4.07, 3.71]),
    ("US_CPI_YOY_PCT", "US CPI, year on year", "Macro", "percent", [3.0, 2.8, 3.1, 3.0, 2.7]),
    ("VIX", "CBOE Volatility Index", "Volatility", "points", [16.2, 21.5, 27.8, 17.9, 15.1]),
]


# ── deriving every row ────────────────────────────────────────────────────
def snap_index(day):
    """The first snapshot on or after a date — when a position starts to show."""
    for k, d in enumerate(DATES):
        if day <= d:
            return k
    return len(DATES) - 1


def round_qty(i, units):
    if i["_kind"] == "cash":
        return float(round(units, -3))
    if i["_kind"] == "bond":
        return float(round(units, -1))              # units of 100 nominal
    if units >= 1000:
        return float(round(units, -2))
    return float(round(units))


def build_holdings():
    rows = []
    for p in PORTFOLIOS:
        base = p["base_currency"]
        for iid, w, pnl, acquired, opt in p["_holdings"]:
            i = I[iid]
            path = i["_path"]
            mv_usd_today = p["_usd"] * w / 100.0
            mv_local_today = mv_usd_today / usd_per(i["currency"], 4)
            price_unit = path[4] / (100.0 if i["_kind"] == "bond" else 1.0)
            q_today = round_qty(i, mv_local_today / price_unit)
            start = opt.get("start", 0)
            mult = opt.get("qty", [1.0] * 5)
            avg_cost = path[4] / (1 + pnl / 100.0)
            k_acq = 0 if acquired < DATES[0] else snap_index(acquired)
            for k in range(start, 5):
                q = round_qty(i, q_today * mult[k])
                px = path[k]
                mv_local = q * px / (100.0 if i["_kind"] == "bond" else 1.0)
                mv_usd = mv_local * usd_per(i["currency"], k)
                mv_base = mv_usd / usd_per(base, k)
                cost_local = q * avg_cost / (100.0 if i["_kind"] == "bond" else 1.0)
                cost_base = convert(cost_local, i["currency"], base, k_acq)
                rows.append({
                    "snapshot_date": DATES[k], "portfolio_id": p["portfolio_id"],
                    "client_id": p["client_id"], "instrument_id": iid,
                    "instrument_name": i["instrument_name"], "asset_class": i["asset_class"],
                    "sub_asset_class": i["sub_asset_class"], "sector": i["sector"],
                    "region": i["region"], "instrument_ccy": i["currency"],
                    "quantity": q, "price_local": px, "market_value_local": round(mv_local, 2),
                    "portfolio_ccy": base, "market_value_base": round(mv_base, 2),
                    "market_value_usd": round(mv_usd, 2), "weight_pct": 0.0,
                    "avg_cost_local": round(avg_cost, 4), "cost_basis_base": round(cost_base, 2),
                    "unrealised_pnl_base": round(mv_base - cost_base, 2),
                    "unrealised_pnl_pct": round(100 * (mv_base - cost_base) / cost_base, 2) if cost_base else 0.0,
                    "lending_value_base": round(mv_base * i["_adv"] / 100.0, 2),
                    "advance_rate_pct": float(i["_adv"]), "liquidity_tier": i["liquidity_tier"],
                    "valuation_date": i["_stale"] or DATES[k], "acquired_date": acquired,
                })
    totals = {}
    for r in rows:
        key = (r["portfolio_id"], r["snapshot_date"])
        totals[key] = totals.get(key, 0.0) + r["market_value_base"]
    for r in rows:
        r["weight_pct"] = round(100 * r["market_value_base"] / totals[(r["portfolio_id"], r["snapshot_date"])], 4)
    return rows, totals


def quarter_ends(start="2025-10-01", end=TODAY):
    return [d for d in ("2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30") if start <= d <= end]


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def build_transactions(rows, totals):
    """Income, fees, interest, and the special movements each story needs."""
    out = []
    by_pk = {}
    for r in rows:
        by_pk.setdefault((r["portfolio_id"], r["instrument_id"]), {})[r["snapshot_date"]] = r
    pmap = {p["portfolio_id"]: p for p in PORTFOLIOS}

    for (pid, iid), snaps in sorted(by_pk.items()):
        i = I[iid]
        if not i["_income"]:
            continue
        p = pmap[pid]
        if i["_kind"] == "bond":
            kind, months = "Coupon", (5, 11)               # semi-annual
        elif i["asset_class"] == C:
            kind, months = "Interest", (12, 3, 6, 9)
        elif i["sub_asset_class"] in ("Real Estate Securities", "Private Credit", "Private Real Estate"):
            kind, months = "Distribution", (12, 3, 6, 9)
        elif i["asset_class"] == EQ:
            kind, months = "Dividend", (11, 5) if i["_kind"] == "stock" else (12, 6)
        else:
            continue
        for y, m in [(2025, 10), (2025, 11), (2025, 12)] + [(2026, mm) for mm in range(1, 10)]:
            if m not in months:
                continue
            day = "%d-%02d-%02d" % (y, m, 15 if kind != "Interest" else 28)
            k = snap_index(day)
            r = snaps.get(DATES[k])
            if not r:
                continue
            per_year = len(months)
            if kind == "Coupon":
                amount = r["quantity"] * 100 * i["_income"] / 100.0 / per_year
            else:
                amount = r["market_value_local"] * i["_income"] / 100.0 / per_year
            out.append(dict(trade_date=day, portfolio_id=pid, transaction_type=kind,
                            instrument_id=iid, quantity="", price_local="", currency=i["currency"],
                            amount=round(amount, 2), narrative="Scheduled %s received." % kind.lower()))

    fee = {"Discretionary": 0.85, "Advisory": 0.55, "Custody": 0.12}
    for p in PORTFOLIOS:
        for qe in quarter_ends():
            aum = totals.get((p["portfolio_id"], qe))
            if not aum:
                continue
            rate = fee[p["service_model"]]
            label = {"Discretionary": "discretionary management", "Advisory": "advisory",
                     "Custody": "custody"}[p["service_model"]]
            out.append(dict(trade_date=shift(qe, 5), portfolio_id=p["portfolio_id"],
                            transaction_type="Management Fee", instrument_id="", quantity="",
                            price_local="", currency=p["base_currency"],
                            amount=round(-aum * rate / 100.0 / 4, 2),
                            narrative="Quarterly %s fee at %.2f%% p.a." % (label, rate)))
    for f in FACILITIES:
        for qe in quarter_ends():
            k = DATES.index(qe)
            out.append(dict(trade_date=shift(qe, 1), portfolio_id=f["collateral_portfolio_id"],
                            transaction_type="Interest Charge", instrument_id="", quantity="",
                            price_local="", currency=f["facility_ccy"],
                            amount=round(-f["_drawn"][k] * f["interest_rate_pct"] / 100.0 / 4, 2),
                            narrative="Quarterly interest on %s at %.2f%% p.a." % (
                                f["facility_id"], f["interest_rate_pct"])))

    drawn = {f["facility_id"]: f["_drawn"] for f in FACILITIES}
    for t in SPECIAL_TX:
        t = dict(t)
        if t["transaction_type"] == "Facility Drawdown":
            path = drawn[t["narrative"].split(" on ")[1].split(" ")[0]]
            k = snap_index(t["trade_date"])
            t["amount"] = round(path[k] - path[k - 1], 2)
        if t["transaction_type"] in ("Buy", "Structured Product Subscription") and t["amount"] == "":
            k = snap_index(t["trade_date"])
            snaps = by_pk[(t["portfolio_id"], t["instrument_id"])]
            r = snaps[DATES[k]]
            prev = snaps.get(DATES[k - 1]) if k else None
            qty = r["quantity"] - (prev["quantity"] if prev else 0.0)
            px = I[t["instrument_id"]]["_path"][k]
            t["quantity"], t["price_local"] = qty, px
            t["currency"] = I[t["instrument_id"]]["currency"]
            unit = 100.0 if I[t["instrument_id"]]["_kind"] == "bond" else 1.0
            t["amount"] = round(-qty * px / unit, 2)
        out.append(t)

    out.sort(key=lambda t: (t["trade_date"], t["portfolio_id"], t["transaction_type"]))
    for n, t in enumerate(out, 1):
        t["transaction_id"] = "TXN-%05d" % n
        t["settlement_date"] = t["trade_date"] if t["transaction_type"] in (
            "Interest", "Coupon", "Dividend", "Distribution", "Management Fee", "Interest Charge",
            "Withdrawal", "Transfer In", "Capital Call", "Facility Drawdown", "Redemption Request",
            "Valuation Update") else shift(t["trade_date"], 2)
        t["client_id"] = pmap[t["portfolio_id"]]["client_id"]
        t["instrument_name"] = I[t["instrument_id"]]["instrument_name"] if t["instrument_id"] else ""
    return out


def calibrate_facilities(rows):
    """Lending value comes from the collateral portfolio, row by row; the drawn
    amount is the story. One facility states its LTV today and the drawn path is
    scaled to meet it, which keeps the step at the drawdown intact."""
    for f in FACILITIES:
        pid = f["collateral_portfolio_id"]
        lv = [sum(r["lending_value_base"] for r in rows if r["portfolio_id"] == pid
                  and r["snapshot_date"] == d) for d in DATES]
        mv = [sum(r["market_value_base"] for r in rows if r["portfolio_id"] == pid
                  and r["snapshot_date"] == d) for d in DATES]
        if f.get("_target_ltv_today"):
            scale = f["_target_ltv_today"] / 100.0 * lv[4] / f["_drawn"][4]
            f["_drawn"] = [round(x * scale, -5) for x in f["_drawn"]]
        f["_lv"], f["_mv"] = lv, mv


def write_csv(name, fields, rows):
    with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    rows, totals = build_holdings()
    calibrate_facilities(rows)
    txns = build_transactions(rows, totals)

    # clients
    usd_by_client = {}
    for p in PORTFOLIOS:
        p["_usd_today"] = sum(r["market_value_usd"] for r in rows
                              if r["portfolio_id"] == p["portfolio_id"] and r["snapshot_date"] == TODAY)
        usd_by_client[p["client_id"]] = usd_by_client.get(p["client_id"], 0.0) + p["_usd_today"]
    crow = []
    for c in CLIENTS:
        aum = usd_by_client[c["client_id"]]
        crow.append(dict(c, rm_id=RM["rm_id"], rm_name=RM["rm_name"], rm_desk=RM["rm_desk"],
                         wealth_band="UHNW" if aum >= 30e6 else "HNW", total_aum_usd=round(aum, 2)))
    write_csv("clients.csv", ["client_id", "client_name", "age", "gender", "nationality",
                              "country_of_residence", "tax_domicile", "booking_centre", "rm_id",
                              "rm_name", "rm_desk", "base_currency", "wealth_band", "total_aum_usd",
                              "life_stage", "source_of_wealth", "risk_profile",
                              "risk_tolerance_score", "investment_horizon_years", "liquidity_needs",
                              "objectives", "client_since", "kyc_review_due", "pep_status",
                              "reporting_language"], crow)

    # portfolios
    prow = []
    for p in PORTFOLIOS:
        code = p["mandate_code"]
        r = dict(p, mandate_name=MANDATES[code][0] if code in MANDATES else "Custody - no mandate",
                 benchmark="HR %s %s Composite" % (MANDATES[code][0], p["base_currency"])
                 if code in MANDATES else "None - custody only",
                 aum_usd_current=round(p["_usd_today"], 2))
        for d in DATES:
            r["aum_" + d] = round(totals.get((p["portfolio_id"], d), 0.0), 2)
        prow.append(r)
    write_csv("portfolios.csv", ["portfolio_id", "client_id", "portfolio_name", "mandate_code",
                                 "mandate_name", "service_model", "base_currency", "inception_date",
                                 "benchmark"] + ["aum_" + d for d in DATES] + ["aum_usd_current"], prow)

    write_csv("holdings.csv", ["snapshot_date", "portfolio_id", "client_id", "instrument_id",
                               "instrument_name", "asset_class", "sub_asset_class", "sector", "region",
                               "instrument_ccy", "quantity", "price_local", "market_value_local",
                               "portfolio_ccy", "market_value_base", "market_value_usd", "weight_pct",
                               "avg_cost_local", "cost_basis_base", "unrealised_pnl_base",
                               "unrealised_pnl_pct", "lending_value_base", "advance_rate_pct",
                               "liquidity_tier", "valuation_date", "acquired_date"], rows)

    irow = []
    for i in INSTRUMENTS:
        r = dict(i)
        for k, d in enumerate(DATES):
            r["price_" + d] = i["_path"][k]
        irow.append(r)
    write_csv("instruments.csv", ["instrument_id", "instrument_name", "asset_class", "sub_asset_class",
                                  "sector", "region", "currency", "liquidity_tier",
                                  "underlying_reference", "sustainability_excluded",
                                  "concentration_limit_applies"] + ["price_" + d for d in DATES], irow)

    mrow = []
    for code, (name, single, notes, bands) in MANDATES.items():
        for cls in ORDER:
            lo, tgt, hi = bands[cls]
            mrow.append(dict(mandate_code=code, mandate_name=name, asset_class=cls, min_pct=lo,
                             target_pct=tgt, max_pct=hi, max_single_position_pct=single,
                             mandate_notes=notes))
    write_csv("mandates.csv", ["mandate_code", "mandate_name", "asset_class", "min_pct", "target_pct",
                               "max_pct", "max_single_position_pct", "mandate_notes"], mrow)

    write_csv("transactions.csv", ["transaction_id", "trade_date", "settlement_date", "portfolio_id",
                                   "client_id", "transaction_type", "instrument_id", "instrument_name",
                                   "quantity", "price_local", "currency", "amount", "narrative"], txns)

    frow = []
    for f in FACILITIES:
        r = dict(f)
        for k, d in enumerate(DATES):
            drawn, lv = f["_drawn"][k], f["_lv"][k]
            r["drawn_" + d] = drawn
            r["collateral_market_value_" + d] = round(f["_mv"][k], 2)
            r["lending_value_" + d] = round(lv, 2)
            r["ltv_pct_" + d] = round(100 * drawn / lv, 2)
            r["headroom_" + d] = round(lv - drawn, 2)
        r["utilisation_pct_current"] = round(100 * f["_drawn"][4] / f["credit_limit"], 2)
        frow.append(r)
    ffields = ["facility_id", "client_id", "collateral_portfolio_id", "facility_type", "facility_ccy",
               "credit_limit", "interest_rate_pct", "margin_call_ltv_pct"]
    for d in DATES:
        ffields += ["drawn_" + d, "collateral_market_value_" + d, "lending_value_" + d,
                    "ltv_pct_" + d, "headroom_" + d]
    write_csv("credit_facilities.csv", ffields + ["utilisation_pct_current"], frow)

    write_csv("commitments.csv", ["commitment_id", "client_id", "portfolio_id", "fund_name", "currency",
                                  "committed", "called_to_date", "uncalled", "expected_call_window"],
              COMMITMENTS)
    write_csv("planned_cash_needs.csv", ["need_id", "client_id", "description", "currency", "amount",
                                         "due_from", "due_to", "recurrence", "certainty"], NEEDS)

    mkt = []
    for k, d in enumerate(DATES):
        for sid, name, cat, unit, vals in MARKET:
            mkt.append(dict(snapshot_date=d, series_id=sid, series_name=name, category=cat, unit=unit,
                            value=round(vals[k], 2), snapshot_label=LABELS[k]))
        for ccy, (sid, per_unit, vals) in FX.items():
            mkt.append(dict(snapshot_date=d, series_id=sid, series_name="%s %s" % (
                FX_NAMES[ccy], "in US dollars" if per_unit else "per US dollar"), category="FX",
                unit="USD per %s" % ccy if per_unit else "%s per USD" % ccy,
                value=vals[k], snapshot_label=LABELS[k]))
    write_csv("market_context.csv", ["snapshot_date", "series_id", "series_name", "category", "unit",
                                     "value", "snapshot_label"], mkt)

    write_csv("event_log.csv", ["event_date", "event_type", "region", "description",
                                "primary_transmission", "severity"],
              [dict(zip(["event_date", "event_type", "region", "description",
                         "primary_transmission", "severity"], e)) for e in EVENTS])

    notes = [{"note_id": "N-%03d" % n, "client_id": cid, "note_date": d, "rm_id": RM["rm_id"],
              "rm_name": RM["rm_name"], "channel": ch, "note": text}
             for n, (cid, d, ch, text) in enumerate(sorted(NOTES, key=lambda x: (x[0], x[1])), 1)]
    with open(os.path.join(HERE, "rm_notes.json"), "w", encoding="utf-8") as fh:
        json.dump(notes, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("  %d clients, %d portfolios, %d holdings rows, %d instruments, %d transactions, "
          "%d notes" % (len(CLIENTS), len(PORTFOLIOS), len(rows), len(INSTRUMENTS), len(txns),
                        len(notes)))
    print("  book today: USD %.1fm" % (sum(usd_by_client.values()) / 1e6))
    for f in FACILITIES:
        print("  %s LTV %s against %.0f%%" % (f["facility_id"], " -> ".join(
            "%.1f" % (100 * a / b) for a, b in zip(f["_drawn"], f["_lv"])), f["margin_call_ltv_pct"]))


if __name__ == "__main__":
    main()
