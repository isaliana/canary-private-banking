"""
Canonical access to the dataset.

Every trap the data sets is handled here, once, so no module has to remember it:
FX conversion, custody portfolios that are wealth but not mandate, lending value
that is not market value, look-through into structured products, stale marks,
and missing fields.

Standard library only — the dataset is about a thousand position rows and does
not need pandas.
"""
import csv
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Instrument-name suffixes that carry no identity, stripped before matching a
# structured product's underlying_reference back to an instrument in the universe.
_SUFFIXES = re.compile(
    r"\b(Ltd|Limited|Inc|Corp|Corporation|Tbk|AB|KK|Holdings?|Group|Pte\.?\s*Ltd|ADR|plc|SA|NV)\b\.?",
    re.I,
)


def _norm(name):
    """Loose key for matching a referenced name to an instrument."""
    return re.sub(r"[^a-z0-9]+", " ", _SUFFIXES.sub("", name or "").lower()).strip()


def _f(value, default=0.0):
    """Floats that survive blank cells."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Book:
    def __init__(self, data_dir=DATA):
        self.dir = data_dir
        self.clients = self._csv("clients.csv")
        self.portfolios = self._csv("portfolios.csv")
        self.holdings = self._csv("holdings.csv")
        self.instruments = self._csv("instruments.csv")
        self.mandates = self._csv("mandates.csv")
        self.transactions = self._csv("transactions.csv")
        self.facilities = self._csv("credit_facilities.csv")
        self.commitments = self._csv("commitments.csv")
        self.cash_needs = self._csv("planned_cash_needs.csv")
        self.market = self._csv("market_context.csv")
        self.events = self._csv("event_log.csv")
        with open(os.path.join(data_dir, "rm_notes.json"), encoding="utf-8") as fh:
            self.notes = json.load(fh)

        self.dates = sorted({r["snapshot_date"] for r in self.holdings})
        self.today = self.dates[-1]
        self.start = self.dates[0]

        self.C = {r["client_id"]: r for r in self.clients}
        self.P = {r["portfolio_id"]: r for r in self.portfolios}
        self.I = {r["instrument_id"]: r for r in self.instruments}

        self._build_fx()
        self._build_positions()
        self._build_mandates()
        self._build_lookthrough()
        self._build_flags()

    def _csv(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    # ── FX ────────────────────────────────────────────────────────────────
    def _build_fx(self):
        """market_context quotes each pair in market convention. Normalise so
        fx[date][ccy] is always USD per one unit of that currency."""
        self.fx = defaultdict(lambda: {"USD": 1.0})
        for r in self.market:
            if r["category"] != "FX":
                continue
            sid, v, d = r["series_id"], _f(r["value"]), r["snapshot_date"]
            if not v:
                continue
            if sid.startswith("USD"):          # USDSGD = SGD per USD
                self.fx[d][sid[3:]] = 1.0 / v
            else:                              # EURUSD = USD per EUR
                self.fx[d][sid[:3]] = v

    def to_usd(self, amount, ccy, date=None):
        rate = self.fx[date or self.today].get(ccy)
        if rate is None:
            raise KeyError("no FX rate for %s at %s" % (ccy, date or self.today))
        return amount * rate

    def usd_price(self, iid, date):
        """USD unit price of any instrument at any snapshot, held or not."""
        raw = self.I[iid].get("price_" + date, "")
        if raw == "":
            return None
        return _f(raw) * self.fx[date][self.I[iid]["currency"]]

    # ── positions ─────────────────────────────────────────────────────────
    def _build_positions(self):
        self._by_client = defaultdict(lambda: defaultdict(list))
        self._by_portfolio = defaultdict(lambda: defaultdict(list))
        for r in self.holdings:
            r["_mv"] = _f(r["market_value_usd"])
            r["_qty"] = _f(r["quantity"])
            r["_lend_base"] = _f(r["lending_value_base"])
            r["_mv_base"] = _f(r["market_value_base"])
            # cost basis is struck at the historic rate, so convert P&L with the
            # row's own base->USD ratio rather than today's
            ratio = (r["_mv"] / r["_mv_base"]) if r["_mv_base"] else 1.0
            r["_pnl"] = _f(r["unrealised_pnl_base"]) * ratio
            self._by_client[r["client_id"]][r["snapshot_date"]].append(r)
            self._by_portfolio[r["portfolio_id"]][r["snapshot_date"]].append(r)

    def rows(self, client_id, date=None):
        return self._by_client[client_id][date or self.today]

    def portfolio_rows(self, portfolio_id, date=None):
        return self._by_portfolio[portfolio_id][date or self.today]

    def positions(self, client_id, date=None):
        """Instrument -> aggregated position across all of a client's portfolios."""
        out = {}
        for r in self.rows(client_id, date):
            p = out.setdefault(r["instrument_id"], {"qty": 0.0, "mv": 0.0, "lend": 0.0, "pnl": 0.0})
            p["qty"] += r["_qty"]
            p["mv"] += r["_mv"]
            p["lend"] += r["_lend_base"]
            p["pnl"] += r["_pnl"]
        return out

    def wealth(self, client_id, date=None):
        return sum(r["_mv"] for r in self.rows(client_id, date))

    def daily_liquid(self, client_id, date=None, exclude_portfolios=()):
        return sum(r["_mv"] for r in self.rows(client_id, date)
                   if r["liquidity_tier"] == "Daily"
                   and r["portfolio_id"] not in exclude_portfolios)

    def client_portfolios(self, client_id):
        return [p for p in self.portfolios if p["client_id"] == client_id]

    def managed_portfolios(self, client_id):
        """Custody accounts are the client's wealth but are measured against no
        mandate. Every band test must use this, never client_portfolios."""
        return [p for p in self.client_portfolios(client_id)
                if p["service_model"] != "Custody"]

    # ── mandates ──────────────────────────────────────────────────────────
    def _build_mandates(self):
        self.bands = defaultdict(dict)
        self.single_limit = {}
        self.mandate_notes = {}
        for r in self.mandates:
            code = r["mandate_code"]
            self.bands[code][r["asset_class"]] = (
                _f(r["min_pct"]), _f(r["target_pct"]), _f(r["max_pct"]))
            self.single_limit[code] = _f(r["max_single_position_pct"])
            self.mandate_notes[code] = r["mandate_notes"]

    # ── look-through ──────────────────────────────────────────────────────
    def _build_lookthrough(self):
        """Derive real economic exposure from underlying_reference and the
        'ref. X' pattern in instrument names, rather than hardcoding a map.

        exposure_names(iid) -> [(display_name, instrument_id or None)]
        A wrapper contributes its FULL value to each leg: a worst-of basket is
        exposed to every name in it, so the legs deliberately do not sum to 100%.
        """
        by_key = {}
        for r in self.instruments:
            if r["concentration_limit_applies"] == "Y" and r["asset_class"] != "Structured Products":
                by_key.setdefault(_norm(r["instrument_name"]), r["instrument_id"])
        # a bond issued by a listed name is the same credit as its equity
        for r in self.instruments:
            m = re.match(r"^(.*?)\s+\d", r["instrument_name"])
            if m and r["asset_class"] == "Fixed Income":
                by_key.setdefault(_norm(m.group(1)), r["instrument_id"])

        self.lookthrough = {}
        for r in self.instruments:
            iid, ref, name = r["instrument_id"], r["underlying_reference"], r["instrument_name"]
            legs = []
            if r["asset_class"] == "Structured Products":
                body = ref
                for prefix in ("Worst-of basket:", "Single underlying:", "Underlying:"):
                    if body.startswith(prefix):
                        body = body[len(prefix):]
                        break
                else:
                    # e.g. the accumulator, whose reference is all mechanics —
                    # the name carries the underlying instead
                    m = re.search(r"ref\.\s*(.+?)(?:,|$)", name)
                    body = m.group(1) if m else ""
                for part in body.split("/"):
                    part = re.split(r",", part)[0].strip()
                    if not part or len(part) < 4:
                        continue
                    if re.search(r"\b(spot|autocall|observation|quarterly|strike)\b", part, re.I):
                        continue
                    legs.append((part, by_key.get(_norm(part))))
            elif r["concentration_limit_applies"] == "Y" and r["asset_class"] in (
                    "Equity", "Fixed Income", "Alternatives"):
                # a single name is its own exposure; bonds resolve to the issuer
                m = re.match(r"^(.*?)\s+\d", name)
                display = (m.group(1) if m else name).strip()
                legs.append((display, by_key.get(_norm(display), iid)))
            self.lookthrough[iid] = legs

    def exposure_by_name(self, client_id, date=None):
        """Aggregate single-name exposure across every portfolio, counting a
        structured product's full value against each basket leg."""
        agg = defaultdict(lambda: {"usd": 0.0, "via": set()})
        for iid, pos in self.positions(client_id, date).items():
            for display, target in self.lookthrough.get(iid, []):
                key = self.I[target]["instrument_name"] if target and target in self.I else display
                key = re.sub(r"\s+\d.*$", "", key).strip()
                agg[key]["usd"] += pos["mv"]
                agg[key]["via"].add(iid)
        return agg

    # ── flags and small helpers ───────────────────────────────────────────
    def _build_flags(self):
        self.stale_marks = {}
        for r in self.holdings:
            if r["valuation_date"] != r["snapshot_date"]:
                self.stale_marks[r["instrument_id"]] = r["valuation_date"]

    def pledged_portfolios(self, client_id):
        return {f["collateral_portfolio_id"] for f in self.facilities
                if f["client_id"] == client_id}

    def client_facilities(self, client_id):
        return [f for f in self.facilities if f["client_id"] == client_id]

    def client_notes(self, client_id):
        return sorted((n for n in self.notes if n["client_id"] == client_id),
                      key=lambda n: n["note_date"])

    def client_needs(self, client_id):
        return [r for r in self.cash_needs if r["client_id"] == client_id]

    def client_commitments(self, client_id):
        return [r for r in self.commitments if r["client_id"] == client_id]

    def age(self, client_id):
        """CL-0008 is a family office and has no age. Callers must cope."""
        return _i(self.C[client_id].get("age"))

    def pronoun(self, client_id):
        """(subject, object, possessive) for a sentence about the client, from
        clients.gender. A family office has no gender and is "they". Written
        into finding text, so a rule that says "he" about every client calls
        half the book by the wrong word."""
        return {"M": ("he", "him", "his"),
                "F": ("she", "her", "her")}.get(self.C[client_id].get("gender"),
                                                ("they", "them", "their"))

    def horizon_end(self, client_id, base_year=None):
        yrs = _i(self.C[client_id].get("investment_horizon_years"), 0)
        return (base_year or int(self.today[:4])) + (yrs or 0)


if __name__ == "__main__":
    b = Book()
    print("snapshots        ", ", ".join(b.dates))
    print("clients          ", len(b.clients), "| portfolios", len(b.portfolios),
          "| positions", len(b.holdings), "| notes", len(b.notes))
    print("total wealth     USD %.1fm" % (sum(b.wealth(c) for c in b.C) / 1e6))
    print("stale marks      ", b.stale_marks)
    print("missing age      ", [c for c in b.C if b.age(c) is None])
    print()
    print("look-through derived from underlying_reference:")
    for iid, legs in b.lookthrough.items():
        if b.I[iid]["asset_class"] == "Structured Products":
            print("  %-14s %-46s -> %s" % (
                iid, b.I[iid]["instrument_name"][:45],
                ", ".join("%s%s" % (d, "" if t else " [external]") for d, t in legs) or "(none)"))
    print()
    print("largest single-name exposure, look-through, today:")
    for cid in sorted(b.C):
        agg = b.exposure_by_name(cid)
        if not agg:
            continue
        w = b.wealth(cid)
        top = max(agg.items(), key=lambda kv: kv[1]["usd"])
        print("  %-9s %-24s %-34s %5.1f%%  via %s" % (
            cid, b.C[cid]["client_name"][:23], top[0][:33], 100 * top[1]["usd"] / w,
            ",".join(sorted(top[1]["via"]))))
