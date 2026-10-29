"""
Book-level ranking: who does the RM call first, and can she defend it?

Severity dominates and count is only a tiebreak. An earlier additive version
scored a client higher for having several mild problems than for having one
serious one, which buried a discretionary compliance breach at rank 10. A
ranking model is only as good as its worst-represented dimension.

Weights and thresholds are here, in one visible block, and are emitted into
the bundle so the workbench can retune them live. That is the deliberate split:
a finding's SEVERITY is a property of the finding (engine/severity.py, needs a
rebuild); how much a dimension COUNTS, and where the tier lines fall, is the
RM's judgement and is hers to move without one. app/triage.js is a direct port
of `rank` below and checks itself against this output at boot.
"""
from schema import LABELS

# Dimension weights. 1.0 is neutral; raise one and that dimension outranks.
WEIGHTS = {
    "collateral":    1.00,
    "funding":       1.00,
    "mandate":       1.00,
    "purpose_fit":   1.00,
    "concentration": 1.00,
    "life_event":    0.95,
    "tax":           0.85,
    "data_quality":  0.75,     # a confidence problem, not a risk: informs, rarely leads
}

MATERIAL = 60.0      # a weighted finding at or above this counts toward the tiebreak

# Where the tier lines fall, on the weighted peak. Deliberately not saturating:
# an earlier calibration put nine clients in "act", which makes the tier
# meaningless. Nine acts is a to-do list, not a triage.
TIERS = {"act": 90.0, "review": 60.0}      # anything below "review" is "watch"


def config():
    """Everything the ranking layer is tunable by, in one payload."""
    return {"weights": WEIGHTS, "tiers": TIERS, "material": MATERIAL}


def rank(book, findings):
    by_client = {}
    for f in findings:
        by_client.setdefault(f.client_id, []).append(f)

    rows = []
    for client in book.clients:
        cid = client["client_id"]
        mine = [f for f in by_client.get(cid, []) if f.status != "waived"]
        governed = [f for f in by_client.get(cid, []) if f.status == "waived"]
        # Rank on the severity the bundle publishes (one decimal), so the terminal,
        # the workbench and its parity check all see the same peak.
        #
        # And one obligation is one problem: a dated promise produces both a life
        # event and a funding finding, both keep their card, but the weaker of
        # the pair carries `same_fact_as` and does not count again here.
        counting = [f for f in mine if not f.same_fact_as]
        scored = [(round(f.severity, 1) * WEIGHTS.get(f.dimension, 1.0), f) for f in mine]
        scored.sort(key=lambda x: -x[0])

        peak = scored[0][0] if scored else 0.0
        material = sum(1 for f in counting
                       if round(f.severity, 1) * WEIGHTS.get(f.dimension, 1.0) >= MATERIAL)
        wealth = book.wealth(cid)
        # peak dominates; material count breaks ties; AUM breaks those
        score = peak * 1000 + material * 10 + min(wealth / 1e7, 9)

        # what each dimension contributes for this client, so the workbench can
        # show the retune's effect without recomputing anything from raw data
        by_dim = {}
        for s, f in scored:
            by_dim[f.dimension] = max(by_dim.get(f.dimension, 0.0), round(f.severity, 1))

        rows.append({
            "client_id": cid,
            "name": client["client_name"],
            "wealth_usd": wealth,
            "score": round(score, 2),
            "peak": round(peak, 1),
            "material": material,
            "lead": scored[0][1].id if scored else None,
            "lead_dimension": scored[0][1].dimension if scored else None,
            "lead_label": LABELS.get(scored[0][1].dimension, "") if scored else "Nothing outstanding",
            "lead_headline": scored[0][1].headline if scored else
                             "No finding outstanding across any dimension.",
            "dimensions": sorted({f.dimension for f in mine}),
            "finding_ids": [f.id for f, in ((f,) for _, f in scored)],
            "governed_ids": [f.id for f in governed],
            "peak_by_dimension": by_dim,
        })

    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["tier"] = ("act" if r["peak"] >= TIERS["act"] else
                     "review" if r["peak"] >= TIERS["review"] else "watch")
    return rows
