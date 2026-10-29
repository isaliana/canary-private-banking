"""
Mandate and suitability governance.

Three tests, and then the part that makes this advisory rather than compliance:
every breach is classified as drift, client-directed, or waived, from the notes.
A waived breach is suppressed from the action list and shown as governed — a
tool that cries wolf on a breach the client signed for gets switched off.
"""
from schema import Finding
import severity as sv
from severity import Sev
import notes as notes_mod


def _aggregate(rows, key):
    out = {}
    for r in rows:
        out[key(r)] = out.get(key(r), 0.0) + r["_mv"]
    return out


def _classify(book, claims, client_id, asset_class):
    """(status, severity multiplier, what to call that multiplier, evidence)"""
    waivers = notes_mod.has(claims, client_id, "waiver")
    if waivers:
        return "waived", sv.WAIVED_X, "waived in writing", waivers[-1:]
    directed = notes_mod.has(claims, client_id, "directed")
    if directed:
        return "directed", sv.DIRECTED_X, "client-directed, on file", directed[-1:]
    return "open", 1.0, "", []


def run(book, claims):
    out = []
    for client in book.clients:
        cid = client["client_id"]
        for p in book.managed_portfolios(cid):          # custody is never measured
            pid, code = p["portfolio_id"], p["mandate_code"]
            rows = book.portfolio_rows(pid)
            total = sum(r["_mv"] for r in rows)
            if not total:
                continue
            discretionary = p["service_model"] == "Discretionary"

            # ── 1. asset class bands ──────────────────────────────────────
            mix = _aggregate(rows, lambda r: r["asset_class"])
            for asset, (lo, tgt, hi) in book.bands[code].items():
                w = 100 * mix.get(asset, 0.0) / total
                gap = max(w - hi, lo - w)
                if gap <= 0.05:
                    continue
                status, mult, mult_label, evid = _classify(book, claims, cid, asset)
                sev = (Sev.of("%.1fpp outside the %s band" % (gap, code),
                              "gap x %g per point" % sv.MANDATE_BAND_PER_PP,
                              gap * sv.MANDATE_BAND_PER_PP)
                       .times("discretionary mandate",
                              sv.DISCRETIONARY_X if discretionary else 1.0)
                       .times(mult_label or "advisory, client's own choice", mult)
                       .cap(sv.MANDATE_BAND_CEILING))
                direction = "above" if w > hi else "below"
                out.append(Finding(
                    id="MAN-%s-%s" % (pid, asset[:4].upper().replace(" ", "")),
                    client_id=cid, dimension="mandate", severity=sev,
                    headline="%s is %.1f points %s its %s band in %s" % (
                        asset, gap, direction, code, pid),
                    detail=("%s runs %.1f%% %s against a %.0f–%.0f%% band in the %s mandate "
                            "(%s). Target is %.0f%%." % (
                                pid, w, asset, lo, hi, p["mandate_name"],
                                p["service_model"].lower(), tgt)),
                    action=("Bank-side drift in a discretionary mandate — correct it."
                            if discretionary and status == "open" else
                            "Client-directed. Confirm the position is still intended and documented."
                            if status == "directed" else
                            "Waived in writing. No action; shown for the record."
                            if status == "waived" else
                            "Advisory portfolio. Raise at the next review."),
                    rule_text=("weight(asset_class) outside [min_pct, max_pct] from mandates.csv; "
                               "managed portfolios only, custody is excluded; "
                               "severity = gap_pp x %g, x%g if Discretionary" % (
                                   sv.MANDATE_BAND_PER_PP, sv.DISCRETIONARY_X)),
                    numbers={"weight_pct": round(w, 2), "min_pct": lo, "max_pct": hi,
                             "target_pct": tgt, "gap_pp": round(gap, 2)},
                    source_rows=["portfolios.%s" % pid, "mandates.%s.%s" % (code, asset)],
                    status=status, evidence=evid))

            # ── 2. single position limit ──────────────────────────────────
            limit = book.single_limit[code]
            singles = _aggregate(
                [r for r in rows if book.I[r["instrument_id"]]["concentration_limit_applies"] == "Y"],
                lambda r: r["instrument_id"])
            for iid, mv in singles.items():
                w = 100 * mv / total
                if w <= limit + 0.05:
                    continue
                status, mult, mult_label, evid = _classify(book, claims, cid, None)
                out.append(Finding(
                    id="LIM-%s-%s" % (pid, iid),
                    client_id=cid, dimension="mandate",
                    severity=(Sev.of("%.1fpp over a %.0f%% single-position cap" % (w - limit, limit),
                                     "excess x %g per point" % sv.LIMIT_PER_PP,
                                     (w - limit) * sv.LIMIT_PER_PP)
                              .times(mult_label or "not waived or directed", mult)
                              .cap(sv.LIMIT_CEILING)),
                    headline="%s is %.1f%% of %s against a %.0f%% single-position limit" % (
                        book.I[iid]["instrument_name"], w, pid, limit),
                    detail=("The %s mandate caps any single position at %.0f%%. %s sits at %.1f%%, "
                            "%.1f points over." % (p["mandate_name"], limit,
                                                   book.I[iid]["instrument_name"], w, w - limit)),
                    action="Trim to the limit or document why it stands.",
                    rule_text=("weight > max_single_position_pct, applied only where "
                               "instruments.concentration_limit_applies = Y — not to diversified "
                               "funds, sovereigns or deposits"),
                    numbers={"weight_pct": round(w, 2), "limit_pct": limit},
                    source_rows=["holdings.%s.%s" % (pid, iid), "mandates.%s" % code],
                    status=status, evidence=evid))

            # ── 3. binding exclusions ─────────────────────────────────────
            # One finding per portfolio, however many holdings breach the list.
            # It is one problem with one fix — the mandate holds what it
            # promised not to — and three cards saying so three times read as
            # three problems, and would send the client three letters.
            if "excl" in book.mandate_notes.get(code, "").lower() or code == "SUSBAL":
                hits = [{"instrument_id": r["instrument_id"],
                         "instrument": book.I[r["instrument_id"]]["instrument_name"],
                         "weight_pct": round(100 * r["_mv"] / total, 2)}
                        for r in rows
                        if book.I[r["instrument_id"]]["sustainability_excluded"] == "Y"]
                if hits:
                    out.append(_exclusion(book, claims, cid, p, pid, code, total, rows,
                                          hits, discretionary))
    return out


def _excluded_list(note):
    """What the mandate excludes, from its own note: "Balanced allocation with
    binding exclusions: thermal coal mining, …" reads as the part after the colon."""
    return note.split(":", 1)[1].strip().rstrip(".") if ":" in note else note.rstrip(".")


def _exclusion(book, claims, cid, p, pid, code, total, rows, hits, discretionary):
    hits.sort(key=lambda h: -h["weight_pct"])
    ids = {h["instrument_id"] for h in hits}
    w = 100 * sum(r["_mv"] for r in rows if r["instrument_id"] in ids) / total
    names = ["%s (%.1f%%)" % (h["instrument"], h["weight_pct"]) for h in hits]
    held = (names[0] if len(names) == 1
            else ", ".join(names[:-1]) + " and " + names[-1])
    many = len(hits) > 1
    return Finding(
        id="EXC-%s" % pid,
        client_id=cid, dimension="mandate",
        severity=Sev.of(
            "%s on the mandate's own exclusion list"
            % ("%d instruments" % len(hits) if many else "an instrument"),
            "%s mandate" % p["service_model"].lower(),
            sv.EXCLUSION_DISCRETIONARY if discretionary else sv.EXCLUSION_ADVISORY),
        headline=("%d holdings breach the %s exclusion list" % (len(hits), p["mandate_name"])
                  if many else "%s breaches the %s exclusion list"
                  % (hits[0]["instrument"], p["mandate_name"])),
        detail=("%s holds %s%s. %s on the list of exclusions the %s mandate is bound by: %s."
                % (pid, held, ", %.1f%% of the portfolio between them" % w if many else "",
                   "Each is" if many else "It is", p["mandate_name"],
                   _excluded_list(book.mandate_notes[code]))),
        action=("Discretionary mandate — this is the bank's error, not the client's. "
                "Exit, and tell the client before a statement does."
                if discretionary else
                "Advisory — raise with the client and document the decision."),
        rule_text=("instruments.sustainability_excluded = Y inside a mandate whose "
                   "mandate_notes carry binding exclusions; one finding per portfolio"),
        numbers={"weight_pct": round(w, 2), "holdings": hits},
        source_rows=(["holdings.%s.%s" % (pid, h["instrument_id"]) for h in hits]
                     + ["instruments.%s" % h["instrument_id"] for h in hits]),
        status="open", evidence=notes_mod.has(claims, cid, "awareness_gap", "protected"))
