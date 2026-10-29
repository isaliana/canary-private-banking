"""
What the money actually did, and what was happening while it did it.

Three questions the dossier could not answer before:

  How has this client done?        Unrealised return on cost, and the change in
                                   wealth across the five snapshots. Two
                                   different numbers, both labelled.
  Which position is responsible?   Every holding's P&L expressed in points of
                                   the same return, so the contributions sum to
                                   the headline exactly.
  Why did it move?                 Events from event_log.csv attributed to the
                                   client's own holdings, by keyword against
                                   `primary_transmission` and by region. Each
                                   attribution carries the instrument it hit and
                                   the word that matched — an event is never
                                   asserted to be "relevant" without saying how.

Nothing here forecasts and nothing here explains a move it cannot evidence. An
event in the window is reported as an event in the window; the dossier says
"three events in this window touch 38% of his holdings", never "wealth fell
because of them".
"""
import re

# transaction_type, grouped by what it means for the client
INCOME = {"Dividend", "Coupon", "Interest", "Distribution"}
COSTS = {"Management Fee", "Interest Charge"}
EXTERNAL = {"Withdrawal", "Transfer In", "Capital Call", "Facility Drawdown",
            "Redemption Request", "Deposit"}

# words that carry no matching power in a transmission phrase
STOP = {"and", "the", "assets", "asset", "linked", "sensitive", "havens", "haven",
        "products", "product", "exposure", "valuations", "hedges", "hedge",
        "structured", "concentrated", "semi", "long", "term"}


def _stem(word):
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _phrases(transmission):
    """'Energy, oil-linked structured products' -> [('Energy', {'energy'}), ...]"""
    out = []
    for phrase in (transmission or "").split(","):
        phrase = phrase.strip()
        if not phrase:
            continue
        words = {_stem(w) for w in re.split(r"[^a-z0-9]+", phrase.lower())
                 if len(w) >= 3 and w not in STOP}
        if words:
            out.append((phrase, words))
    return out


def _haystack(book, iid):
    i = book.I[iid]
    blob = " ".join([i["instrument_name"], i["asset_class"], i["sub_asset_class"],
                     i["sector"], i["region"]]).lower()
    return {_stem(w) for w in re.split(r"[^a-z0-9]+", blob) if w}


_VOCAB = {}


def _vocab(book):
    """Every word the instrument universe actually uses. A transmission word the
    universe has never heard of ("duration", "havens") cannot discriminate, so it
    is dropped; every word that remains must be present for the phrase to match.

    Requiring ALL the surviving words is what stops "European fixed income" from
    landing on a US Treasury through the word "fixed" — which it did, and which
    would have put a European rate rise in a Hong Kong client's timeline."""
    key = id(book)
    if key not in _VOCAB:
        seen = set()
        for iid in book.I:
            seen |= _haystack(book, iid)
        _VOCAB[key] = seen
    return _VOCAB[key]


def attribute(book, cid, event, positions, wealth):
    """Which of this client's holdings does this event plausibly touch, and how
    do we know? Returns None when nothing matches — silence is the honest
    answer for an event that has no route into this portfolio."""
    hits, seen = [], set()
    vocab = _vocab(book)
    phrases = [(phrase, keys & vocab) for phrase, keys in
               _phrases(event["primary_transmission"])]
    phrases = [(phrase, keys) for phrase, keys in phrases if keys]
    region = event["region"]

    for iid, pos in positions.items():
        words = _haystack(book, iid)
        for phrase, keys in phrases:
            if not keys <= words:              # every surviving word must be there
                continue
            if iid in seen:
                break
            seen.add(iid)
            hits.append({"instrument_id": iid, "instrument": book.I[iid]["instrument_name"],
                         "usd": round(pos["mv"]), "via": phrase,
                         "matched": " + ".join(sorted(keys))})
            break
        # a named region is a second route in, weaker than the transmission and
        # labelled as such; "Global" is not a route, it is every event's default
        if iid not in seen and region != "Global" and book.I[iid]["region"] == region:
            seen.add(iid)
            hits.append({"instrument_id": iid, "instrument": book.I[iid]["instrument_name"],
                         "usd": round(pos["mv"]), "via": region, "matched": "region"})

    if not hits:
        return None
    hits.sort(key=lambda h: -h["usd"])
    touched = sum(h["usd"] for h in hits)
    return {
        "date": event["event_date"], "type": event["event_type"],
        "region": region, "severity": event["severity"],
        "description": event["description"],
        "transmission": event["primary_transmission"],
        "hits": hits[:6], "hit_count": len(hits),
        "touched_usd": touched,
        "touched_pct": round(100 * touched / wealth, 1) if wealth else 0.0,
    }


def build(book, cid):
    dates = book.dates
    wealth_now = book.wealth(cid)
    positions = book.positions(cid)

    # ── return on cost ────────────────────────────────────────────────────
    # cost is market value less unrealised P&L, both already in USD, so the
    # per-position contributions sum to the headline by construction
    cost = sum(p["mv"] - p["pnl"] for p in positions.values())
    pnl = sum(p["pnl"] for p in positions.values())
    ret_pct = (100 * pnl / cost) if cost else 0.0

    start_pos = book.positions(cid, dates[0])

    contributors = []
    for iid, p in positions.items():
        c = p["mv"] - p["pnl"]
        contributors.append({
            "instrument_id": iid, "instrument": book.I[iid]["instrument_name"],
            "asset_class": book.I[iid]["asset_class"],
            "market_value_usd": round(p["mv"]),
            "cost_usd": round(c),
            "unrealised_usd": round(p["pnl"]),
            "return_pct": round(100 * p["pnl"] / c, 1) if c else 0.0,
            # points of the client's own return, so these add up to ret_pct
            "contribution_pp": round(100 * p["pnl"] / cost, 2) if cost else 0.0,
            "value_change_usd": round(p["mv"] - start_pos.get(iid, {"mv": 0.0})["mv"]),
            "held_at_start": iid in start_pos,
        })
    contributors.sort(key=lambda c: c["contribution_pp"])

    # ── cash movements recorded in the period ─────────────────────────────
    income = costs = external = 0.0
    for t in book.transactions:
        if t["client_id"] != cid or not (dates[0] <= t["trade_date"] <= book.today):
            continue
        amt = book.to_usd(float(t["amount"] or 0), t["currency"])
        if t["transaction_type"] in INCOME:
            income += amt
        elif t["transaction_type"] in COSTS:
            costs += amt
        elif t["transaction_type"] in EXTERNAL:
            external += amt

    # ── the path, snapshot to snapshot, with what was happening ───────────
    steps = []
    for i in range(1, len(dates)):
        a, b = dates[i - 1], dates[i]
        wa, wb = book.wealth(cid, a), book.wealth(cid, b)
        window = [e for e in book.events if a < e["event_date"] <= b]
        attributed = [x for x in
                      (attribute(book, cid, e, positions, wealth_now) for e in window)
                      if x]
        attributed.sort(key=lambda x: -x["touched_pct"])
        touched = {h["instrument_id"] for x in attributed for h in x["hits"]}
        steps.append({
            "from": a, "to": b,
            "start_usd": round(wa), "end_usd": round(wb),
            "delta_usd": round(wb - wa),
            "delta_pct": round(100 * (wb - wa) / wa, 2) if wa else 0.0,
            "events": attributed,
            "events_in_window": len(window),
            "touched_pct": round(100 * sum(positions[i2]["mv"] for i2 in touched
                                           if i2 in positions) / wealth_now, 1)
                           if wealth_now else 0.0,
        })

    start_w = book.wealth(cid, dates[0])
    return {
        "cost_usd": round(cost),
        "unrealised_usd": round(pnl),
        "return_on_cost_pct": round(ret_pct, 1),
        "start_usd": round(start_w), "end_usd": round(wealth_now),
        "period_change_usd": round(wealth_now - start_w),
        "period_change_pct": round(100 * (wealth_now - start_w) / start_w, 1) if start_w else 0.0,
        "period_from": dates[0], "period_to": book.today,
        "income_usd": round(income), "costs_usd": round(costs),
        "external_usd": round(external),
        "contributors": contributors,
        "steps": steps,
        "mix_series": [{"date": d, "mix": _mix(book, cid, d)} for d in dates],
    }


def _mix(book, cid, date):
    out = {}
    for r in book.rows(cid, date):
        out[r["asset_class"]] = round(out.get(r["asset_class"], 0.0) + r["_mv"])
    return out
