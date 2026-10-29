"""
Module E. A constrained suggestion, not an optimiser.

The difference matters. An optimiser answers "what is the best portfolio?", which
is a question this dataset cannot support and a client did not ask. This answers a
narrower one an RM actually has to answer on a Monday: *the mandate says equity
must sit under 30% and it is at 54% — what would I actually sell, and what stops
me?* It proposes the smallest set of trades that brings a breached band back
inside its limit, and for every position it does not touch it says which rule
stopped it.

Four constraints, in the order they bind:

  liquidity   sell only `liquidity_tier = Daily`. A quarterly-dealing fund is not
              a source of a Monday trade whatever its market value says.
  gated       and not even a Daily fund the RM has recorded as gated — CL-0008's
              private credit manager has gated two consecutive quarters, which
              the liquidity_tier column does not know.
  protected   never a position the notes protect. CL-0005's Rimba Lestari holding
              is a family asset from her father's estate; proposing its sale is
              how an RM stops trusting the tool.
  collateral  never take a pledged portfolio past its margin trigger. Selling
              collateral removes lending value; buying it back adds some in. The
              switch is modelled as one movement, because that is what it is.

Exclusions cut the other way: an instrument on the mandate's own exclusion list is
sold FIRST, ahead of everything else, because it should never have been there.

The output is a plan attached to the mandate finding that motivated it, not a
finding of its own. A client with one band breach should not be ranked as if they
had two problems — severity dominates and count is only a tiebreak, and inflating
the count is exactly how a discretionary compliance breach got buried at rank ten
once before.
"""
import re

import notes as notes_mod

MIN_TRADE_USD = 25_000        # below this the trade costs more than it corrects
STOPWORDS = {"fund", "the", "ltd", "limited", "inc", "plc", "index", "equity",
             "bond", "global", "position", "stake", "holding", "shareholding"}


def _keywords(name):
    """The words in an instrument name that could identify it in a sentence."""
    return {w for w in re.split(r"[^a-z0-9]+", name.lower())
            if len(w) > 3 and w not in STOPWORDS}


def _named_in(book, cid, quote):
    """Which of this client's instruments a note is talking about.

    "The Rimba Lestari position is a family holding" resolves to Rimba Lestari
    Plantations Bhd. "He would rather wait for the bonds to come back" resolves to
    nothing, and that is the honest answer — the plan carries the claim as an
    unresolved warning rather than guessing which line it meant."""
    q = quote.lower()
    out = []
    for iid in book.positions(cid):
        keys = _keywords(book.I[iid]["instrument_name"])
        if keys and any(re.search(r"\b%s" % re.escape(k), q) for k in keys):
            out.append(iid)
    return out


def binding_exclusions(book, code):
    """Does this mandate carry an exclusion list at all? The same test the
    governance rule uses. Without one, sustainability_excluded is a property of
    the instrument, not a breach — a growth mandate holding a commodity index
    has nothing to sell "first", and saying it is on "the mandate's own
    exclusion list" would be untrue."""
    return "excl" in book.mandate_notes.get(code, "").lower() or code == "SUSBAL"


def _lend_ratio(book, pid, iid):
    """Lending value per unit of market value for this holding, 0 if it carries
    no advance rate at all."""
    rows = [r for r in book.portfolio_rows(pid) if r["instrument_id"] == iid]
    mv = sum(r["_mv_base"] for r in rows)
    return (sum(r["_lend_base"] for r in rows) / mv) if mv else 0.0


def _ltv_after(book, facility, delta_usd_by_ratio):
    """LTV once a set of switches has settled.

    `delta_usd_by_ratio` is [(signed USD market value, lending ratio)] — sells
    negative, buys positive. Lending value moves with the ratio, not with the
    market value, which is trap 3: an advance rate of 0% means selling an
    illiquid alternative frees no borrowing capacity at all."""
    lv = float(facility["lending_value_" + book.today])
    drawn = float(facility["drawn_" + book.today])
    rate = book.fx[book.today][facility["facility_ccy"]]
    change = sum((usd / rate) * ratio for usd, ratio in delta_usd_by_ratio)
    new_lv = lv + change
    return {
        "facility": facility["facility_id"],
        "currency": facility["facility_ccy"],
        "trigger_pct": float(facility["margin_call_ltv_pct"]),
        "ltv_before_pct": round(100 * drawn / lv, 1) if lv else None,
        "ltv_after_pct": round(100 * drawn / new_lv, 1) if new_lv > 0 else None,
        "lending_value_before": round(lv),
        "lending_value_after": round(new_lv),
    }


def _headroom_usd(book, facility, ratio):
    """How much market value at this lending ratio can leave the collateral pool
    before LTV reaches the trigger."""
    if ratio <= 0:
        return float("inf")               # frees no lending value, so unconstrained
    lv = float(facility["lending_value_" + book.today])
    drawn = float(facility["drawn_" + book.today])
    trigger = float(facility["margin_call_ltv_pct"])
    room_local = lv - (100 * drawn / trigger)
    if room_local <= 0:
        return 0.0
    return (room_local / ratio) * book.fx[book.today][facility["facility_ccy"]]


def _guards(book, claims, cid):
    """instrument -> the claim that protects it, plus the claims that name nothing
    the engine could resolve."""
    guard, unresolved = {}, []
    for c in notes_mod.has(claims, cid, "protected", "refusal", "gated"):
        hits = _named_in(book, cid, c["quote"])
        if hits:
            for iid in hits:
                guard.setdefault(iid, c)
        else:
            unresolved.append(c)
    return guard, unresolved


def _stopped_by(inst, iid, guard):
    """The first constraint that bites, or None. Order matters: an instrument that
    cannot be dealt is not a trade whatever else is true of it."""
    if inst["liquidity_tier"] != "Daily":
        return ("liquidity", "%s dealing, not daily — this is not a Monday trade"
                % inst["liquidity_tier"])
    if iid in guard and guard[iid]["type"] == "gated":
        return ("gated", "the RM has recorded this as gated, whatever the "
                         "liquidity tier says")
    if iid in guard:
        return ("protected", guard[iid]["meaning"])
    return None


def _allocate_buys(book, pid, code, rows, total, raised):
    """Proceeds go to whichever classes sit below their own band, largest gap
    first, and into something already held."""
    mix = {}
    for r in rows:
        mix[r["asset_class"]] = mix.get(r["asset_class"], 0.0) + r["_mv"]
    under = []
    for cls, (clo, ctgt, chi) in book.bands.get(code, {}).items():
        w = 100 * mix.get(cls, 0.0) / total if total else 0.0
        if w < clo:
            under.append((cls, (clo - w) / 100.0 * total))

    buys, left = [], raised
    for cls, room in sorted(under, key=lambda x: -x[1]):
        if left <= MIN_TRADE_USD:
            break
        amount = min(room, left)
        into = _buy_candidate(book, pid, cls)
        buys.append({"asset_class": cls, "usd": round(amount),
                     "into": into["instrument"] if into else None,
                     "instrument_id": into["iid"] if into else None,
                     "lend_ratio": into["ratio"] if into else 0.0,
                     "note": "" if into else
                             "no existing holding in this class — the buy needs an "
                             "instrument decision, which is not a rule's to make"})
        left -= amount
    if left > MIN_TRADE_USD:
        buys.append({"asset_class": "Cash and Equivalents", "usd": round(left),
                     "into": None, "instrument_id": None, "lend_ratio": 0.0,
                     "note": "held as cash until the review decides where it goes"})
    return buys


def _collateral_effect(book, cid, pid, sells, buys):
    facility = next((f for f in book.client_facilities(cid)
                     if f["collateral_portfolio_id"] == pid), None)
    if not facility:
        return None
    deltas = [(-s["usd"], s["lend_ratio"]) for s in sells]
    deltas += [(b["usd"], b["lend_ratio"]) for b in buys]
    return _ltv_after(book, facility, deltas)


def plan_for_exclusion(book, claims, finding):
    """A binding exclusion is not a band. There is no amount that makes holding it
    acceptable, so the trade is the whole position — and the constraints can only
    delay it, never cancel it. A blocked exclusion becomes an escalation. One
    plan covers every excluded holding in the portfolio, as one finding does."""
    pid = finding.source_rows[0].split(".")[1]
    cid, p = finding.client_id, book.P[pid]
    rows = book.portfolio_rows(pid)
    total = sum(r["_mv"] for r in rows)
    guard, unresolved = _guards(book, claims, cid)

    sells, blocked, held_total, classes = [], [], 0.0, []
    for h in finding.numbers["holdings"]:
        iid = h["instrument_id"]
        held = sum(r["_mv"] for r in rows if r["instrument_id"] == iid)
        if not held:
            continue
        held_total += held
        inst = book.I[iid]
        classes.append(inst["asset_class"])
        stop = _stopped_by(inst, iid, guard)
        if stop:
            blocked.append({"instrument_id": iid, "instrument": inst["instrument_name"],
                            "usd": round(held), "excluded": True, "constraint": stop[0],
                            "why": stop[1] + " — but the exclusion is binding, so this is "
                                             "an escalation, not a reason to leave it",
                            "quote": guard[iid]["quote"] if iid in guard else "",
                            "note_id": guard[iid]["note_id"] if iid in guard else ""})
        else:
            sells.append({"instrument_id": iid, "instrument": inst["instrument_name"],
                          "usd": round(held), "of_position_pct": 100.0,
                          "lend_ratio": _lend_ratio(book, pid, iid), "excluded": True,
                          "reason": "on the mandate's own exclusion list — there is no "
                                    "weight at which holding it is inside the mandate",
                          "capped_by": None})
    if not held_total:
        return None

    raised = sum(s["usd"] for s in sells)
    buys = _allocate_buys(book, pid, p["mandate_code"], rows, total, raised)
    return {"kind": "exit", "portfolio": pid, "mandate": p["mandate_code"],
            "mandate_name": p["mandate_name"], "service_model": p["service_model"],
            "asset_class": classes[0] if len(set(classes)) == 1 else "several classes",
            "weight_pct": round(100 * held_total / total, 2) if total else 0.0,
            "band": None, "target_pct": 0.0, "portfolio_usd": round(total),
            "excess_usd": round(held_total), "raised_usd": round(raised),
            "shortfall_usd": round(held_total - raised), "weight_after_pct": 0.0,
            "sells": sells, "blocked": blocked, "buys": buys,
            "collateral": _collateral_effect(book, cid, pid, sells, buys),
            "unresolved_claims": unresolved, "min_trade_usd": MIN_TRADE_USD}


def plan_for_limit(book, claims, finding):
    """A single-position limit is a haircut on one named holding, not a class."""
    pid = finding.source_rows[0].split(".")[1]
    iid = finding.source_rows[0].split(".")[2]
    cid, p = finding.client_id, book.P[pid]
    rows = book.portfolio_rows(pid)
    total = sum(r["_mv"] for r in rows)
    held = sum(r["_mv"] for r in rows if r["instrument_id"] == iid)
    limit = finding.numbers.get("limit_pct")
    if not held or not total or limit is None:
        return None
    trim = held - (limit / 100.0) * total
    if trim <= MIN_TRADE_USD:
        return None
    inst = book.I[iid]
    guard, unresolved = _guards(book, claims, cid)
    stop = _stopped_by(inst, iid, guard)

    sells, blocked, capped = [], [], None
    if stop:
        blocked.append({"instrument_id": iid, "instrument": inst["instrument_name"],
                        "usd": round(trim), "excluded": False, "constraint": stop[0],
                        "why": stop[1], "quote": guard[iid]["quote"] if iid in guard else "",
                        "note_id": guard[iid]["note_id"] if iid in guard else ""})
    else:
        ratio = _lend_ratio(book, pid, iid)
        facility = next((f for f in book.client_facilities(cid)
                         if f["collateral_portfolio_id"] == pid), None)
        size = trim
        if facility:
            room = _headroom_usd(book, facility, ratio)
            if size > room:
                size, capped = max(0.0, room), "collateral"
        if size < MIN_TRADE_USD:
            blocked.append({"instrument_id": iid, "instrument": inst["instrument_name"],
                            "usd": round(trim), "excluded": False,
                            "constraint": "collateral",
                            "why": "trimming it would take %s past its %s%% margin trigger"
                                   % (facility["facility_id"], facility["margin_call_ltv_pct"]),
                            "quote": "", "note_id": ""})
        else:
            sells.append({"instrument_id": iid, "instrument": inst["instrument_name"],
                          "usd": round(size), "of_position_pct": round(100 * size / held, 1),
                          "lend_ratio": ratio, "excluded": False,
                          "reason": "trimmed to the %s%% single-position cap" % limit,
                          "capped_by": capped})

    raised = sum(s["usd"] for s in sells)
    buys = _allocate_buys(book, pid, p["mandate_code"], rows, total, raised)
    return {"kind": "trim", "portfolio": pid, "mandate": p["mandate_code"],
            "mandate_name": p["mandate_name"], "service_model": p["service_model"],
            "asset_class": inst["asset_class"],
            "weight_pct": finding.numbers.get("weight_pct"), "band": [0, limit],
            "target_pct": limit, "portfolio_usd": round(total),
            "excess_usd": round(trim), "raised_usd": round(raised),
            "shortfall_usd": round(max(0.0, trim - raised)),
            "weight_after_pct": round(100 * (held - raised) / total, 1),
            "sells": sells, "blocked": blocked, "buys": buys,
            "collateral": _collateral_effect(book, cid, pid, sells, buys),
            "unresolved_claims": unresolved, "min_trade_usd": MIN_TRADE_USD}


def plan_for(book, claims, finding):
    """One mandate band breach -> what to do about it, and what stops each trade."""
    n = finding.numbers
    pid = finding.source_rows[0].split(".")[1]
    cid = finding.client_id
    p = book.P[pid]
    code = p["mandate_code"]
    rows = book.portfolio_rows(pid)
    total = sum(r["_mv"] for r in rows)
    asset = finding.headline.split(" is ")[0]
    if not total or asset not in book.bands.get(code, {}):
        return None

    lo, tgt, hi = book.bands[code][asset]
    weight = n["weight_pct"]
    over = weight > hi

    # Proceeds are reinvested inside the same portfolio, so the denominator does
    # not move and the trim is a straight percentage of the portfolio.
    excess_usd = abs(weight - (hi if over else lo)) / 100.0 * total

    # ── who is protected, and by what ──────────────────────────────────────
    guard, unresolved = _guards(book, claims, cid)

    facility = next((f for f in book.client_facilities(cid)
                     if f["collateral_portfolio_id"] == pid), None)

    if not over:
        # An under-weight band is corrected by buying, not selling. Say the
        # amount and leave the instrument to the RM — inventing one would be the
        # model choosing a security, which is not this product's job.
        return {"kind": "buy", "portfolio": pid, "mandate": code,
                "mandate_name": p["mandate_name"], "service_model": p["service_model"],
                "asset_class": asset, "weight_pct": weight, "band": [lo, hi],
                "target_pct": tgt, "portfolio_usd": round(total),
                "excess_usd": round(excess_usd), "raised_usd": 0,
                "shortfall_usd": round(excess_usd),
                "weight_after_pct": weight,
                "sells": [], "blocked": [], "buys": [], "collateral": None,
                "unresolved_claims": unresolved, "min_trade_usd": MIN_TRADE_USD,
                "note": "%s sits below its %s band. Correcting it is a purchase of "
                        "about USD %.1fm; the instrument is a decision for the review, "
                        "not for a rule." % (asset, code, excess_usd / 1e6)}

    # ── candidates, worst first ────────────────────────────────────────────
    holdings = {}
    for r in rows:
        if r["asset_class"] != asset:
            continue
        h = holdings.setdefault(r["instrument_id"], {"usd": 0.0})
        h["usd"] += r["_mv"]

    binding = binding_exclusions(book, code)

    def is_excluded(inst):
        return binding and inst["sustainability_excluded"] == "Y"

    def rank(item):
        iid, h = item
        return (0 if is_excluded(book.I[iid]) else 1, -h["usd"])

    sells, blocked, raised = [], [], 0.0
    for iid, h in sorted(holdings.items(), key=rank):
        inst = book.I[iid]
        excluded = is_excluded(inst)
        remaining = excess_usd - raised
        if remaining <= MIN_TRADE_USD and not excluded:
            break

        stop = _stopped_by(inst, iid, guard)

        if stop:
            blocked.append({
                "instrument_id": iid, "instrument": inst["instrument_name"],
                "usd": round(h["usd"]), "excluded": excluded,
                "constraint": stop[0], "why": stop[1],
                "quote": guard[iid]["quote"] if iid in guard else "",
                "note_id": guard[iid]["note_id"] if iid in guard else "",
            })
            continue

        size = h["usd"] if excluded else min(h["usd"], remaining)
        ratio = _lend_ratio(book, pid, iid)
        capped_by = None
        if facility:
            room = _headroom_usd(book, facility, ratio) - sum(
                s["usd"] for s in sells if s["lend_ratio"] > 0)
            if size > room:
                size, capped_by = max(0.0, room), "collateral"
        if size < MIN_TRADE_USD:
            blocked.append({
                "instrument_id": iid, "instrument": inst["instrument_name"],
                "usd": round(h["usd"]), "excluded": excluded,
                "constraint": capped_by or "size",
                "why": ("selling it would take %s past its %s%% margin trigger"
                        % (facility["facility_id"], facility["margin_call_ltv_pct"]))
                       if capped_by else "below the minimum trade size",
                "quote": "", "note_id": "",
            })
            continue

        sells.append({
            "instrument_id": iid, "instrument": inst["instrument_name"],
            "usd": round(size), "of_position_pct": round(100 * size / h["usd"], 1),
            "lend_ratio": ratio, "excluded": excluded,
            "reason": ("on the mandate's own exclusion list — sold in full, ahead of "
                       "everything else" if excluded else
                       "largest daily-liquid holding in the breaching class"),
            "capped_by": capped_by,
        })
        raised += size

    # ── where the proceeds go ──────────────────────────────────────────────
    buys = _allocate_buys(book, pid, code, rows, total, raised)
    ltv = _collateral_effect(book, cid, pid, sells, buys)

    return {
        "kind": "sell", "portfolio": pid, "mandate": code,
        "mandate_name": p["mandate_name"], "service_model": p["service_model"],
        "asset_class": asset, "weight_pct": weight, "band": [lo, hi],
        "target_pct": tgt, "portfolio_usd": round(total),
        "excess_usd": round(excess_usd), "raised_usd": round(raised),
        "shortfall_usd": round(max(0.0, excess_usd - raised)),
        "weight_after_pct": round(weight - 100 * raised / total, 1),
        "sells": sells, "blocked": blocked, "buys": buys,
        "collateral": ltv, "unresolved_claims": unresolved,
        "min_trade_usd": MIN_TRADE_USD,
    }


def _buy_candidate(book, pid, asset_class):
    """An existing holding in the under-weight class: the largest daily-liquid one
    that is not itself excluded. Adding to something already held is a smaller
    decision than introducing a new security."""
    best = None
    for r in book.portfolio_rows(pid):
        inst = book.I[r["instrument_id"]]
        if (r["asset_class"] != asset_class or inst["liquidity_tier"] != "Daily"
                or inst["sustainability_excluded"] == "Y"):
            continue
        if best is None or r["_mv"] > best["usd"]:
            best = {"iid": r["instrument_id"], "instrument": inst["instrument_name"],
                    "usd": r["_mv"], "ratio": _lend_ratio(book, pid, r["instrument_id"])}
    return best


def build(book, claims, findings):
    """{finding id -> plan} for every open asset-class band breach."""
    out = {}
    route = {"MAN-": plan_for, "EXC-": plan_for_exclusion, "LIM-": plan_for_limit}
    for f in findings:
        fn = route.get(f.id[:4])
        if fn is None or f.status == "waived":
            continue
        try:
            p = fn(book, claims, f)
        except (KeyError, IndexError, ValueError):
            p = None
        if p:
            out[f.id] = p
    return out
