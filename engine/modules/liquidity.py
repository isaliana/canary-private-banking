"""
Collateral and funding feasibility.

The finding that needs both: for a client with a Lombard facility, selling the
liquid assets to raise cash destroys the lending value supporting the loan.
Liquidity and credit have to be solved together or the answer is wrong.
"""
from schema import Finding
import severity as sv
import upcoming
from severity import Sev
import notes as notes_mod

HORIZON_MONTHS = 12


def _needs(book, cid, horizon_date):
    """Cash needs and the capital calls whose window opens inside the horizon,
    converted to USD. They are quoted in local currency; summing the raw column
    is the first mistake to make."""
    total, detail = 0.0, []
    # A cash-needs row can restate the uncalled commitments rather than add to
    # them — "Outstanding private markets commitments" written as a cash need is
    # the sum of the uncalled funds, not something on top. Counting both doubles
    # the obligation.
    restates_commitments = any(
        "commitment" in r["description"].lower() for r in book.client_needs(cid))
    for r in book.client_needs(cid):
        if r["certainty"] == "Aspirational" or r["due_from"] > horizon_date:
            continue
        usd = book.to_usd(float(r["amount"]), r["currency"])
        total += usd
        detail.append({"what": r["description"], "ccy": r["currency"],
                       "need_id": r["need_id"],
                       "amount": float(r["amount"]), "usd": usd,
                       "certainty": r["certainty"], "recurrence": r["recurrence"],
                       "due_from": r["due_from"], "due_to": r["due_to"]})
    for r in book.client_commitments(cid):
        # the window opens at the start of its first quarter; a call window that
        # opens after the horizon is not money owed inside it
        if restates_commitments or upcoming.window_start(r["expected_call_window"]) > horizon_date:
            continue
        usd = book.to_usd(float(r["uncalled"]), r["currency"])
        total += usd
        detail.append({"what": "Uncalled: " + r["fund_name"], "ccy": r["currency"],
                       "amount": float(r["uncalled"]), "usd": usd,
                       "certainty": "Contractual", "recurrence": "Capital call",
                       "due_from": r["expected_call_window"], "due_to": ""})
    return total, detail


def cover_report(book, cid):
    """Why the funding rule is silent for most of the book — with the arithmetic.

    A finding that does not fire leaves nothing on the screen, and an RM cannot
    tell "covered" from "nobody looked". A client who owes a few hundred thousand
    in school fees against tens of millions of daily-liquid assets leaves the rule
    quiet at a hundred times cover, which is right, but the silence should be
    legible. So every dated obligation gets its cover here whether or not it ever
    becomes a finding.

    Per-need cover is against the client's whole daily-liquid pool, so the rows
    do not sum — a client can be comfortable against each obligation and short
    against all of them. The aggregate is reported alongside and is the one the
    rule actually uses."""
    horizon = "%d%s" % (int(book.today[:4]) + 1, book.today[4:])
    daily = book.daily_liquid(cid)
    wealth = book.wealth(cid)
    total, _ = _needs(book, cid, horizon)
    cover = (daily / total) if total else None

    def status(c, within):
        if not within:
            return "Beyond 12 months"
        if c is None:
            return "No amount recorded"
        return ("Not covered" if c < 1 else "Tight" if c < 1.5
                else "Watch" if c < 3 else "Covered")

    rows = []
    for r in book.client_needs(cid):
        if r["certainty"] == "Aspirational":
            continue
        usd = book.to_usd(float(r["amount"]), r["currency"])
        nxt = upcoming.next_occurrence(r, book.today) or r["due_from"]
        c = (daily / usd) if usd else None
        rows.append({
            "need_id": r["need_id"], "description": r["description"],
            "currency": r["currency"], "amount": float(r["amount"]),
            "usd": round(usd), "next_due": nxt, "first_due": r["due_from"],
            "recurrence": r["recurrence"], "certainty": r["certainty"],
            "share_pct": round(100 * usd / wealth, 2) if wealth else 0.0,
            "cover_x": round(c, 1) if c else None,
            "status": status(c, r["due_from"] <= horizon),
        })
    rows.sort(key=lambda x: x["next_due"])

    sev = _funding_severity(cover)
    return {
        "horizon": horizon,
        "need_12m_usd": round(total),
        "daily_liquid_usd": round(daily),
        "cover_x": round(cover, 1) if cover else None,
        "severity": round(sev, 1),
        "reported": sev >= sv.FUNDING_REPORT_AT,
        "report_at": sv.FUNDING_REPORT_AT,
        "needs": rows,
    }


def _funding_severity(cover):
    """The same ladder the rule uses, so the dossier and the finding cannot
    drift apart."""
    if cover is None:
        return 0.0
    return Sev.ladder("cover", cover, sv.FUNDING_RUNGS, "below").value


def _fmt(v, ccy):
    v = abs(float(v))
    return "%s %.1fm" % (ccy, v / 1e6) if v >= 1e6 else "%s %s" % (ccy, "{:,.0f}".format(v))


def _funding_chart(f, need_local, free_usd, dmv, dlv, released, repay,
                   lv, drawn, trigger, post_ltv, book):
    """The six numbers that carry the whole funding story, in the currency the
    client actually owes, plus the loan-to-value they produce.

    Emitted here rather than assembled in the browser: these are figures, and a
    figure in the workbench comes out of engine/ or it does not appear. The tick
    unit is chosen here too, so the chart's own scale is a published number."""
    ccy = f["facility_ccy"]
    rate = book.fx[book.today][ccy]
    rows = [
        {"label": "Owed", "amount": round(need_local), "tone": "alert",
         "note": "confirmed, and dated"},
        {"label": "Free of any pledge", "amount": round(free_usd * rate), "tone": "data",
         "note": "spent first, before any collateral is sold" if free_usd > 0 else
                 "nothing sits outside the pledged account — the routing test has "
                 "only one answer"},
        {"label": "Daily-sellable collateral", "amount": round(dmv), "tone": "data",
         "note": "market value, which is the number a statement shows"},
        {"label": "...its lending value", "amount": round(dlv), "tone": "data",
         "note": "after per-asset advance rates. This is the number the loan runs on"},
        {"label": "Released by the sale", "amount": round(released), "tone": "data",
         "note": "selling the collateral takes its borrowing capacity with it"},
        {"label": "Must repay first", "amount": round(repay), "tone": "alert",
         "note": "to keep the facility inside its trigger through the sale"},
    ]
    top = max(r["amount"] for r in rows) or 1
    unit = next((u for u in (1e5, 2.5e5, 5e5, 1e6, 2e6, 5e6, 1e7, 2.5e7)
                 if top / u <= 46), 5e7)
    return {"currency": ccy, "unit": unit, "rows": rows,
            "ltv": {"before_pct": round(100 * drawn / lv, 1) if lv else None,
                    "after_pct": round(post_ltv, 1) if post_ltv < 1e4 else None,
                    "trigger_pct": trigger}}


def run(book, claims):
    out = []
    horizon = "%d%s" % (int(book.today[:4]) + 1, book.today[4:])

    for client in book.clients:
        cid = client["client_id"]
        they = book.pronoun(cid)[0]
        pledged = book.pledged_portfolios(cid)
        facilities = book.client_facilities(cid)

        # ── 1. collateral headroom ────────────────────────────────────────
        for f in facilities:
            trigger = float(f["margin_call_ltv_pct"])
            path = [(d, float(f["ltv_pct_" + d])) for d in book.dates]
            now = path[-1][1]
            peak = max(v for _, v in path)
            headroom = trigger - now
            breached = [d for d, v in path if v >= trigger]
            sev = Sev.ladder("%.1fpp of headroom to a %.0f%% trigger" % (headroom, trigger),
                             headroom, sv.COLLATERAL_RUNGS, "below")
            if breached:
                sev.floor("breached on " + ", ".join(breached), sv.COLLATERAL_BREACH_FLOOR)
            if sev.value < sv.COLLATERAL_REPORT_AT and not breached:
                continue
            out.append(Finding(
                id="COL-%s" % f["facility_id"],
                client_id=cid, dimension="collateral", severity=sev,
                headline="%s is at %.1f%% LTV against a %.0f%% margin trigger" % (
                    f["facility_id"], now, trigger),
                detail=("%s %s %.1fm drawn against lending value of %s %.1fm. "
                        "LTV ran %s across the five snapshots%s." % (
                            f["facility_type"], f["facility_ccy"],
                            float(f["drawn_" + book.today]) / 1e6, f["facility_ccy"],
                            float(f["lending_value_" + book.today]) / 1e6,
                            " → ".join("%.1f%%" % v for _, v in path),
                            ", breaching on " + ", ".join(breached) if breached else "")),
                action=("Already breached during the period — check whether it was cured by an "
                        "action or only by the market." if breached else
                        "Thin headroom. Any collateral sale or drawdown needs checking first."),
                rule_text=("ltv = drawn / lending_value, where lending value is market value "
                           "after per-asset advance-rate haircuts, not raw market value; "
                           "trigger is credit_facilities.margin_call_ltv_pct"),
                numbers={"ltv_pct": now, "trigger_pct": trigger, "peak_pct": peak,
                         "headroom_pp": round(headroom, 2),
                         "drawn": float(f["drawn_" + book.today]),
                         "currency": f["facility_ccy"],
                         "path": [{"date": d, "ltv": v} for d, v in path]},
                source_rows=["credit_facilities.%s" % f["facility_id"],
                             "portfolios.%s" % f["collateral_portfolio_id"]],
                evidence=notes_mod.has(claims, cid, "directed", "escalate")))

        # ── 2. funding feasibility ────────────────────────────────────────
        need, detail = _needs(book, cid, horizon)
        if need <= 0:
            continue
        wealth = book.wealth(cid)
        free = book.daily_liquid(cid, exclude_portfolios=pledged)
        shortfall = max(0.0, need - free)
        blocked, note, post = False, "", None

        for f in facilities:
            if shortfall <= 0:
                break
            rows = book.portfolio_rows(f["collateral_portfolio_id"])
            dmv = sum(r["_mv_base"] for r in rows if r["liquidity_tier"] == "Daily")
            dlv = sum(r["_lend_base"] for r in rows if r["liquidity_tier"] == "Daily")
            if dmv <= 0:
                continue
            lv = float(f["lending_value_" + book.today])
            drawn = float(f["drawn_" + book.today])
            trigger = float(f["margin_call_ltv_pct"])
            local = shortfall / book.fx[book.today][f["facility_ccy"]]
            released = min(local, dmv) * (dlv / dmv)
            new_lv = lv - released
            post_ltv = (100 * drawn / new_lv) if new_lv > 0 else float("inf")
            if post_ltv >= trigger:
                blocked = True
                repay = drawn - trigger / 100 * new_lv
                # The repayment is not the shortfall, and that is the whole
                # confusion: it is how far the existing debt overshoots what the
                # *shrunken* collateral pool can carry at the trigger. Every
                # intermediate value is emitted so the workbench can show the
                # derivation instead of asserting the total — a number an RM
                # cannot take apart is a number she cannot defend.
                post = {"facility": f["facility_id"], "post_ltv_pct": round(post_ltv, 1),
                        "trigger_pct": trigger, "released": released,
                        "repay_first": max(0.0, repay), "currency": f["facility_ccy"],
                        "daily_mv": dmv, "daily_lending_value": dlv,
                        "steps": [
                            {"label": "Drawn on %s today" % f["facility_id"],
                             "value": round(drawn), "op": ""},
                            {"label": "Lending value behind it",
                             "value": round(lv), "op": "",
                             "note": "LTV %.1f%%, against a %g%% trigger"
                                     % (100 * drawn / lv if lv else 0, trigger)},
                            {"label": "To raise, by selling daily-liquid collateral",
                             "value": round(local), "op": ""},
                            {"label": "Lending value that sale removes",
                             "value": -round(released), "op": "−",
                             "note": "%s of market value at a %.1f%% average advance rate"
                                     % (_fmt(local, f["facility_ccy"]), 100 * dlv / dmv)},
                            {"label": "Lending value left afterwards",
                             "value": round(new_lv), "op": "=",
                             "note": "the debt has not moved, so LTV becomes %.1f%%"
                                     % post_ltv},
                            {"label": "Most %s may owe at the %g%% trigger" % (they, trigger),
                             "value": round(trigger / 100 * new_lv), "op": "×",
                             "note": "%g%% of %s" % (trigger, _fmt(new_lv, f["facility_ccy"]))},
                            {"label": "So %s must repay first" % they,
                             "value": round(max(0.0, repay)), "op": "=",
                             "note": "%s owed less %s allowed"
                                     % (_fmt(drawn, f["facility_ccy"]),
                                        _fmt(trigger / 100 * new_lv, f["facility_ccy"]))},
                        ],
                        "chart": _funding_chart(f, local, free, dmv, dlv, released,
                                                max(0.0, repay), lv, drawn, trigger,
                                                post_ltv, book)}
                note = ("Selling the daily-liquid collateral to raise %s %.1fm releases %s %.1fm "
                        "of lending value, taking %s from %.1f%% to %s. %s would have to repay "
                        "about %s %.1fm first." % (
                            f["facility_ccy"], local / 1e6, f["facility_ccy"], released / 1e6,
                            f["facility_id"], 100 * drawn / lv,
                            "%.0f%%" % post_ltv if post_ltv < 1e4 else "a full margin call",
                            they.capitalize(), f["facility_ccy"], max(0.0, repay) / 1e6))

        total_daily = book.daily_liquid(cid)
        cover = total_daily / need if need else 99.0
        sev = (Sev.of("funding the need would trip a margin trigger",
                      "the sale itself causes the call", sv.FUNDING_BLOCKED) if blocked
               else Sev.ladder("%.1fx cover on a USD %.1fm need" % (cover, need / 1e6),
                               cover, sv.FUNDING_RUNGS, "below"))
        if sev.value < sv.FUNDING_REPORT_AT:
            continue
        confirmed = [d for d in detail if d["certainty"] in ("Confirmed", "Contractual")]
        out.append(Finding(
            id="FUN-%s" % cid, client_id=cid, dimension="funding", severity=sev,
            headline=("The portfolio cannot fund what has been promised without a margin call"
                      if blocked else
                      "USD %.1fm due within 12 months against USD %.1fm sellable" % (
                          need / 1e6, total_daily / 1e6)),
            detail=(("USD %.1fm falls due within twelve months against USD %.1fm sellable at "
                     "daily liquidity, of which USD %.1fm sits outside any pledged portfolio. " % (
                         need / 1e6, total_daily / 1e6, free / 1e6)) +
                    (note if blocked else
                     "Cover is %.1f times the requirement." % cover)),
            action=("Repay the facility before any sale, or fund this outside the portfolio. "
                    "'Sell some liquid assets' triggers the margin call." if blocked else
                    "Plan the funding path now rather than at the call date."),
            rule_text=("need = cash needs due <= 12m + uncalled commitments whose call window "
                       "opens <= 12m, each converted "
                       "to USD at the snapshot rate; unpledged daily liquidity is spent first; "
                       "only the shortfall releases lending value, and blocked when "
                       "drawn / (lending_value - released) >= margin_call_ltv_pct. "
                       "repay_first = drawn - margin_call_ltv_pct/100 x "
                       "(lending_value - released)"),
            numbers={"need_usd": need, "free_unpledged_usd": free,
                     "daily_liquid_usd": book.daily_liquid(cid), "wealth_usd": wealth,
                     "cover": round(cover, 2), "blocked": blocked,
                     "collateral": post, "items": detail,
                     "need_ids": [d["need_id"] for d in detail if d.get("need_id")]},
            source_rows=["planned_cash_needs.%s" % cid, "commitments.%s" % cid,
                         "market_context.FX.%s" % book.today],
            confidence="high" if all(d["certainty"] in ("Confirmed", "Contractual")
                                     for d in detail) else "medium",
            check=("" if all(d["certainty"] in ("Confirmed", "Contractual") for d in detail)
                   else "Some of this is Likely rather than Confirmed — %d of %d items. "
                        "Confirm timing before acting." % (len(confirmed), len(detail))),
            evidence=notes_mod.has(claims, cid, "awareness_gap", "open_item")))
    return out
