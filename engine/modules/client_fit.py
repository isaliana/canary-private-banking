"""
Does the portfolio fit the life it is funding?

Three findings that need the client's biography and the position in the same
sentence — which is why a statement never shows them.

  purpose_fit    income maturing after the client needs it
  concentration  single-name exposure once you look through the wrappers
  life_event     dated obligations the current allocation was not built for
"""
import re
from schema import Finding
import severity as sv
from severity import Sev
import notes as notes_mod

# Where a client's money came from, mapped to the sector that is the same bet.
SAME_BET = {
    "coal": "Energy", "mining": "Energy", "energy": "Energy", "oil": "Energy",
    "gas": "Energy", "shipping": "Industrials", "maritime": "Industrials",
    "property": "Real Estate", "real estate": "Real Estate", "development": "Real Estate",
    "technology": "Information Technology", "software": "Information Technology",
    "semiconductor": "Information Technology", "agribusiness": "Consumer Staples",
    "palm": "Consumer Staples", "food": "Consumer Staples",
    "pharma": "Health Care", "healthcare": "Health Care", "bank": "Financials",
}

DRAWS_INCOME = ("Retired", "Pre-retirement")


def _same_bet(book, cid, exposure_name, via_ids):
    """Does the largest exposure repeat the source of the client's wealth?"""
    sow = (book.C[cid].get("source_of_wealth") or "").lower()
    sectors = {book.I[i]["sector"] for i in via_ids if i in book.I}
    for word, sector in SAME_BET.items():
        if word not in sow:
            continue
        if sector in sectors or word in exposure_name.lower():
            return word
    return None


def run(book, claims):
    out = []
    for client in book.clients:
        cid = client["client_id"]
        wealth = book.wealth(cid)
        if not wealth:
            continue
        positions = book.positions(cid)

        # ── 1. purpose fit ────────────────────────────────────────────────
        annual = [n for n in book.client_needs(cid)
                  if n["recurrence"] in ("Annual", "Annual instalments")]
        draws = client["life_stage"] in DRAWS_INCOME or bool(annual)
        if draws:
            hz = book.horizon_end(cid)
            sleeve_pct = loss = 0.0
            overshoot = 0
            legs, ladder, biggest = [], [], None
            for iid, pos in positions.items():
                name = book.I[iid]["instrument_name"]
                m = re.search(r"due (\d{4})", name)
                perpetual = "Perpetual" in name
                if not (m or perpetual):
                    continue
                maturity = 9999 if perpetual else int(m.group(1))
                w = 100 * pos["mv"] / wealth
                beyond = maturity > hz
                # the ladder shows the whole income sleeve, so the horizon line
                # has something to cut across
                ladder.append({"instrument": name, "weight_pct": round(w, 2),
                               "maturity": None if perpetual else maturity,
                               "perpetual": perpetual, "beyond": beyond,
                               "market_value_usd": round(pos["mv"]),
                               "unrealised_usd": round(pos["pnl"])})
                if not beyond:
                    continue
                sleeve_pct += w
                loss += min(pos["pnl"], 0.0)
                overshoot = max(overshoot,
                                sv.FIT_PERPETUAL_YEARS if perpetual else maturity - hz)
                legs.append(ladder[-1])
                if biggest is None or w > biggest["weight_pct"]:
                    biggest = legs[-1]
            if sleeve_pct >= sv.FIT_MIN_SLEEVE and loss < 0:
                age = book.age(cid)
                they = book.pronoun(cid)[0]
                refusal = notes_mod.has(claims, cid, "refusal")
                out.append(Finding(
                    id="FIT-%s" % cid, client_id=cid, dimension="purpose_fit",
                    severity=(Sev.of("%.1f%% of wealth maturing past a %d horizon"
                                     % (sleeve_pct, hz),
                                     "sleeve %% x %g" % sv.FIT_PER_PCT,
                                     sleeve_pct * sv.FIT_PER_PCT)
                              .plus("%d years of overshoot x %g" % (overshoot,
                                                                   sv.FIT_PER_YEAR_BEYOND),
                                    overshoot * sv.FIT_PER_YEAR_BEYOND)
                              .cap(sv.FIT_CEILING)),
                    headline="%.1f%% of wealth matures after the horizon it is meant to fund" % sleeve_pct,
                    detail=("%s draws income and has a stated horizon to %d. %.1f%% of total wealth "
                            "sits in income positions maturing after that, USD %.1fm underwater — "
                            "the largest is %s%s.%s" % (
                                client["client_name"], hz, sleeve_pct, abs(loss) / 1e6,
                                biggest["instrument"],
                                " which never matures" if biggest["perpetual"]
                                # the name usually already carries the year
                                else "" if str(biggest["maturity"]) in biggest["instrument"]
                                else ", maturing %d" % biggest["maturity"],
                                (" %s %s %d." % (they.capitalize(),
                                                 "are" if they == "they" else "is", age))
                                if age else "")),
                    action=(("Waiting for these to recover is not a plan %s can outlive. "
                             "Shorten the ladder to match the drawdown." % they)
                            if age and age >= 65
                            else "Match the maturity ladder to the drawdown schedule."),
                    rule_text=("applies when life_stage is Retired or Pre-retirement, or an annual "
                               "cash need exists; sleeve = sum of weights of income positions "
                               "maturing after 2026 + investment_horizon_years, perpetuals counted "
                               "as never; fires at sleeve >= %g%%%% of wealth while underwater"
                               % sv.FIT_MIN_SLEEVE),
                    numbers={"sleeve_pct": round(sleeve_pct, 2), "horizon_end": hz,
                             "unrealised_usd": round(loss), "age": age, "legs": legs,
                             "ladder": sorted(ladder, key=lambda x: x["maturity"] or 9999),
                             "today_year": int(book.today[:4])},
                    source_rows=["clients.%s" % cid] + ["instruments.%s" % i for i in positions],
                    evidence=refusal))

        # ── 2. look-through concentration ─────────────────────────────────
        agg = book.exposure_by_name(cid)
        if agg:
            name, blob = max(agg.items(), key=lambda kv: kv[1]["usd"])
            w = 100 * blob["usd"] / wealth
            via = sorted(blob["via"])
            same = _same_bet(book, cid, name, via)
            sev = Sev.ladder("%s at %.1f%% of wealth, look-through" % (name, w),
                             w, sv.CON_RUNGS, "above")
            if same and w >= 12:
                sev.plus("repeats the source of wealth", sv.CON_SAME_BET_BONUS)
            sev.cap(sv.CON_CEILING)
            if sev.value >= sv.CON_REPORT_AT:
                wrappers = [book.I[i]["instrument_name"] for i in via]
                out.append(Finding(
                    id="CON-%s" % cid, client_id=cid, dimension="concentration", severity=sev,
                    headline="%s is %.1f%% of total wealth" % (name, w),
                    detail=("Across every portfolio, %s reaches %.1f%% of this client's wealth "
                            "through %d holding%s: %s.%s" % (
                                name, w, len(via), "" if len(via) == 1 else "s",
                                "; ".join(wrappers),
                                " The family's wealth came from %s — the portfolio repeats the "
                                "bet rather than diversifying it." % same if same else "")),
                    action=("Show the aggregated figure. It does not appear on any single "
                            "portfolio statement."),
                    rule_text=("single-name exposure aggregated across all portfolios, with "
                               "look-through from instruments.underlying_reference; a worst-of "
                               "basket contributes its full value to every leg, so legs do not "
                               "sum to 100%"),
                    numbers={"weight_pct": round(w, 2), "usd": blob["usd"],
                             "via": via, "same_bet_as_source_of_wealth": same},
                    source_rows=["instruments.%s" % i for i in via],
                    evidence=notes_mod.has(claims, cid, "protected", "refusal", "directed")))

        # ── 3. life events ────────────────────────────────────────────────
        for n in book.client_needs(cid):
            usd = book.to_usd(float(n["amount"]), n["currency"])
            share = 100 * usd / wealth
            if share < 8 and n["certainty"] != "Confirmed":
                continue
            if share < 4:
                continue
            health = notes_mod.has(claims, cid, "health")
            age = book.age(cid)
            sev = (Sev.of("%s %s, %.0f%% of wealth" % (n["currency"],
                                                       "{:,.0f}".format(float(n["amount"])), share),
                          "share of wealth x %g" % sv.LIFE_PER_PCT, share * sv.LIFE_PER_PCT)
                   .plus("recorded as Confirmed",
                         sv.LIFE_CONFIRMED_BONUS if n["certainty"] == "Confirmed" else 0)
                   .plus("a health note is on file", sv.LIFE_HEALTH_BONUS if health else 0)
                   .cap(sv.LIFE_CEILING))
            out.append(Finding(
                id="LIF-%s" % n["need_id"], client_id=cid, dimension="life_event", severity=sev,
                headline="%s — %s %s (%.0f%% of wealth)" % (
                    n["description"], n["currency"],
                    "{:,.0f}".format(float(n["amount"])), share),
                detail=("Due %s%s. %s. Worth USD %.1fm, %.0f%% of total wealth.%s" % (
                    n["due_from"], "" if n["due_to"] == n["due_from"] else " to " + n["due_to"],
                    n["certainty"], usd / 1e6, share,
                    " The client is %d." % age if age and age >= 70 else "")),
                action="Check the allocation actually supports this date, not just the amount.",
                rule_text=("planned_cash_needs converted to USD at the snapshot rate; fires above "
                           "4% of wealth, or 8% when not Confirmed"),
                numbers={"usd": usd, "share_pct": round(share, 2), "currency": n["currency"],
                         "amount": float(n["amount"]), "certainty": n["certainty"],
                         "due_from": n["due_from"], "due_to": n["due_to"],
                         "recurrence": n["recurrence"]},
                source_rows=["planned_cash_needs.%s" % n["need_id"]],
                confidence="high" if n["certainty"] == "Confirmed" else "medium",
                check="" if n["certainty"] == "Confirmed" else
                      "Recorded as '%s' — confirm before building a plan around it." % n["certainty"],
                evidence=health))

        # ── 3b. the objective and the cash-needs row disagree ─────────────
        stated = re.search(r"USD ([\d.]+)m", client.get("objectives", "") or "")
        if stated and annual:
            said = float(stated.group(1)) * 1e6
            recorded = book.to_usd(float(annual[0]["amount"]), annual[0]["currency"])
            if recorded and abs(recorded - said) / recorded > 0.05:
                out.append(Finding(
                    id="CHK-%s" % cid, client_id=cid, dimension="life_event",
                    severity=Sev.of("two sources of truth for the drawdown",
                                    "flat — informs every other number, never leads",
                                    sv.OBJECTIVE_CONFLICT),
                    headline="Stated objective and recorded cash need disagree",
                    detail=("Objectives say USD %.2fm a year; planned_cash_needs records "
                            "USD %.2fm — a %.0f%% gap on the number the whole plan turns on." % (
                                said / 1e6, recorded / 1e6,
                                100 * abs(recorded - said) / recorded)),
                    action="Ask which is right before modelling anything on it.",
                    rule_text="clients.objectives parsed for an annual figure, compared with "
                              "planned_cash_needs where recurrence is Annual",
                    numbers={"objective_usd": said, "recorded_usd": recorded},
                    source_rows=["clients.%s" % cid, "planned_cash_needs.%s" % annual[0]["need_id"]],
                    confidence="check",
                    check="Two sources of truth for the drawdown. The workbench will not pick one."))
    return out


def stale_marks(book, claims):
    """A mark that has not moved for a year is not today's price. Reported as a
    confidence problem, not a risk — it changes how much weight every other
    finding about this client can carry."""
    out = []
    for client in book.clients:
        cid = client["client_id"]
        wealth = book.wealth(cid)
        for iid, pos in book.positions(cid).items():
            marked = book.stale_marks.get(iid)
            if not marked:
                continue
            share = 100 * pos["mv"] / wealth
            if share < sv.STALE_MIN_SHARE:
                continue
            pledged = book.pledged_portfolios(cid)
            collateral = any(r["portfolio_id"] in pledged and r["instrument_id"] == iid
                             for r in book.rows(cid))
            age = ((int(book.today[:4]) - int(marked[:4])) * 12
                   + int(book.today[5:7]) - int(marked[5:7]))
            out.append(Finding(
                id="STA-%s-%s" % (cid, iid), client_id=cid, dimension="data_quality",
                severity=(Sev.of("%.0f%% of wealth priced at a mark from %s" % (share, marked),
                                 "share of wealth x %g" % sv.STALE_PER_PCT,
                                 share * sv.STALE_PER_PCT)
                          .plus("the mark also secures a facility",
                                sv.STALE_COLLATERAL_BONUS if collateral else 0)
                          .cap(sv.STALE_CEILING)),
                headline="%.0f%% of wealth is valued at a price from %s" % (share, marked),
                detail=("%s is marked %s at every snapshot, including today. It is %.1f%% of "
                        "this client's wealth%s. Private marks lagging a quarter is normal; this "
                        "one is %d months old." % (
                            book.I[iid]["instrument_name"], marked, share,
                            " and sits behind a credit facility" if collateral else "", age)),
                action=("Request a current valuation before any decision that depends on this "
                        "number — including the loan-to-value on the facility it secures."
                        if collateral else
                        "Request a current valuation before relying on the total."),
                rule_text=("holdings.valuation_date != holdings.snapshot_date, aggregated per "
                           "client; fires above %g%% of wealth" % sv.STALE_MIN_SHARE),
                numbers={"share_pct": round(share, 2), "marked": marked, "months_old": age,
                         "market_value_usd": round(pos["mv"]), "is_collateral": collateral},
                source_rows=["holdings.%s.%s" % (cid, iid)],
                confidence="check",
                check="Every percentage shown for this client moves if the mark moves."))
    return out


_base_run = run


def run(book, claims):                                    # noqa: F811
    return _base_run(book, claims) + stale_marks(book, claims)
