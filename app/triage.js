/* app/triage.js — a direct port of `rank` in engine/triage.py.
 *
 * This is the one place the workbench is allowed to produce a number, and it
 * is deliberate. The split is:
 *
 *   severity   a property of the finding. Computed once, in engine/severity.py,
 *              from data. Never recomputed here — the values below come
 *              straight out of the bundle.
 *   ranking    a property of the RM's judgement: how much each dimension
 *              counts and where the tier lines fall. She has to be able to
 *              move those and see the book reorder, or the ranking is a black
 *              box she is asked to trust.
 *
 * So this file re-applies published weights to published severities. It reads
 * nothing from data/ and derives no new fact about a client. `parityCheck`
 * below re-runs it at the engine's own defaults and shouts if the two ever
 * disagree, which is what keeps the port honest. */
"use strict";

function rankBook(bundle, cfg) {
  const W = cfg.weights, T = cfg.tiers, MATERIAL = cfg.material;
  const weight = d => (W[d] === undefined ? 1 : W[d]);

  const byClient = {};
  bundle.findings.forEach(f => {
    (byClient[f.client_id] = byClient[f.client_id] || []).push(f);
  });

  // Object key order is the engine's own client order, so ties break the same
  // way here as they do in Python — both sorts are stable.
  const rows = Object.keys(bundle.clients).map(cid => {
    const all = byClient[cid] || [];
    const mine = all.filter(f => f.status !== "waived");
    const governed = all.filter(f => f.status === "waived");
    const scored = mine.map(f => ({ s: f.severity * weight(f.dimension), f }))
                       .sort((a, b) => b.s - a.s);

    const peak = scored.length ? scored[0].s : 0;
    // One obligation is one problem: a finding that restates another (a life
    // event and its funding verdict) keeps its card but does not count twice.
    const material = scored.filter(x => x.s >= MATERIAL && !x.f.same_fact_as).length;
    const wealth = bundle.clients[cid].wealth_usd;
    // peak dominates; material count breaks ties; AUM breaks those
    const score = peak * 1000 + material * 10 + Math.min(wealth / 1e7, 9);

    const byDim = {};
    scored.forEach(x => {
      byDim[x.f.dimension] = Math.max(byDim[x.f.dimension] || 0, x.f.severity);
    });

    return {
      client_id: cid,
      name: bundle.clients[cid].profile.client_name,
      wealth_usd: wealth,
      score: round2(score),
      peak: round1(peak),
      material: material,
      lead: scored.length ? scored[0].f.id : null,
      lead_dimension: scored.length ? scored[0].f.dimension : null,
      lead_label: scored.length ? scored[0].f.label : "Nothing outstanding",
      lead_headline: scored.length ? scored[0].f.headline
                                   : "No finding outstanding across any dimension.",
      dimensions: [...new Set(mine.map(f => f.dimension))].sort(),
      finding_ids: scored.map(x => x.f.id),
      governed_ids: governed.map(f => f.id),
      peak_by_dimension: byDim,
    };
  });

  rows.sort((a, b) => b.score - a.score);
  rows.forEach((r, i) => {
    r.rank = i + 1;
    r.tier = r.peak >= T.act ? "act" : r.peak >= T.review ? "review" : "watch";
  });
  return rows;
}

const round1 = v => Math.round(v * 10) / 10;
const round2 = v => Math.round(v * 100) / 100;

/* Re-run the port at the engine's own settings and compare with what the
 * engine shipped. A silent divergence here would mean the workbench and the
 * terminal disagree about who to call first, which is the one thing this
 * product cannot get wrong. */
function parityCheck(bundle) {
  const mine = rankBook(bundle, bundle.ranking);
  const bad = [];
  bundle.book.forEach((r, i) => {
    const m = mine[i];
    // Peaks are compared to one rounding step, not exactly: Python's round()
    // works on the float (54.15 -> 54.1) and Math.round on the half (54.2).
    if (!m || m.client_id !== r.client_id || m.tier !== r.tier
        || Math.abs(m.peak - r.peak) > 0.1 + 1e-9) {
      bad.push((r.client_id || "?") + " engine " + r.rank + "/" + r.tier
               + " vs port " + (m ? m.rank + "/" + m.tier : "missing"));
    }
  });
  if (bad.length) {
    console.warn("triage.js has drifted from engine/triage.py:\n  " + bad.join("\n  "));
  }
  return bad;
}
