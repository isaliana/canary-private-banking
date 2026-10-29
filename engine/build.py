"""
Runs the engine and writes app/findings.json — the only thing the UI reads.

    python3 engine/build.py

No number in the workbench is produced anywhere but here.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "modules"))

from loader import Book                      # noqa: E402
import notes as notes_mod                    # noqa: E402
import performance                           # noqa: E402
import scenario                              # noqa: E402
import clientnote                            # noqa: E402
import severity                              # noqa: E402
import triage                                # noqa: E402
import upcoming                              # noqa: E402
from modules import governance, liquidity, client_fit, tax   # noqa: E402
from modules import rebalance                # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "app", "findings.json")
NARRATION = os.path.join(HERE, "cache", "narration.json")
RECORDED = os.path.join(HERE, "cache", "translations.json")
MODULES = [governance, liquidity, client_fit, tax]


def narration():
    """Layer 3's output, if engine/narrate.py has been run. Absent is a normal
    state, not an error: no key, no network, no cache — the workbench falls back
    to the deterministic template and says so on the screen."""
    if not os.path.exists(NARRATION):
        return {}
    with open(NARRATION, encoding="utf-8") as fh:
        return json.load(fh)


def recorded_translations():
    """Translations recorded for a copy with no server (engine/translate.py
    --import-recorded). The composer replays one only for the exact text it was
    made from, and says it is a recording."""
    if not os.path.exists(RECORDED):
        return []
    with open(RECORDED, encoding="utf-8") as fh:
        return json.load(fh)


def link_duplicates(book, findings):
    """A dated obligation produces two findings, and that is correct.

    `life_event` says a promise is large relative to the wealth behind it.
    `funding` says whether the portfolio can actually meet it. Different
    claims, different actions, both worth a card — CL-0002 is told his HKD 80m
    land deposit is 27% of his wealth *and* that selling to pay it trips a
    margin call.

    But it is one obligation, so it is one problem. Counting it twice inflates
    the material tiebreak, which is the specific failure that once buried a
    discretionary compliance breach at rank ten. The weaker of the pair keeps its
    card and its severity, records which finding it doubles, and stops counting.
    Severity decides which is weaker, not dimension: for CL-0014 the life
    events are the more serious half and the funding finding defers to them."""
    fund = {}
    for f in findings:
        if f.dimension == "funding":
            fund[f.client_id] = f
    for f in findings:
        if f.dimension != "life_event" or f.client_id not in fund:
            continue
        need_id = f.source_rows[0].split(".")[-1] if f.source_rows else ""
        peer = fund[f.client_id]
        if need_id not in set(peer.numbers.get("need_ids", [])):
            continue
        weak, strong = (f, peer) if f.severity <= peer.severity else (peer, f)
        weak.same_fact_as = strong.id

    # A client with two obligations and one funding verdict can chain — a second
    # life event defers to the funding finding, which itself defers to the
    # first. Resolve to the head so `same_fact_as` always names a card that is
    # still counting, and one cluster contributes one problem at its worst
    # severity.
    by_id = {f.id: f for f in findings}
    for f in findings:
        seen = set()
        while f.same_fact_as and f.same_fact_as in by_id:
            nxt = by_id[f.same_fact_as]
            if not nxt.same_fact_as or nxt.id in seen:
                break
            seen.add(nxt.id)
            f.same_fact_as = nxt.same_fact_as
    return findings


def _with_note(d, notes):
    """The deterministic client note, in plain language and in the client's own
    language where we have frames for it. Always present; the model layer
    replaces it when it has run, and the drawer says which is which."""
    if d["id"] in notes:
        d["note"] = notes[d["id"]]
    return d


def _with_plan(d, plans):
    if d["id"] in plans:
        d["plan"] = plans[d["id"]]
    return d


def _with_draft(d, drafts):
    """The model's draft, signed. The narration prompt leaves the signature to
    the RM, so her own sign-off is added here, in the language of each version —
    the same one the deterministic note uses."""
    rec = drafts.get(d["id"])
    if rec:
        lang = rec.get("language", "") or "English"
        sign = lambda l: clientnote.SIGN.get(l, clientnote.SIGN["English"])
        d["draft"] = {"subject": rec["draft"]["subject"],
                      "english": rec["draft"]["english"] + "\n\n" + sign("English"),
                      "client_language": rec["draft"]["client_language"] + "\n\n" + sign(lang),
                      "raises": rec["draft"]["raises"],
                      "language": lang,
                      "unverified": rec.get("unverified", []),
                      "at": rec.get("at", ""),
                      "model": rec.get("usage", {}).get("model", ""),
                      "via": rec.get("via", "API")}
    return d


def build_bundle(book, drafts=None, recorded=None):
    """The bundle as a dict: everything the workbench reads, and nothing else.

    `drafts` maps finding id -> narration record (the shape engine/narrate.py
    caches). Absent is a normal state. `main()` below writes this to disk."""
    drafts = drafts or {}
    claims = notes_mod.extract(book.notes)

    findings = []
    for mod in MODULES:
        produced = mod.run(book, claims)
        findings.extend(produced)
        print("  %-14s %3d findings" % (mod.__name__.split(".")[-1], len(produced)))

    link_duplicates(book, findings)
    order = triage.rank(book, findings)
    # Module E. A plan is attached to the finding that motivated it rather than
    # emitted as a finding of its own: a client with one band breach must not
    # rank as though they had two problems.
    plans = rebalance.build(book, claims, findings)
    print("  %-14s %3d plans" % ("rebalance", len(plans)))
    print("  %-14s %3d stated shocks, repriced per client"
          % ("scenario", len(scenario.SCENARIOS)))
    notes = clientnote.build(book, findings)
    langs = sorted({l for v in notes.values() for l in v if l != "English"})
    print("  %-14s %3d notes, %d in a second language (%s)"
          % ("client note", len(notes),
             sum(1 for v in notes.values() if len(v) > 1), ", ".join(langs)))

    # per-client dossier context the UI needs and should not recompute
    clients = {}
    for c in book.clients:
        cid = c["client_id"]
        positions = book.positions(cid)
        rows = []
        for iid, p in sorted(positions.items(), key=lambda kv: -kv[1]["mv"]):
            inst = book.I[iid]
            rows.append({
                "instrument_id": iid, "name": inst["instrument_name"],
                "asset_class": inst["asset_class"], "sub": inst["sub_asset_class"],
                "sector": inst["sector"], "region": inst["region"],
                "currency": inst["currency"], "liquidity": inst["liquidity_tier"],
                "market_value_usd": round(p["mv"]), "unrealised_usd": round(p["pnl"]),
                "weight_pct": round(100 * p["mv"] / book.wealth(cid), 2),
                "underlying": inst["underlying_reference"],
                "excluded": inst["sustainability_excluded"] == "Y",
                "stale_mark": book.stale_marks.get(iid, ""),
            })
        mix = {}
        for r in rows:
            mix[r["asset_class"]] = mix.get(r["asset_class"], 0) + r["market_value_usd"]
        clients[cid] = {
            "profile": c,
            "wealth_usd": book.wealth(cid),
            "wealth_series": [{"date": d, "usd": book.wealth(cid, d)} for d in book.dates],
            "daily_liquid_usd": book.daily_liquid(cid),
            "portfolios": [{**p, "aum_usd": sum(r["_mv"] for r in book.portfolio_rows(p["portfolio_id"]))}
                           for p in book.client_portfolios(cid)],
            "positions": rows,
            "mix": mix,
            "performance": performance.build(book, cid),
            "scenarios": scenario.build_for(book, cid),
            "claims": claims.get(cid, []),
            "notes": book.client_notes(cid),
            "facilities": book.client_facilities(cid),
            "needs": book.client_needs(cid),
            "funding": liquidity.cover_report(book, cid),
            "commitments": book.client_commitments(cid),
        }

    return {
        "generated_from": "data/ at snapshot %s" % book.today,
        "dates": book.dates, "today": book.today,
        "book": order,
        "findings": [_with_note(_with_plan(_with_draft(f.as_dict(), drafts), plans), notes)
                     for f in findings],
        "clients": clients,
        "events": book.events,
        "upcoming": upcoming.build(book),
        "recorded_translations": recorded or [],
        "ranking": triage.config(),          # tunable in the workbench, no rebuild
        "calibration": severity.CALIBRATION,  # read-only there; needs a rebuild
    }


def main():
    book = Book()
    bundle = build_bundle(book, narration(), recorded_translations())
    findings = bundle["findings"]
    order = bundle["book"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, separators=(",", ":"))
    # also as a script, so the workbench opens from file:// with no server —
    # one less thing to go wrong on stage
    with open(OUT.replace(".json", ".js"), "w", encoding="utf-8") as fh:
        fh.write("window.FINDINGS = ")
        json.dump(bundle, fh, separators=(",", ":"))
        fh.write(";")

    drafted = sum(1 for f in bundle["findings"] if f.get("draft"))
    held = sum(1 for f in bundle["findings"]
               if f.get("draft") and f["draft"]["unverified"])
    print("\n  narration    %3d of %d findings drafted%s" % (
        drafted, len(findings),
        "" if not drafted else ", %d held back on the numeric check" % held))
    print("\n  %d findings across %d clients -> %s (%.0f KB)" % (
        len(findings), len({f["client_id"] for f in findings}), OUT,
        os.path.getsize(OUT) / 1024))
    print("\n  %-4s %-9s %-26s %9s  %-14s %s" % ("#", "id", "client", "AUM", "driver", "headline"))
    print("  " + "-" * 116)
    for r in order:
        print("  %-4d %-9s %-26s %8.1fm  %-14s %s" % (
            r["rank"], r["client_id"], r["name"][:25], r["wealth_usd"] / 1e6,
            r["lead_label"], r["lead_headline"][:56]))


if __name__ == "__main__":
    main()
