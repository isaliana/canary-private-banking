/* Canary — the RM workbench.
 *
 * This file renders. It does not calculate. Every number displayed comes from
 * app/findings.js, produced by the deterministic engine in engine/. If you find
 * yourself about to write arithmetic here, it belongs in a module instead. */
"use strict";

const B = window.FINDINGS;
/* The book belongs to one RM, and the copy uses her name — read from the data
 * rather than written into the interface. */
const RM = (B.clients[B.book[0].client_id] || {}).profile || {};
const RM_FIRST = (RM.rm_name || "").split(" ")[0] || "The RM";
const F = {};                       // finding id -> finding
B.findings.forEach(f => F[f.id] = f);
const state = {
  view: "book",
  client: null,
  filter: null,
  tier: null,
  decisions: load("wb.decisions", {}),
  drafts: load("wb.drafts", {}),
  ranking: null,                    // null means the engine's own settings
  tab: "raise",                     // dossier tab
  step: null,                       // which snapshot window is open
  shock: 0,                         // which stated scenario is selected
  notes: {},                        // notes the RM writes in the workbench
  noteLang: {},                     // which language of a draft is on screen
  sync: load("wb.sync", {}),        // finding id -> the last checked translation
};

/* What the RM decides, drafts and writes lives in this browser's storage. */
function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) || fallback; }
  catch (e) { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
}

/* ── the ranking layer ────────────────────────────────────────────────
 * The engine ships its weights and tier lines in the bundle, and app/triage.js
 * is a direct port of the ranking that used them. The RM can move both and
 * watch the book reorder; until she does, `state.ranking` is null and the
 * workbench renders exactly what `python3 engine/build.py` printed. Severity
 * itself is never touched here — see the note at the top of triage.js. */
const DEFAULT_CFG = B.ranking;
const ENGINE_RANK = {};             // client id -> the rank the engine gave them
B.book.forEach(r => { ENGINE_RANK[r.client_id] = r.rank; });

state.ranking = load("wb.ranking", null);
state.notes = load("wb.notes", {});

const cfg = () => state.ranking || DEFAULT_CFG;
const tuned = () => !!state.ranking;

function sameAsDefault(c) {
  return Object.keys(DEFAULT_CFG.weights).every(d => c.weights[d] === DEFAULT_CFG.weights[d])
    && c.tiers.act === DEFAULT_CFG.tiers.act
    && c.tiers.review === DEFAULT_CFG.tiers.review
    && c.material === DEFAULT_CFG.material;
}

let ROWS = [];                      // the ranked book, at the current settings
let BOOK = {};                      // client id -> triage row
function reRank() {
  ROWS = rankBook(B, cfg());
  BOOK = {};
  ROWS.forEach(r => { BOOK[r.client_id] = r; });
}

/* ── porcelain (lieflat-charts) ────────────────────────────────────────
 * Single-hue blue ladder: lightness is the data, exactly as the mono contract
 * intends. Used for every chart in the app; the chrome keeps its own palette,
 * whose ivory and navy are within a hair of porcelain's own BG and TXT. */
const P = {
  TXT: "#141B4B", MUT: "rgba(20,27,75,.62)", LAB: "rgba(20,27,75,.74)",
  GRID: "rgba(20,27,75,.16)", TRACK: "rgba(20,27,75,.12)", FLOOR: "rgba(20,27,75,.26)",
  DATA: "#303A78", DATA2: "#969CB2", HERO: "#141B4B", FAINT: "#CED1DC",
  PALE: "#E4E6EA", BG: "#F3F2E8",
  ALERT: "#8C2F2A",          // deep brick, never a bright red
  GOLD: "#9A7B35",           // muted antique gold — see the note below
};

/* The one non-blue in the data palette. Porcelain is a single-hue ladder where
 * lightness is the data, and that contract holds everywhere a chart encodes an
 * ordered quantity. Asset-class sleeves are not ordered — they are categories
 * that happen to be sorted by size — and at a 1.3px stroke two navies read as
 * one, so the second sleeve needs hue as well as lightness to separate.
 *
 * The gold is chosen to sit at L*≈45, between navy (L*17) and blue-grey (L*63),
 * so inserting it does NOT break the lightness ladder: largest to smallest still
 * runs dark to pale. It earns its place by adding a second channel, not by
 * replacing the first. Used in exactly one chart — an accent that appears twice
 * is no longer an accent — and never for the alert brick's job. */

/* ── formatting ───────────────────────────────────────────────────────── */
const usdm = v => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "m"
                 : Math.abs(v) >= 1e3 ? Math.round(v / 1e3) + "k" : Math.round(v));
const usd2 = v => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + "m" : usdm(v));
const full = v => "USD " + Math.round(v).toLocaleString("en-US");
const signed = v => (v > 0 ? "+" : v < 0 ? "−" : "") + usdm(Math.abs(v));
const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dateLong = d => new Date(d + "T00:00:00Z")
  .toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const dateShort = d => new Date(d + "T00:00:00Z")
  .toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });

/* ── screen 1 · the book ──────────────────────────────────────────────── */
const TIER_ORDER = [["act", "Act"], ["review", "Review"], ["watch", "Watch"]];
const TIER_WORD = { act: "act tier", review: "review tier", watch: "watch tier" };

function visibleRows() {
  let rows = ROWS;
  if (state.filter) rows = rows.filter(r => r.dimensions.includes(state.filter));
  if (state.tier) rows = rows.filter(r => r.tier === state.tier);
  return rows;
}

function cohortLabel() {
  const bits = [];
  if (state.tier) bits.push(TIER_WORD[state.tier]);
  if (state.filter) bits.push(label(state.filter).toLowerCase() + " findings");
  return bits.join(", filtered to ");
}

function renderBook() {
  const counts = {};
  B.findings.forEach(f => { counts[f.dimension] = (counts[f.dimension] || 0) + 1; });
  const dims = [...new Set(ROWS.flatMap(r => r.dimensions))]
    .sort((a, b) => (counts[b] || 0) - (counts[a] || 0));
  const tiers = { act: [], review: [], watch: [] };
  ROWS.forEach(r => tiers[r.tier].push(r));

  const rows = visibleRows();
  // The calendar answers whatever question the book is currently asking. A
  // tier or dimension filter scopes it too — otherwise every tile opens the
  // same diary, which is what made the tiles feel inert.
  const cohort = (state.tier || state.filter)
    ? new Set(rows.map(r => r.client_id)) : null;
  const act = tiers.act.length;

  document.getElementById("view").innerHTML = `
  <div class="masthead">
    <div class="eyebrow date">${esc(dateLong(B.today))} · start of week${
      RM.rm_desk ? " · " + esc(RM.rm_desk.replace(" - ", ", ")) : ""}</div>
    <h1>${act} ${act === 1 ? "client needs" : "clients need"} you before anything else.</h1>
    <p class="lede">Clients in order of their most serious open issue, not their account
      size. Every figure opens to the rule behind it and the data it came from, and you set
      how much each type of issue counts.</p>
  </div>

  ${startHere()}

  ${metricStrip(tiers)}

  <section class="deck">
    <figure class="viz-map">
      <figcaption>
        <h2>Attention does not follow assets</h2>
        <p class="sub">Across is total wealth, up is the severity of that client's worst
          open finding. The dotted rules are the tier thresholds. Hover a client for what
          is wrong; click to open them.</p>
      </figcaption>
      <div data-reveal>${riskMap()}</div>
    </figure>
    ${Diary.html(cohort, cohortLabel())}
  </section>

  <section class="book">
    <div class="book-head">
      <h2>Who to call first</h2>
      <div class="filters">
        <button data-dim="" aria-pressed="${!state.filter}">All<b>${B.findings.length}</b></button>
        ${dims.map(d => `<button data-dim="${d}" aria-pressed="${state.filter === d}">${
          esc(label(d))}<b>${counts[d]}</b></button>`).join("")}
      </div>
    </div>
    <table class="book-table">
      <thead><tr>
        <th></th><th>Client</th><th class="r">Wealth</th><th>What is wrong</th><th class="r">Findings</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => {
          const c = B.clients[r.client_id].profile;
          const moved = ENGINE_RANK[r.client_id] - r.rank;
          return `<tr class="tier-${r.tier}" data-client="${r.client_id}" tabindex="0"
            style="--i:${rows.indexOf(r)}">
            <td class="rank-cell n">${r.rank}${tuned() && moved ? `<span class="moved ${
              moved > 0 ? "up" : "down"}">${moved > 0 ? "▲" : "▼"}${Math.abs(moved)}</span>` : ""}</td>
            <td class="who-cell">
              <div class="nm">${esc(r.name)}</div>
              <div class="sub">${esc(c.client_id)} · ${esc(c.booking_centre)} · ${esc(c.wealth_band)}</div>
            </td>
            <td class="r n" style="padding-top:20px">${usdm(r.wealth_usd)}</td>
            <td class="lead-cell">
              <div class="hd"><span class="marker"></span>${esc(r.lead_headline)}</div>
              <div class="dims">${r.dimensions.map(d =>
                `<span class="tag${d === r.lead_dimension ? " on" : ""}">${esc(label(d))}</span>`).join("")}
              </div>
            </td>
            <td class="r n dim" style="padding-top:20px">${r.finding_ids.length || "—"}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>
    ${rows.length ? "" : `<p class="empty">No client matches that combination.</p>`}
  </section>`;

  wireStartHere();
  document.querySelectorAll("[data-dim]").forEach(b =>
    b.addEventListener("click", () => { state.filter = b.dataset.dim || null; renderBook(); }));
  document.querySelectorAll("[data-tier]").forEach(b => {
    const go = () => { state.tier = state.tier === b.dataset.tier ? null : b.dataset.tier;
      renderBook(); };
    b.addEventListener("click", go);
    b.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") {
      e.preventDefault(); go(); } });
  });
  document.querySelectorAll("[data-tune]").forEach(b =>
    b.addEventListener("click", () => openTuner()));
  document.querySelectorAll("[data-reset-rank]").forEach(b =>
    b.addEventListener("click", resetRanking));
  document.querySelectorAll("[data-client]").forEach(el => {
    const go = () => openClient(el.dataset.client);
    el.addEventListener("click", go);
    el.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  });
  Diary.wire();
  wireMapHover();
  armReveal();
}

/* ── start here ───────────────────────────────────────────────────────
 * For someone opening the workbench for the first time rather than for Clara:
 * three stops that show what the rest of the screen is for. The first is the
 * finding no statement shows — a client who can sell enough to pay a promise,
 * except that selling it trips the margin call on the loan it secures. Chosen
 * from the data, not named here, so a regenerated book still has a first stop;
 * with no such finding the strip does not appear. Every figure is the engine's. */
function startHere() {
  if (load("wb.start", "") === "hidden") return "";
  const f = B.findings.filter(x => x.dimension === "funding" && x.numbers.blocked
                                  && x.numbers.collateral)
    .sort((a, b) => b.severity - a.severity)[0];
  if (!f) return "";
  const p = B.clients[f.client_id].profile;
  const c = f.numbers.collateral;
  const lang = p.reporting_language && p.reporting_language !== "English"
    ? p.reporting_language : "";
  return `<aside class="start" aria-label="Start here">
    <div class="start-head"><span class="eyebrow">First time here? Three stops</span>
      <button class="linkish" data-start-hide>Hide</button></div>
    <ol class="start-stops">
      <li><button data-start="finding" data-fid="${esc(f.id)}">
        <b>The margin call no statement shows</b>
        <span>${esc(p.client_name.split(" ")[0])} can sell ${esc(c.currency)} ${
          (c.daily_mv / 1e6).toFixed(1)}m in a day. Selling enough of it to pay a promise
          takes the loan it secures to ${c.post_ltv_pct}%, past a ${c.trigger_pct}% margin
          trigger.</span></button></li>
      <li><button data-start="note" data-fid="${esc(f.id)}">
        <b>The note${lang ? ", in " + esc(lang) : ""}</b>
        <span>Claude drafts it from the finding alone${lang ? ", in " + esc(lang)
          + " and English" : ""}. Every figure is checked against the engine before it
          reaches the screen, and names never leave the machine.</span></button></li>
      <li><button data-start="tune">
        <b>You decide what counts</b>
        <span>Move the weights and the book reorders behind the panel. Severity stays the
          engine's; the weighting is the RM's.</span></button></li>
    </ol>
  </aside>`;
}

function wireStartHere() {
  document.querySelectorAll("[data-start-hide]").forEach(b =>
    b.addEventListener("click", () => { save("wb.start", "hidden"); renderBook(); }));
  document.querySelectorAll("[data-start]").forEach(b =>
    b.addEventListener("click", () => {
      if (b.dataset.start === "tune") return openTuner();
      const f = F[b.dataset.fid];
      openClient(f.client_id);
      if (b.dataset.start === "note") return openDrawer(f.id);
      const el = document.getElementById("f-" + f.id);
      if (el) { el.scrollIntoView({ block: "start" }); el.classList.add("flash");
                setTimeout(() => el.classList.remove("flash"), 1200); }
    }));
}

/* The strip. Two kinds of number, and the design now says so: what the book IS
 * on the left — clients, assets, findings — and what it ASKS OF HER on the
 * right, where every figure is a filter rather than a fact. The rule between
 * them is the point; these were one undifferentiated row, and the totals were
 * also repeated in the standfirst above. */
function metricStrip(tiers) {
  const aum = ROWS.reduce((sum, r) => sum + r.wealth_usd, 0);
  return `<div class="metrics">
    <div class="mgroup totals">
      <div class="metric">
        <div class="v n">${ROWS.length}</div><div class="k">Clients</div></div>
      <div class="metric">
        <div class="v n">${usdm(aum)}</div><div class="k">Assets under management (USD)</div></div>
      <div class="metric">
        <div class="v n">${B.findings.length}</div><div class="k">Findings</div></div>
    </div>
    <div class="mgroup asks" role="group" aria-label="Filter the book by tier">
      ${TIER_ORDER.map(([t, name]) => `<button class="metric tier t-${t}" data-tier="${t}"
        aria-pressed="${state.tier === t}">
        <div class="v n">${tiers[t].length}</div>
        <div class="k"><i class="dot"></i>${name}</div></button>`).join("")}
    </div>
    <div class="mtail">
      <button class="tune-btn${tuned() ? " on" : ""}" data-tune>${
        tuned() ? "Ranking · retuned" : "How this is ranked"}</button>
      ${tuned() ? `<button class="tune-reset" data-reset-rank>Reset</button>` : ""}
    </div>
  </div>`;
}

function label(d) {
  const f = B.findings.find(x => x.dimension === d);
  return f ? f.label : d;
}

/* Severity against wealth — after lieflat-charts `basics-gallery.html`, card
 * C4 (F8 Plumb Scatter). The reading it exists to force: the tallest dot in the
 * book is not the widest one.
 *
 * The plumb lines are gone. They were the template's own mechanism and they
 * did their job at full width, but at this size twenty hairlines dropping to
 * the floor were reading as a bar chart of nothing — the eye kept trying to
 * compare their lengths, which encode the same thing as the dot's height. What
 * survives is the part that carries the argument: position against a wealth
 * floor and a severity axis, with the tier rules drawn in.
 *
 * Kept from the template: the barcode floor with fifth-tick emphasis, end
 * labels in place of numeric ticks, hero dots labelled with a paint-order halo,
 * rotated axis hint, footer caption stating the reading rule. The tier rules
 * read from the live ranking config, so retuning a weight moves them.
 *
 * Hovering a dot opens a card: who, how much, and a one-line brief of what is
 * actually wrong — the lead finding plus every dimension they carry. The point
 * of the chart is that the tall dot is not the rich one, and you should not
 * have to open a dossier to find out why it is tall.
 * Deliberately dropped: the staggered fade/pop entrance — the visual system rules out
 * playful animation, and that overrides the gallery here.
 * Palette: porcelain. Severity band is the only thing colour encodes. */
function riskMap() {
  const W = 730, H = 322, X0 = 46, X1 = W - 30, base = H - 52;
  const wmax = Math.ceil(Math.max(...ROWS.map(r => r.wealth_usd)) / 1e7) * 1e7;
  const mapX = v => X0 + (v / wmax) * (X1 - X0);
  const mapY = v => base - (v / 100) * (base - 54);
  const T = cfg().tiers;

  // nudge coincident hero markers apart; two clients can sit at nearly the
  // same wealth and severity and one must not hide the other
  const placed = [], nudge = {}, lift = {};
  ROWS.filter(r => r.tier === "act").sort((a, b) => b.peak - a.peak).forEach(r => {
    let dx = 0;
    const y = mapY(r.peak);
    for (let g = 0; g < 12; g++) {
      const x = mapX(r.wealth_usd) + dx;
      if (!placed.some(p => Math.hypot(p.x - x, p.y - y) < 56)) break;
      dx = dx > 0 ? -dx : -dx + 32;
    }
    const x = mapX(r.wealth_usd) + dx;
    // the label is far wider than the dot, so separating the dots is not enough:
    // anything still within a label's width of a placed one gets a rung higher
    let up = 0;
    while (up < 60 && placed.some(p => Math.abs(p.x - x) < 112
                                    && Math.abs((y - up) - (p.y - p.up)) < 24)) up += 16;
    nudge[r.client_id] = dx;
    lift[r.client_id] = up;
    placed.push({ x: x, y: y, up: up });
  });

  const barcode = [];
  for (let g = 0; g <= 20; g++) {
    const x = X0 + (g / 20) * (X1 - X0);
    barcode.push(`<line x1="${x.toFixed(1)}" y1="${base}" x2="${x.toFixed(1)}"
      y2="${base - (g % 5 === 0 ? 7 : 3.5)}" stroke="${P.FLOOR}" stroke-width="0.9"/>`);
  }

  return `<svg viewBox="0 0 ${W} ${H}" class="map" role="img"
      aria-label="${ROWS.length} clients placed by total wealth across and the severity of
        their worst open finding up. The most severe finding in the book belongs to a client
        well below the book's average wealth.">
    ${[{ at: T.act, n: "ACT" }, { at: T.review, n: "REVIEW" }].map(t => `
      <line x1="${X0}" x2="${X1}" y1="${mapY(t.at).toFixed(1)}" y2="${mapY(t.at).toFixed(1)}"
        stroke="${P.GRID}" stroke-width="1" stroke-dasharray="1 5"/>
      <text class="thr" x="${X1}" y="${(mapY(t.at) - 6).toFixed(1)}"
        text-anchor="end">${t.n} ${t.at}</text>`).join("")}

    <g class="fade" style="--d:.05s">${barcode.join("")}</g>
    <line x1="${X0 - 8}" y1="${base}" x2="${X1 + 8}" y2="${base}"
      stroke="${P.LAB}" stroke-width="1.2"/>
    <text class="foot" x="${X0}" y="${base + 16}">SMALLEST</text>
    <text class="foot" x="${X1}" y="${base + 16}" text-anchor="end">LARGEST · USD ${
      (wmax / 1e6).toFixed(0)}m</text>
    <text class="foot" x="18" y="${mapY(84).toFixed(1)}" text-anchor="end"
      transform="rotate(-90 18 ${mapY(84).toFixed(1)})">MORE SEVERE &#8593;</text>

    ${ROWS.slice().sort((a, b) => a.peak - b.peak).map((r, i) => {
      const act = r.tier === "act", rev = r.tier === "review";
      const trueX = mapX(r.wealth_usd), dx = act ? (nudge[r.client_id] || 0) : 0;
      const x = trueX + dx, y = mapY(r.peak);
      const tone = act ? P.ALERT : rev ? P.DATA : P.DATA2;
      // The first name, not the last word: "Raymond Wong Ka Lok" ends in a
      // given name, and "Lok" would be no one's idea of how to refer to him.
      const short = r.name.split(" ")[0];
      return `<g class="pt${act ? " act" : ""}" data-client="${r.client_id}" tabindex="0"
          role="button" aria-label="Rank ${r.rank}, ${esc(r.name)}, ${usdm(r.wealth_usd)} USD,
            worst finding ${r.peak.toFixed(0)}. ${esc(r.lead_headline)}">
        ${dx ? `<line class="fade" style="--d:${(0.18 + i * 0.045).toFixed(2)}s"
          x1="${trueX.toFixed(1)}" y1="${y.toFixed(1)}" x2="${x.toFixed(1)}"
          y2="${y.toFixed(1)}" stroke="${P.FAINT}" stroke-width="1"
          stroke-dasharray="1 3"/>
        <circle class="fade" style="--d:${(0.18 + i * 0.045).toFixed(2)}s"
          cx="${trueX.toFixed(1)}" cy="${y.toFixed(1)}" r="1.4" fill="${P.FAINT}"/>` : ""}
        <circle class="hit" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="14" fill="transparent"/>
        <circle class="dot pop" style="--d:${(0.24 + i * 0.045).toFixed(2)}s"
          cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${act ? 4.8 : 3}"
          fill="${tone}" stroke="${P.BG}" stroke-width="${act ? 1.5 : 0}"/>
        ${act ? `<line class="fade" style="--d:.86s" x1="${x.toFixed(1)}"
            y1="${(y - 7).toFixed(1)}" x2="${x.toFixed(1)}"
            y2="${(y - 6 - (lift[r.client_id] || 0)).toFixed(1)}"
            stroke="${P.FAINT}" stroke-width="1"/>
          <text class="hero fade" style="--d:.86s" x="${x.toFixed(1)}"
            y="${(y - 11 - (lift[r.client_id] || 0)).toFixed(1)}"
            text-anchor="middle">${r.rank} · ${esc(short)}</text>` : ""}
      </g>`;
    }).join("")}

    <text class="rule" x="${W / 2}" y="${H - 11}" text-anchor="middle">WEALTH ACROSS
      &#183; SEVERITY UP &#183; HOVER A CLIENT FOR WHAT IS WRONG</text>
  </svg>`;
}

/* Arms the gallery entrance: a figure plays when it scrolls into view and
 * replays when clicked. Falls back to fully visible without an observer or
 * when the viewer has asked for reduced motion.
 *
 * Plays on a change of screen, not on every render. The book re-renders
 * whenever the calendar switches mode or a tier tile is pressed, and
 * re-animating the scatter each time reads as a glitch. On the renders that do
 * not animate, `shown` paints everything visible outright — an entrance must
 * never be the reason something is missing. */
let revealKey = "";
function armReveal() {
  const figs = document.querySelectorAll("[data-reveal]");
  const key = state.view + ":" + (state.client || "");
  const fresh = key !== revealKey;
  revealKey = key;
  const reduce = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !fresh || !("IntersectionObserver" in window)) {
    figs.forEach(f => f.classList.add("shown"));
    return;
  }
  document.querySelectorAll("path.draw").forEach(pth => {
    try { pth.style.setProperty("--len", pth.getTotalLength().toFixed(1)); } catch (e) { /* ok */ }
  });
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      en.target.classList.add("playing");
      io.unobserve(en.target);
    });
  }, { threshold: 0.12 });
  figs.forEach(f => {
    io.observe(f);
    const svg = f.querySelector("svg");
    if (!svg) return;
    svg.addEventListener("click", e => {
      if (e.target.closest("[data-client]")) return;   // never steal a navigation click
      f.classList.remove("playing", "shown");
      void f.offsetWidth;
      f.classList.add("playing");
    });
  });
}

/* Hovering a dot has to answer "why is this one high?" without a click, so the
 * card carries the lead finding and the whole set of dimensions the client is
 * carrying — the shape of their problem, not just their name. */
function mapCard(r) {
  const c = B.clients[r.client_id].profile;
  const counts = {};
  B.findings.filter(f => f.client_id === r.client_id && f.status !== "waived")
    .forEach(f => { counts[f.dimension] = (counts[f.dimension] || 0) + 1; });
  const dims = Object.keys(counts)
    .sort((a, b) => (r.peak_by_dimension[b] || 0) - (r.peak_by_dimension[a] || 0));
  const governed = r.governed_ids.length;

  return `<div class="mc-top">
      <span class="mc-rank n">${r.rank}</span>
      <span class="mc-nm">${esc(r.name)}</span>
      <span class="mc-tier t-${r.tier}"><i class="dot"></i>${
        r.tier[0].toUpperCase() + r.tier.slice(1)}</span>
    </div>
    <div class="mc-facts">
      <span><b class="n">${usdm(r.wealth_usd)}</b> USD</span>
      <span>${esc(c.booking_centre)}</span>
      <span>worst finding <b class="n">${r.peak.toFixed(0)}</b></span>
    </div>
    ${r.lead ? `<p class="mc-lead">${esc(r.lead_headline)}</p>` : ""}
    <div class="mc-dims">${dims.map(d => `<span class="mc-d${
      d === r.lead_dimension ? " on" : ""}">${esc(label(d))}
      <b class="n">${r.peak_by_dimension[d].toFixed(0)}</b>${
      counts[d] > 1 ? `<i>&times;${counts[d]}</i>` : ""}</span>`).join("")
      || `<span class="mc-none">Nothing outstanding across any dimension.</span>`}
    </div>
    ${governed ? `<p class="mc-gov">${governed} breach${governed === 1 ? "" : "es"} governed
      and deliberately not raised.</p>` : ""}`;
}

function wireMapHover() {
  const fig = document.querySelector(".viz-map");
  if (!fig) return;
  const card = document.createElement("div");
  card.className = "mapcard";
  card.hidden = true;
  fig.appendChild(card);

  const show = g => {
    const r = BOOK[g.dataset.client];
    if (!r) return;
    g.classList.add("hot");
    card.innerHTML = mapCard(r);
    card.hidden = false;
    // place it against the figure, flipping before it can run off either edge
    const box = fig.getBoundingClientRect();
    const dot = g.querySelector(".dot").getBoundingClientRect();
    const w = card.offsetWidth, h = card.offsetHeight;
    let x = dot.left - box.left + dot.width / 2 - w / 2;
    x = Math.max(4, Math.min(x, box.width - w - 4));
    let y = dot.top - box.top - h - 14;
    if (y < 0) y = dot.bottom - box.top + 14;
    card.style.left = x + "px";
    card.style.top = y + "px";
  };
  const hide = g => { g.classList.remove("hot"); card.hidden = true; };

  document.querySelectorAll("svg.map .pt").forEach(g => {
    g.addEventListener("mouseenter", () => show(g));
    g.addEventListener("mouseleave", () => hide(g));
    g.addEventListener("focus", () => show(g));
    g.addEventListener("blur", () => hide(g));
  });
}

/* ── charts that belong to a finding ──────────────────────────────────
 * Evidence, not decoration: each renders inside the finding whose claim it
 * proves, from that finding's own numbers. Nothing is recomputed here. */
function findingChart(f) {
  if (f.dimension === "purpose_fit" && f.numbers.ladder) return maturityLadder(f);
  if (f.dimension === "collateral" && f.numbers.path) return ltvPath(f);
  if (f.dimension === "funding" && (f.numbers.collateral || {}).chart)
    return fundingChart(f);
  return "";
}
/* C1 Tick Rows — basics-gallery.html, card C1.
 * A countable unit standing on a hairline rule, jittered in height and opacity,
 * a dot under every fifth tick, the big number at the row end, and a caps
 * footer stating what one tick is. It is the right template because the whole
 * argument here is a comparison of six amounts in one currency, and the reader
 * has to be able to see that the fourth is smaller than the third.
 *
 * That gap is the finding. HKD 265.0m of daily-sellable collateral carries only
 * HKD 150.1m of lending value, so selling enough of it to raise HKD 80m takes more
 * borrowing capacity away than the sale brings in. "Sell some liquid assets"
 * triggers the margin call, and the two rows sit one above the other so you can
 * see why. The strip underneath carries it through to the number that matters. */
function fundingChart(f) {
  const c = (f.numbers.collateral || {}).chart;
  if (!c) return "";
  const rows = c.rows, unit = c.unit;
  const maxTicks = Math.max(...rows.map(r => Math.ceil(r.amount / unit))) || 1;

  /* Compact by construction: the argument is a comparison of six lengths, so
   * the rows are only as tall as a tick needs and the whole figure is capped in
   * CSS. A chart that fills a screen to say one sentence is a chart that makes
   * the reader work for nothing. */
  const W = 900, L = 190, R = 92, T = 16, rowH = 28, px = (W - L - R) / maxTicks;
  const H = T + rows.length * rowH + 58;
  const amt = v => c.currency + " " + (Math.abs(v) >= 1e6
    ? (v / 1e6).toFixed(1) + "m" : Math.round(v / 1e3) + "k");
  const jit = (k, i) => ((k * 7 + i * 13) % 11) / 11;

  const ltv = c.ltv, top = Math.max(ltv.after_pct || 0, ltv.trigger_pct) * 1.12;
  const sy = T + rows.length * rowH + 22;
  const sx = v => L + (v / top) * (W - L - R);

  return `<figure class="fchart wide fund" data-reveal>
    <svg viewBox="0 0 ${W} ${H}" role="img"
        aria-label="Six amounts in ${c.currency}: what is owed, what is free of any
          pledge, the daily-sellable collateral and its lending value, what the sale
          releases, and what must be repaid first.">
      ${rows.map((r, i) => {
        const y = T + i * rowH + 14;
        const n = Math.round(r.amount / unit);
        const tone = r.tone === "alert" ? P.ALERT : P.DATA;
        const ticks = [];
        for (let k = 0; k < n; k++) {
          const x = L + k * px + px / 2, h = 7 + jit(k, i) * 5;
          ticks.push(`<line x1="${x.toFixed(1)}" y1="${y}" x2="${x.toFixed(1)}"
            y2="${(y - h).toFixed(1)}" stroke="${tone}" stroke-width="1"
            opacity="${(0.55 + jit(k + 3, i) * 0.45).toFixed(2)}"/>`
            + (k % 5 === 4 ? `<circle cx="${x.toFixed(1)}" cy="${y + 3.2}" r="0.8"
                 fill="${P.FAINT}"/>` : ""));
        }
        return `<g class="lrow" style="--i:${i}">
          <text class="tr-nm" x="${L - 12}" y="${y + 3}" text-anchor="end">${
            esc(r.label)}</text>
          <line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${P.TRACK}"
            stroke-width="0.7"/>
          ${ticks.join("")}
          <text class="tr-val ${r.tone}" x="${(L + Math.max(n, 1) * px + 10).toFixed(1)}"
            y="${y + 4}">${n ? amt(r.amount) : "none"}</text>
        </g>`;
      }).join("")}

      <line x1="${L}" y1="${sy - 10}" x2="${W - R}" y2="${sy - 10}"
        stroke="${P.GRID}" stroke-width="1"/>
      <text class="tr-nm" x="${L - 12}" y="${sy + 12}" text-anchor="end">Loan to value</text>
      <line x1="${L}" y1="${sy + 8}" x2="${(W - R).toFixed(1)}" y2="${sy + 8}"
        stroke="${P.TRACK}" stroke-width="3.5"/>
      <line x1="${L}" y1="${sy + 8}" x2="${sx(ltv.before_pct).toFixed(1)}" y2="${sy + 8}"
        stroke="${P.DATA}" stroke-width="3.5"/>
      <line class="draw" x1="${sx(ltv.before_pct).toFixed(1)}" y1="${sy + 8}"
        x2="${sx(ltv.after_pct || top).toFixed(1)}" y2="${sy + 8}"
        stroke="${P.ALERT}" stroke-width="3.5"/>
      <line x1="${sx(ltv.trigger_pct).toFixed(1)}" y1="${sy - 1}"
        x2="${sx(ltv.trigger_pct).toFixed(1)}" y2="${sy + 17}"
        stroke="${P.HERO}" stroke-width="1.4" stroke-dasharray="3 3"/>
      <text class="tr-trig" x="${(sx(ltv.trigger_pct) + 5).toFixed(1)}" y="${sy - 3}">${
        ltv.trigger_pct}% trigger</text>
      <text class="tr-val" x="${(sx(ltv.before_pct) - 7).toFixed(1)}" y="${sy - 3}"
        text-anchor="end">${ltv.before_pct}% today</text>
      <text class="tr-val alert" x="${(sx(ltv.after_pct || top) + 7).toFixed(1)}"
        y="${sy + 12}">${ltv.after_pct === null ? "a full margin call"
          : ltv.after_pct + "% after the sale"}</text>

      <text class="rule" x="${L}" y="${H - 6}">ONE TICK =
        ${esc(c.currency)} ${(unit / 1e6).toFixed(unit >= 1e6 ? 1 : 2)}M &#183; DOT MARKS
        EVERY FIFTH &#183; LENDING VALUE IS NOT MARKET VALUE</text>
    </svg>
    ${repayLadder(f)}
    <figcaption>The third row and the fourth are the finding. Daily-sellable collateral
      is worth ${amt(rows[2].amount)} at market and ${amt(rows[3].amount)} as security,
      so raising ${amt(rows[0].amount)} against it removes more borrowing capacity than
      the sale brings in. "Sell some liquid assets" is what causes the margin call.</figcaption>
  </figure>`;
}


/* Where the repayment figure comes from.
 *
 * "He would have to repay about HKD 29.9m first" was asserted and nowhere
 * derived, which is the one thing this product is not allowed to do. The
 * confusion it caused is specific and worth naming: the repayment is *not* the
 * shortfall. It is how far his existing debt overshoots what the collateral pool
 * can carry once the sale has shrunk it — the debt does not move, the security
 * behind it does. Steps come from `liquidity`, not from here. */
function repayLadder(f) {
  const c = f.numbers.collateral || {};
  if (!c.steps || !c.steps.length) return "";
  const ccy = c.currency;
  const amt = v => ccy + " " + (Math.abs(v) >= 1e6
    ? (Math.abs(v) / 1e6).toFixed(1) + "m"
    : Math.round(Math.abs(v)).toLocaleString("en-US"));
  return `<details class="repay">
    <summary>How ${esc(amt(c.repay_first))} was worked out</summary>
    <ol class="repay-steps">
      ${c.steps.map((st, i) => `<li${i === c.steps.length - 1 ? ' class="last"' : ""}>
        <span class="rs-op n">${esc(st.op || "")}</span>
        <span class="rs-lab">${esc(st.label)}${st.note
          ? `<em>${esc(st.note)}</em>` : ""}</span>
        <span class="rs-val n">${esc(amt(st.value))}</span></li>`).join("")}
    </ol>
    <p class="repay-note">The repayment is not the shortfall. The debt does not move when
      the collateral is sold — the security behind it does, and by more than the sale
      raises. What must be repaid is the distance between what is owed and what the
      smaller pool can carry at the trigger.</p>
  </details>`;
}

/* F12 Dumbbell Queue, adapted — lieflat-charts `basics-gallery.html`, card C8.
 * Each income position runs from today to the year it matures, terminating in
 * a bead; the client's horizon cuts across. A row crossing the line is money
 * they cannot wait for. */
function maturityLadder(f) {
  const rows = f.numbers.ladder, hz = f.numbers.horizon_end, y0 = f.numbers.today_year;
  const real = rows.map(r => r.maturity).filter(Boolean);
  const last = Math.max(hz + 4, ...(real.length ? real : [hz + 4]));
  // The horizon label sits on its own row above the year labels; at T = 40
  // the two shared one and "Horizon ends 2036" ran into "2035" and "2040".
  const W = 780, L = 258, R = 78, T = 56, rowH = 32;
  const H = T + rows.length * rowH + 30;
  const X = yr => L + ((Math.min(yr, last) - y0) / (last - y0)) * (W - L - R);
  const ticks = [];
  for (let v = Math.ceil(y0 / 5) * 5; v <= last; v += 5) ticks.push(v);
  const beyond = rows.filter(r => r.beyond);
  const big = beyond.length
    ? beyond.reduce((a, b) => (b.weight_pct > a.weight_pct ? b : a)) : null;

  return `<figure class="fchart" data-reveal>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Maturity of each dated income position
        against a horizon ending ${hz}. ${beyond.length} of ${rows.length} mature after it.">
      ${ticks.map(v => `<line x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${T - 10}"
          y2="${H - 26}" stroke="${P.TRACK}" stroke-width="1"/>
        <text x="${X(v).toFixed(1)}" y="${T - 16}" text-anchor="middle">${v}</text>`).join("")}

      ${[[T - 36, T - 27], [T - 9, H - 24]].map(([a, b]) => `<line x1="${X(hz).toFixed(1)}"
        x2="${X(hz).toFixed(1)}" y1="${a}" y2="${b}" stroke="${P.HERO}" stroke-width="1.8"
        stroke-dasharray="3 3"/>`).join("")}
      <text class="hz" x="${(X(hz) + 7).toFixed(1)}" y="${T - 40}">Horizon ends ${hz}</text>

      ${rows.map((r, i) => {
        const y = T + i * rowH + 12;
        const end = r.perpetual ? W - R : X(r.maturity);
        const tone = r.beyond ? (r === big ? P.ALERT : P.DATA) : P.FAINT;
        return `<g class="lrow" style="--i:${i}">
          <text class="nm" x="${L - 14}" y="${(y + 4).toFixed(1)}" text-anchor="end">${
            esc(r.instrument.length > 40 ? r.instrument.slice(0, 39) + "\u2026" : r.instrument)}</text>
          <line x1="${X(y0).toFixed(1)}" y1="${y}" x2="${end.toFixed(1)}" y2="${y}"
            stroke="${tone}" stroke-width="${r.beyond ? 2.5 : 1.5}"
            ${r.perpetual ? 'stroke-dasharray="5 3"' : ""}/>
          ${r.perpetual
            ? `<text class="never" x="${(end + 6).toFixed(1)}" y="${(y + 4).toFixed(1)}">never</text>`
            : `<circle cx="${end.toFixed(1)}" cy="${y}" r="4" fill="${tone}"/>`}
          <text class="wt" x="${W - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${
            r.weight_pct.toFixed(1)}%</text>
        </g>`;
      }).join("")}
    </svg>
    <figcaption>Dated income positions only; bond funds carry no stated maturity.
      Width is time, not size — the figure at the right is each position's share of total wealth.</figcaption>
  </figure>`;
}

/* F2 Hairline Line — loan-to-value across the five snapshots against the
 * trigger that matters. Breaches are filled red and enlarged. */
function ltvPath(f) {
  const path = f.numbers.path, trig = f.numbers.trigger_pct;
  const W = 700, H = 210, L = 40, R = 54, T = 26, Bm = 40;
  const vals = path.map(p => p.ltv).concat([trig]);
  const hi = Math.ceil(Math.max(...vals) / 10) * 10 + 6;
  const lo = Math.max(0, Math.floor(Math.min(...vals) / 10) * 10 - 6);
  const X = i => L + (i / (path.length - 1)) * (W - L - R);
  const Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - Bm);
  const line = path.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.ltv).toFixed(1)}`).join("");

  return `<figure class="fchart" data-reveal>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Loan to value across five snapshots against
        a ${trig} percent margin trigger.">
      <line x1="${L}" x2="${W - R}" y1="${Y(trig).toFixed(1)}" y2="${Y(trig).toFixed(1)}"
        stroke="${P.ALERT}" stroke-width="1.8" stroke-dasharray="3 3"/>
      <text class="trig" x="${W - R + 6}" y="${(Y(trig) + 4).toFixed(1)}">${trig}% trigger</text>
      <line x1="${L}" x2="${W - R}" y1="${H - Bm}" y2="${H - Bm}" stroke="${P.GRID}" stroke-width="1"/>
      <path class="draw" d="${line}" fill="none" stroke="${P.DATA}" stroke-width="2.5"
        stroke-linejoin="round"/>
      ${path.map((p, i) => {
        const breach = p.ltv >= trig;
        return `<g class="lrow" style="--i:${i}">
          <circle cx="${X(i).toFixed(1)}" cy="${Y(p.ltv).toFixed(1)}" r="${breach ? 5 : 3.5}"
            fill="${breach ? P.ALERT : P.BG}" stroke="${breach ? P.ALERT : P.DATA}"
            stroke-width="1.8"/>
          <text class="val ${breach ? "breach" : ""}" x="${X(i).toFixed(1)}"
            y="${(Y(p.ltv) - 12).toFixed(1)}" text-anchor="middle">${p.ltv.toFixed(1)}%</text>
          <text x="${X(i).toFixed(1)}" y="${H - Bm + 17}" text-anchor="middle">${
            dateShort(p.date)}</text>
          <text x="${X(i).toFixed(1)}" y="${H - Bm + 29}" text-anchor="middle">${
            p.date.slice(0, 4)}</text>
        </g>`;
      }).join("")}
    </svg>
    <figcaption>Loan-to-value is drawn against <em>lending value</em> — market value after per-asset
      advance-rate haircuts — not raw market value.</figcaption>
  </figure>`;
}

/* ── screen 2 · the dossier ─────────────────────────────────────────────
 * Three tabs, because the page was one column of everything and the RM has
 * three different jobs on it: decide what to raise, look at the money, and
 * remember who the person is. Tabs also let each one use the full width — the
 * prose keeps its reading measure and the space beside it now carries the
 * evidence instead of standing empty. */
/* Named the way the RM would say them, not the way the engine thinks about
 * them. "What we would raise" was the engine's voice and three words too long. */
const TABS = [
  ["raise", "To raise"],
  ["money", "Portfolio"],
  ["shock", "Scenario analysis"],
  ["context", "Context"],
];

function openClient(cid) {
  state.view = "client"; state.client = cid; state.tab = "raise"; state.shock = 0;
  renderClient();
  window.scrollTo(0, 0);
}

/* Days until a date, from the snapshot. Nothing else in the app needs to know
 * about "soon", so the threshold lives with its only caller. */
function daysUntil(d) {
  return Math.round((new Date(d + "T00:00:00Z") - new Date(B.today + "T00:00:00Z"))
                    / 86400000);
}

function renderClient() {
  const cid = state.client;
  const C = B.clients[cid];
  const p = C.profile;
  const row = BOOK[cid];
  const perf = C.performance;
  const mine = B.findings.filter(f => f.client_id === cid && f.status !== "waived")
    .sort((a, b) => b.severity - a.severity);
  const governed = B.findings.filter(f => f.client_id === cid && f.status === "waived");
  const kyc = p.kyc_review_due ? daysUntil(p.kyc_review_due) : null;

  document.getElementById("view").innerHTML = `
  <a class="back" href="#" id="back">&larr; The book</a>

  <div class="dossier-head">
    <h1>${esc(p.client_name)}</h1>
    <div class="facts">
      <span class="fkey">Who</span>
      <span class="n">${esc(p.client_id)}</span>
      <span>${p.age ? esc(p.age) + ", " : ""}${esc(p.nationality)}</span>
      <span>Resident <b>${esc(p.country_of_residence)}</b></span>
      <span>Taxed <b>${esc(p.tax_domicile)}</b>${
        p.country_of_residence !== p.tax_domicile ? " (not residence)" : ""}</span>
      <span>Booked <b>${esc(p.booking_centre)}</b></span>
      ${p.reporting_language && p.reporting_language !== "English"
        ? `<span>Reads <b>${esc(p.reporting_language)}</b></span>` : ""}
    </div>
    <div class="facts second">
      <span class="fkey">Relationship</span>
      <span>Client since <b>${esc((p.client_since || "").slice(0, 4))}</b></span>
      ${p.kyc_review_due ? `<span class="${kyc <= 90 ? "due-soon" : ""}">KYC review
        <b>${esc(dateLong(p.kyc_review_due))}</b>${
          kyc < 0 ? " — overdue" : kyc <= 90 ? ` — in ${kyc} days` : ""}</span>` : ""}
      ${p.pep_status && p.pep_status !== "No" ? `<span class="due-soon">PEP
        <b>${esc(p.pep_status)}</b></span>` : ""}
      <span>Risk profile <b>${esc(p.risk_profile)}</b>, ${esc(p.risk_tolerance_score)}/10</span>
      <span>${esc(p.liquidity_needs)} liquidity need</span>
      <span>Horizon <b>${esc(p.investment_horizon_years)}y</b></span>
    </div>

    <div class="stat-row">
      <div><div class="v n">${usd2(C.wealth_usd)}</div><div class="k">Total wealth, USD</div></div>
      <div><div class="v n ${perf.return_on_cost_pct < 0 ? "alert" : "pos"}">${
        perf.return_on_cost_pct > 0 ? "+" : ""}${perf.return_on_cost_pct.toFixed(1)}%</div>
        <div class="k">Unrealised return on cost</div></div>
      <div><div class="v n">${usd2(C.daily_liquid_usd)}</div>
        <div class="k">Sellable at daily liquidity, USD</div></div>
      <div><div class="v n">${mine.length}</div>
        <div class="k">Open finding${mine.length === 1 ? "" : "s"}</div></div>
      <div><div class="v n">${row && row.rank ? row.rank : "—"}</div><div class="k">Rank in the book</div></div>
    </div>

    <div class="tabs" role="tablist">
      ${TABS.map(([k, name]) => `<button role="tab" data-tab="${k}"
        aria-selected="${state.tab === k}">${esc(name)}${
        k === "raise" && mine.length ? `<b>${mine.length}</b>` : ""}</button>`).join("")}
    </div>
  </div>

  ${state.tab === "raise" ? tabRaise(mine, governed)
    : state.tab === "money" ? tabMoney(C, perf)
    : state.tab === "shock" ? tabShock(C)
    : tabContext(C, p)}`;

  document.getElementById("back").addEventListener("click", e => {
    e.preventDefault(); state.view = "book"; renderBook(); window.scrollTo(0, 0);
  });
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.addEventListener("click", () => {
      state.tab = b.dataset.tab; renderClient();
      document.querySelector(".tabs").scrollIntoView({ block: "start" });
    }));
  document.querySelectorAll("[data-shock]").forEach(b =>
    b.addEventListener("click", () => { state.shock = +b.dataset.shock; renderClient(); }));
  document.querySelectorAll("[data-goshock]").forEach(g => {
    const go = () => {
      state.shock = +g.dataset.goshock; state.tab = "shock"; renderClient();
      document.querySelector(".tabs").scrollIntoView({ block: "start" });
    };
    g.addEventListener("click", go);
    g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") go(); });
  });
  wireFindings();
  wireMoney();
  wireNotes();
  armReveal();
}

/* ── tab 1 · what we would raise ──────────────────────────────────────── */
function tabRaise(mine, governed) {
  return `<section class="section">
    <p class="sub">Ordered by severity. Every figure opens to the rule that produced it, the rows
      it read, and anything ${esc(RM_FIRST)} has already written about it.</p>
    ${mine.length ? mine.map(f => finding(f)).join("")
      : `<p class="empty">Nothing outstanding across any dimension.</p>`}
    ${governed.length ? `
      <h2 style="margin-top:46px">Governed, and deliberately not raised</h2>
      <p class="sub">A breach the client waived in writing is not an action item. Shown for the
        record &mdash; and carrying no plan on purpose: proposing trades against a written
        instruction is how an RM stops trusting the tool.</p>
      ${governed.map(f => finding(f, true)).join("")}` : ""}
  </section>`;
}

/* ── tab 2 · positions and performance ────────────────────────────────── */
function tabMoney(C, perf) {
  return `
  <section class="section">
    <h2>How the money has done</h2>
    <p class="sub">Two different numbers, and they answer different questions. Return on cost is
      since each position was bought; the period figure is what the five snapshots show.</p>

    <div class="perf-row">
      <div><div class="v n">${usd2(perf.cost_usd)}</div>
        <div class="k">Cost base — what the book was bought for</div></div>
      <div><div class="v n ${perf.unrealised_usd < 0 ? "alert" : "pos"}">${
        signed(perf.unrealised_usd)}</div>
        <div class="k">Unrealised, ${perf.return_on_cost_pct > 0 ? "+" : ""}${
          perf.return_on_cost_pct.toFixed(1)}% on cost</div></div>
      <div><div class="v n ${perf.period_change_usd < 0 ? "alert" : "pos"}">${
        signed(perf.period_change_usd)}</div>
        <div class="k">Wealth across the period, ${perf.period_change_pct > 0 ? "+" : ""}${
          perf.period_change_pct.toFixed(1)}%</div></div>
      <div><div class="v n">${usd2(perf.income_usd)}</div>
        <div class="k">Income received in the period</div></div>
      <div><div class="v n">${usd2(Math.abs(perf.costs_usd))}</div>
        <div class="k">Fees and interest charged</div></div>
      ${perf.external_usd ? `<div><div class="v n">${signed(perf.external_usd)}</div>
        <div class="k">Client money in and out</div></div>` : ""}
    </div>
    <p class="foot-note">Wealth across the period is the observed total at each snapshot. The
      cash figures beside it are what the transaction log records; together they do not add to a
      full attribution, and the workbench does not pretend they do.</p>
  </section>

  <section class="section">
    <h2>Wealth through the period, and what was happening</h2>
    <p class="sub">Five dated snapshots, on a real time axis &mdash; everything between them
      is inferred, not observed. Numbered markers are events from <code>event_log.csv</code>
      that reach this client's own holdings; click one to read the window. Right of the
      dashed rule is not a continuation of the line and not a forecast: it is today's
      wealth repriced instantaneously under the widest and the mildest of the four stated
      shocks. Click either to open the scenario.</p>
    <div class="chart" data-reveal>${wealthPath(C, perf)}</div>
    <div id="stepPanel">${stepPanel(perf, state.step)}</div>
  </section>

  <section class="section">
    <h2>What moved the return</h2>
    <p class="sub">From nothing to the return on cost, one position at a time. Each step is
      that holding's unrealised profit or loss in points of the same return, so the steps
      land exactly on the net — nothing is hidden in a residual.</p>
    ${contribWaterfall(perf)}
  </section>

  <section class="section">
    <h2>Where the money sits, and how that has changed</h2>
    <p class="sub">One ladder per snapshot, so five dated readings stay five dated readings.
      Custody accounts are included — they are the client's wealth even where no mandate
      governs them.</p>
    <div class="chart" data-reveal>${mixLadders(perf)}</div>
  </section>

  <section class="section">
    <h2>Positions</h2>
    <p class="sub">Every portfolio combined, including custody. ${
      C.portfolios.map(x => esc(x.portfolio_name) + " (" + esc(x.service_model) + ")").join(" · ")}</p>
    <div class="tbl-wrap">
      <table class="data">
        <thead><tr><th>Instrument</th><th>Liquidity</th>
          <th class="r">Weight</th><th class="r">Value USD</th><th class="r">Unrealised</th>
          <th class="r">Return</th><th class="r">Contribution</th></tr></thead>
        <tbody>${C.positions.map(x => {
          const c = perf.contributors.find(k => k.instrument_id === x.instrument_id) || {};
          return `<tr>
          <td><div>${esc(x.name)}${x.excluded ? ` <span class="tag crit">Excluded</span>` : ""}</div>
            <div class="sub">${esc(x.sub)} · ${esc(x.region)} · ${esc(x.currency)}${
              x.underlying ? " · " + esc(x.underlying) : ""}${
              x.stale_mark ? ` · <span class="alert">marked ${esc(x.stale_mark)}</span>` : ""}</div></td>
          <td>${esc(x.liquidity)}</td>
          <td class="r">${x.weight_pct.toFixed(1)}%</td>
          <td class="r">${usd2(x.market_value_usd)}</td>
          <td class="r ${x.unrealised_usd < 0 ? "alert" : "pos"}">${signed(x.unrealised_usd)}</td>
          <td class="r ${c.return_pct < 0 ? "alert" : "pos"}">${
            c.return_pct === undefined ? "—" : (c.return_pct > 0 ? "+" : "") + c.return_pct.toFixed(1) + "%"}</td>
          <td class="r n ${c.contribution_pp < 0 ? "alert" : "pos"}">${
            c.contribution_pp === undefined ? "—"
              : (c.contribution_pp > 0 ? "+" : "") + c.contribution_pp.toFixed(2) + "pp"}</td>
        </tr>`; }).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

/* A finding that does not fire leaves nothing on the screen, and nothing on the
 * screen is indistinguishable from nobody having looked. This says which. */
function fundingVerdict(fn) {
  if (!fn.need_12m_usd) {
    return `<p class="verdict quiet">Nothing falls due inside twelve months.</p>`;
  }
  const tight = fn.reported;
  return `<p class="verdict ${tight ? "loud" : "quiet"}">
    <b>${usd2(fn.need_12m_usd)}</b> falls due inside twelve months against
    <b>${usd2(fn.daily_liquid_usd)}</b> sellable at daily liquidity —
    <b class="n">${fn.cover_x}×</b> cover.
    ${tight
      ? `The funding rule reports below 3× and has raised it; the finding is under
         <em>To raise</em>.`
      : `The funding rule reports below 3×, so it stays silent for this client. Silence
         here means covered, not unexamined.`}</p>`;
}

/* ── Module F, the stated shock ───────────────────────────────────────────
 * Nothing here forecasts. A scenario is a vector of price moves somebody has
 * asserted, and this shows the arithmetic that follows. No probability is
 * attached and none is implied — the copy says "if", never "will", and every
 * scenario carries the event it is drawn from and the caveat on its own
 * construction. From engine/scenario.py. */
function tabShock(C) {
  const list = C.scenarios || [];
  if (!list.length) return `<section class="section"><p class="empty">No scenarios.</p></section>`;
  const s = list[Math.min(state.shock, list.length - 1)] || list[0];
  const p = B.clients[state.client].profile;
  const down = s.delta_usd < 0;

  return `<section class="section">
    <h2>If this happened</h2>
    <p class="sub">A stated shock, repriced &mdash; not a forecast. None of these has
      happened to the portfolio as it stands today. What the event log supplies is the
      <em>size</em> of a move of this kind when one actually occurred, so the vector is
      calibrated rather than invented; the arithmetic is then run against
      ${esc(p.client_name.split(" ")[0])}'s holdings at
      ${esc(dateLong(B.today))}, which are not the holdings that took the original
      move. No probability is attached to any of them.</p>

    <div class="shock-pick" role="tablist">
      ${list.map((x, i) => `<button role="tab" data-shock="${i}"
        aria-selected="${i === state.shock}">${esc(x.name)}${
        x.asked_by === p.client_id ? `<i>asked for it</i>` : ""}</button>`).join("")}
    </div>

    <div class="shock">
      <div class="shock-top">
        <div class="sh-fig">
          <div class="v n ${down ? "alert" : "pos"}">${
            s.delta_pct > 0 ? "+" : ""}${s.delta_pct.toFixed(1)}%</div>
          <div class="k">${usd2(s.before_usd)} &rarr; ${usd2(s.after_usd)},
            ${signed(s.delta_usd)}</div>
        </div>
        <div class="sh-fig">
          <div class="v n">${s.reached_pct}%</div>
          <div class="k">of wealth the stated channels reach; ${s.untouched_count}
            holdings are untouched and are shown as such</div>
        </div>
      </div>

      <p class="sh-premise">${esc(s.premise)}</p>
      <p class="sh-meta"><span class="eyebrow">Drawn from</span> ${esc(s.mirrors)}</p>
      <p class="sh-caveat"><span class="eyebrow">What this gets wrong</span>
        ${esc(s.caveat)}</p>

      ${s.collateral.map(c => `<p class="sh-ltv ${c.breaches ? "bad" : "ok"}">
        <b>${esc(c.facility)}</b> would move <b class="n">${c.ltv_before_pct}%</b> &rarr;
        <b class="n">${c.ltv_after_pct === null ? "a full margin call"
          : c.ltv_after_pct + "%"}</b> against a ${c.trigger_pct}% trigger${
        c.breaches ? ` — <b>through it.</b> ${esc(p.client_name.split(" ")[0])} would need
          about ${usd2(c.shortfall)} back before anything else happens. Lending value
          moves with the collateral, which is the part that never appears on a
          statement.` : ". The collateral takes the shock and the facility holds."}</p>`)
        .join("")}

      ${s.bands.length ? `<div class="sh-bands">
        <span class="eyebrow">Mandate bands this would cross</span>
        ${s.bands.map(b => `<div class="sh-band ${b.crosses}">
          <b>${esc(b.asset_class)}</b> in ${esc(b.portfolio)}
          <span class="n">${b.before_pct}% &rarr; ${b.after_pct}%</span>
          <span class="sh-cross">${b.crosses === "out"
            ? "out of its " + b.band[0] + "–" + b.band[1] + "% band"
            : "back inside its " + b.band[0] + "–" + b.band[1] + "% band"}</span>
        </div>`).join("")}</div>` : ""}

      <div class="tbl-wrap"><table class="data shock-table">
        <thead><tr><th>What moves</th><th class="r">Weight</th><th class="r">Move</th>
          <th class="r">Value change</th><th>Down which channel</th></tr></thead>
        <tbody>${s.positions.map(r => `<tr>
          <td>${esc(r.instrument)}<div class="sub">${esc(r.asset_class)}</div></td>
          <td class="r n dim">${r.weight_pct.toFixed(1)}%</td>
          <td class="r n ${r.move_pct < 0 ? "alert" : "pos"}">${
            r.move_pct > 0 ? "+" : ""}${r.move_pct.toFixed(1)}%</td>
          <td class="r n ${r.delta_usd < 0 ? "alert" : "pos"}">${signed(r.delta_usd)}</td>
          <td class="sh-chan">${r.channels.map(c => `<span class="sh-ch">${esc(c.channel)}
            <b class="n">${c.pct > 0 ? "+" : ""}${c.pct}%</b>
            <i>${esc(c.why)}</i></span>`).join("")}</td>
        </tr>`).join("")}</tbody>
      </table></div>

      <p class="foot-note">Channels are additive: a shipping company the shipping and
        energy channels both reach takes both moves, and the last column says so.
        Nothing is netted against a hedge, because the dataset does not record hedges.
        Nothing here executes, and nothing here is a view on what will happen.</p>
    </div>
  </section>`;
}

/* ── tab 3 · context ──────────────────────────────────────────────────── */
function tabContext(C, p) {
  const own = (state.notes[p.client_id] || []).slice().reverse();
  return `
  <section class="section">
    <h2>Who this is</h2>
    <p class="sub">The standing facts. Everything the engine reasons about a client's
      <em>purpose</em> — horizon, drawdown, life stage — starts here.</p>
    <dl class="who">
      <div><dt>Life stage</dt><dd>${esc(p.life_stage)}</dd></div>
      <div><dt>Source of wealth</dt><dd>${esc(p.source_of_wealth)}</dd></div>
      <div><dt>Objectives</dt><dd>${esc(p.objectives)}</dd></div>
      <div><dt>Risk</dt><dd>${esc(p.risk_profile)}, scored ${esc(p.risk_tolerance_score)}/10,
        horizon ${esc(p.investment_horizon_years)} years, ${esc(p.liquidity_needs)}
        liquidity need</dd></div>
      <div><dt>Booking and tax</dt><dd>Booked ${esc(p.booking_centre)}, resident
        ${esc(p.country_of_residence)}, taxed ${esc(p.tax_domicile)}${
          p.country_of_residence !== p.tax_domicile
            ? " — the two differ, and every tax finding gates on the second"
            : ""}</dd></div>
      <div><dt>Reporting</dt><dd>${esc(p.base_currency)}, in
        ${esc(p.reporting_language)}${p.reporting_language !== "English"
          ? " — every client note is written in " + esc(p.reporting_language)
            + " as well as English, and the composer opens on the version that gets sent"
          : ""}</dd></div>
      <div><dt>Relationship</dt><dd>Client since ${esc(dateLong(p.client_since))}, KYC review
        due ${esc(dateLong(p.kyc_review_due))}${
          p.pep_status && p.pep_status !== "No" ? ", PEP " + esc(p.pep_status) : ""}</dd></div>
    </dl>
  </section>

  ${C.funding.needs.length || C.commitments.length ? `<section class="section">
    <h2>What has been promised, and whether it is covered</h2>
    <p class="sub">Dated obligations on the file. Amounts are in the currency they were
      recorded in; the engine converts before it compares them to anything.</p>

    ${fundingVerdict(C.funding)}

    <div class="tbl-wrap"><table class="data">
      <thead><tr><th>What</th><th>Next due</th><th>Certainty</th>
        <th class="r">Amount</th><th class="r">Share</th><th class="r">Cover</th>
        <th></th></tr></thead>
      <tbody>
        ${C.funding.needs.map(n => `<tr>
          <td><div>${esc(n.description)}</div>${
            n.next_due !== n.first_due ? `<div class="sub">${esc(n.recurrence)} — first due
              ${esc(n.first_due)}</div>` : ""}</td>
          <td class="n">${esc(dateLong(n.next_due))}</td>
          <td>${esc(n.certainty)}${n.recurrence && n.recurrence !== "One-off"
            ? " · " + esc(n.recurrence) : ""}</td>
          <td class="r n">${esc(n.currency)} ${Number(n.amount).toLocaleString("en-US")}</td>
          <td class="r n dim">${n.share_pct.toFixed(1)}%</td>
          <td class="r n">${n.cover_x === null ? "—" : n.cover_x + "×"}</td>
          <td><span class="cover-${n.status.split(" ")[0].toLowerCase()}">${
            esc(n.status)}</span></td></tr>`).join("")}
        ${C.commitments.map(c => `<tr><td>${esc(c.fund_name)} — uncalled commitment</td>
          <td class="n">${esc(c.expected_call_window)}</td><td>Contractual</td>
          <td class="r n">${esc(c.currency)} ${Number(c.uncalled).toLocaleString("en-US")}</td>
          <td class="r dim">—</td><td class="r dim">—</td><td></td></tr>`).join("")}
      </tbody></table></div>
    <p class="foot-note">Cover on each row is this client's whole daily-liquid pool against
      that one obligation, so the rows do not add up — a client can be comfortable against
      every line and short against all of them at once. The figure the rule uses is the
      aggregate above.</p>
  </section>` : ""}

  <section class="section">
    <h2>What ${esc(RM_FIRST)} wrote</h2>
    <p class="sub">Partial, subjective, and occasionally in tension with the numbers — which is
      usually where the advice is. The engine reads these: a waiver, a refusal or a health
      remark in here changes what it raises and how hard.</p>

    <form class="note-add" id="noteAdd">
      <label class="eyebrow" for="noteText">Add a note</label>
      <textarea id="noteText" rows="3"
        placeholder="What was said, and when. Written as though the next RM will read it."></textarea>
      <div class="note-actions">
        <select id="noteChannel">
          <option>Call</option><option>Meeting</option><option>Email</option>
          <option>Message</option><option>Internal</option>
        </select>
        <button class="btn" type="submit">Save to the file</button>
      </div>
      <p class="note-warn">Notes added here live in this browser. They are shown to the engine's
        readers but they are not in <code>rm_notes.json</code>, so they do not change a finding
        until they are written back to the source and the engine is re-run.</p>
    </form>

    ${own.map(n => `<article class="note own${n.from ? " filed" : ""}">
      <div class="meta">${esc(dateLong(n.date))} · ${esc(n.channel)} ·
        ${n.from ? `${esc(n.verdict)} from <em>${esc(n.headline)}</em>`
                 : "added in the workbench"}
        <button class="note-del" data-del-note="${esc(n.id)}">Delete</button></div>
      <p>${esc(n.note)}</p></article>`).join("")}

    ${C.notes.length ? C.notes.map(n => `<article class="note">
      <div class="meta">${esc(dateLong(n.note_date))} · ${esc(n.channel)} · ${esc(n.note_id)}</div>
      <p>${esc(n.note)}</p></article>`).join("")
      : own.length ? "" : `<p class="empty">Nothing on file.</p>`}
  </section>`;
}

/* Two rules describing one obligation. Both cards stay — a dated promise being
 * large and that promise being unpayable are different claims with different
 * actions — but neither should read as a second, independent problem. The
 * weaker of the pair carries `same_fact_as` from the engine and says so; the
 * stronger names its partner too, so the link reads in both directions. */
function sameFact(f) {
  const peer = f.same_fact_as ? F[f.same_fact_as] : null;
  if (peer) {
    return `<p class="samefact"><span class="eyebrow">The same obligation</span>
      This is the money <b>${esc(peer.label.toLowerCase())}</b> is about, above &mdash;
      &ldquo;${esc(peer.headline)}&rdquo;. Two rules, one promise: it counts once
      toward this client's rank.
      <button class="sf-go" data-goto-finding="${esc(peer.id)}">Go to it</button></p>`;
  }
  const back = B.findings.filter(x => x.same_fact_as === f.id);
  if (!back.length) return "";
  return `<p class="samefact quiet"><span class="eyebrow">The same obligation</span>
    Also reported as <b>${esc(back.map(x => x.label.toLowerCase()).join(" and "))}</b>
    below. Different question, same money &mdash; counted once.</p>`;
}

/* one finding, as an editorial block */
function finding(f, governed) {
  const d = state.decisions[f.id];
  return `<article class="finding${governed ? " governed" : ""}" id="f-${esc(f.id)}">
    <div class="finding-top">
      <span class="tag${f.severity >= 80 ? " crit" : " on"}">${esc(f.label)}</span>
      <button class="sev" data-sev="${esc(f.id)}" title="How this number was built">severity ${
        f.severity.toFixed(0)}<i aria-hidden="true">?</i></button>
      ${f.status === "waived" ? `<span class="tag">Waiver on file</span>` : ""}
      ${f.status === "directed" ? `<span class="tag">Client-directed</span>` : ""}
      ${f.confidence !== "high" ? `<span class="confidence">${
        f.confidence === "check" ? "Needs checking" : "Partly unconfirmed"}</span>` : ""}
      <h3>${esc(f.headline)}</h3>
    </div>
    <p class="body">${esc(f.detail)}</p>
    ${sameFact(f)}
    ${f.check ? `<p class="body" style="margin-top:9px"><span class="confidence">What we would check &mdash;
      ${esc(f.check)}</span></p>` : ""}
    <div class="do"><span class="eyebrow">Suggested action</span>${esc(f.action)}</div>
    ${planBlock(f)}
    ${findingChart(f)}

    ${d ? `<div class="decided"><b>${esc(d.verdict)}</b> by ${esc(RM_FIRST)} on ${esc(d.at)}${
      d.reason ? ` &mdash; &ldquo;${esc(d.reason)}&rdquo;` : ""}</div>` : ""}

    ${governed ? "" : `<div class="btn-row">
      <button class="btn" data-draft="${esc(f.id)}">Draft the client note</button>
      ${d ? `<button class="btn ghost" data-reopen="${esc(f.id)}">Reopen</button>` : ""}
    </div>`}

    <details class="why">
      <summary>Why this fired, and where the numbers came from</summary>
      <div class="why-inner"><dl>
        <dt>Severity</dt><dd>${severityLadder(f)}</dd>
        <dt>Rule</dt><dd><code>${esc(f.rule_text)}</code></dd>
        ${planWhy(f)}
        <dt>Source rows</dt><dd><code>${f.source_rows.slice(0, 8).map(esc).join("<br>")}</code></dd>
        ${Object.keys(f.numbers).length ? `<dt>Values</dt><dd><div class="numgrid">${
          Object.entries(f.numbers).filter(([, v]) => typeof v !== "object")
            .map(([k, v]) => `<div>${esc(k.replace(/_/g, " "))} <b>${
              typeof v === "number" ? (Math.abs(v) >= 1e5 ? usd2(v) : v) : esc(v)}</b></div>`).join("")
          }</div></dd>` : ""}
        ${f.evidence.length ? `<dt>Evidence</dt><dd>${f.evidence.map(e =>
          `<div class="quote">&ldquo;${esc(e.quote)}&rdquo;
            <cite>${esc(e.note_id)} · ${esc(dateLong(e.date))} · ${esc(e.channel)} · ${
              esc(e.type.replace(/_/g, " "))}</cite></div>`).join("")}</dd>` : ""}
      </dl></div>
    </details>
  </article>`;
}

/* Severity, taken apart. The engine records every step it took (Sev, in
 * engine/severity.py), so this shows the sum rather than asserting the total —
 * and then shows what the dimension weight does to it, because that is the
 * number the ranking actually uses. */
function severityLadder(f) {
  const b = f.severity_basis;
  if (!b || !b.steps || !b.steps.length) return "<span class='dim'>Not recorded.</span>";
  const w = cfg().weights[f.dimension];
  const weight = w === undefined ? 1 : w;
  return `<div class="sev-ladder">
    <div class="sl-driver">Driver &mdash; ${esc(b.driver)}</div>
    <ol class="sl-steps">
      ${b.steps.map(st => `<li>
        <span class="sl-op n">${esc(st.op || "base")}</span>
        <span class="sl-lab">${esc(st.label)}</span>
        <span class="sl-val n">${st.value}</span></li>`).join("")}
    </ol>
    ${b.capped ? `<p class="sl-note">Held at the ${b.ceiling} ceiling for this rule. Ceilings
      are deliberately not saturating &mdash; if everything reaches 100, the act tier stops
      meaning anything.</p>` : ""}
    <div class="sl-weight">
      <span>severity <b class="n">${f.severity.toFixed(1)}</b></span>
      <span>&times; ${esc(f.label.toLowerCase())} weight <b class="n">${weight.toFixed(2)}</b></span>
      <span>= <b class="n">${(f.severity * weight).toFixed(1)}</b> toward the client's rank</span>
      <button class="sl-tune" data-tune>Retune</button>
    </div>
  </div>`;
}

/* ── Module E, the constrained plan ───────────────────────────────────────
 * Rendered inside the finding that motivated it, from `engine/modules/
 * rebalance.py`. The whole point is the right-hand column: for every position
 * the plan does NOT touch, the rule that stopped it. A suggestion an RM cannot
 * interrogate is a suggestion she has to check by hand, which is no saving. */
const PLAN_VERB = { sell: "Trim", exit: "Exit", trim: "Trim", buy: "Buy" };

function planBlock(f) {
  const p = f.plan;
  if (!p) return "";
  const done = p.raised_usd >= p.excess_usd - p.min_trade_usd;

  if (p.kind === "buy") {
    return `<div class="plan">
      <div class="plan-head"><span class="eyebrow">What we would do</span>
        <b>Buy about ${usd2(p.excess_usd)}</b> of ${esc(p.asset_class)}</div>
      <p class="plan-note">${esc(p.note)}</p>
    </div>`;
  }

  return `<div class="plan">
    <div class="plan-head">
      <span class="eyebrow">What we would do</span>
      <b>${esc(PLAN_VERB[p.kind])} ${usd2(p.excess_usd)}</b> from ${esc(p.asset_class)}
      in ${esc(p.portfolio)}
      <span class="plan-arc n">${p.weight_pct.toFixed(1)}% &rarr; ${
        p.weight_after_pct.toFixed(1)}%${p.band
          ? ` &middot; band ${p.band[0]}–${p.band[1]}%` : ""}</span>
    </div>

    <table class="plan-table">
      <tbody>
        ${p.sells.map(s => `<tr class="do">
          <td class="pt-act">Sell</td>
          <td class="pt-nm">${esc(s.instrument)}${s.excluded
            ? ` <span class="tag crit">Excluded</span>` : ""}</td>
          <td class="r n">${usd2(s.usd)}</td>
          <td class="r n dim">${s.of_position_pct}% of it</td>
          <td class="pt-why">${esc(s.reason)}${s.capped_by
            ? ` <b>Capped by the margin trigger.</b>` : ""}</td>
        </tr>`).join("")}

        ${p.blocked.map(x => `<tr class="stop">
          <td class="pt-act">Not sold</td>
          <td class="pt-nm">${esc(x.instrument)}${x.excluded
            ? ` <span class="tag crit">Excluded</span>` : ""}</td>
          <td class="r n dim">${usd2(x.usd)}</td>
          <td class="r"><span class="pt-cons c-${esc(x.constraint)}">${
            esc(x.constraint)}</span></td>
          <td class="pt-why">${esc(x.why)}${x.quote
            ? `<span class="pt-quote">&ldquo;${esc(x.quote)}&rdquo;
               <cite>${esc(x.note_id)}</cite></span>` : ""}</td>
        </tr>`).join("")}

        ${p.buys.map(x => `<tr class="into">
          <td class="pt-act">Buy</td>
          <td class="pt-nm">${x.into ? esc(x.into)
            : `<span class="dim">${esc(x.asset_class)}</span>`}</td>
          <td class="r n">${usd2(x.usd)}</td>
          <td class="r n dim">${esc(x.asset_class)}</td>
          <td class="pt-why">${esc(x.note) || "into an existing holding, which is a "
            + "smaller decision than introducing a new security"}</td>
        </tr>`).join("")}
      </tbody>
    </table>

    ${p.collateral ? `<p class="plan-ltv ${
      p.collateral.ltv_after_pct >= p.collateral.trigger_pct ? "bad" : "ok"}">
      <b>${esc(p.collateral.facility)}</b> moves
      <b class="n">${p.collateral.ltv_before_pct}%</b> &rarr;
      <b class="n">${p.collateral.ltv_after_pct === null ? "a full margin call"
        : p.collateral.ltv_after_pct + "%"}</b>
      against a ${p.collateral.trigger_pct}% trigger. Selling collateral removes
      lending value and buying it back adds some in — the switch is modelled as one
      movement, because that is what it is.</p>` : ""}

    ${p.shortfall_usd > p.min_trade_usd ? `<p class="plan-short">
      <b>${usd2(p.shortfall_usd)} of the correction cannot be traded.</b>
      ${p.blocked.length
        ? "Everything that would close the gap is blocked above. This is a"
          + " conversation, not an instruction — and knowing that before the call"
          + " is the point."
        : "There is not enough daily-liquid holding in the class to close it."}</p>`
      : done ? `<p class="plan-ok">These trades bring the breach inside its limit.</p>` : ""}

    ${p.unresolved_claims.length ? `<p class="plan-note">
      ${p.unresolved_claims.length} note${p.unresolved_claims.length === 1 ? "" : "s"}
      on this client protect${p.unresolved_claims.length === 1 ? "s" : ""} a position the
      engine could not resolve to a line — read
      ${p.unresolved_claims.map(c => esc(c.note_id)).join(", ")} before acting.
      ${p.unresolved_claims.map(c => `<span class="pt-quote">&ldquo;${
        esc(c.quote)}&rdquo;</span>`).join("")}</p>` : ""}

  </div>`;
}

/* How the plan was made, for the fold-out under the card rather than on it:
 * the card says what to trade, the fold-out says why those trades and not
 * others. */
function planWhy(f) {
  const p = f.plan;
  if (!p) return "";
  return `<dt>The plan</dt><dd>${planBasis(f, p)}${p.kind === "buy" ? "" : `
    <p class="plan-foot">A constrained suggestion, not an optimiser: the smallest set of
      trades that brings this ${p.kind === "exit" ? "portfolio inside its exclusion list"
      : "band inside its limit"}, under four rules &mdash; sell only daily-liquid, never a
      gated position, never one the notes protect, never past a margin trigger. Nothing
      here executes.</p>`}</dd>`;
}

/* Where the client's risk profile enters. It is not a term in the plan and it
 * should not be: the profile is expressed once, as the mandate the household
 * signed, and the mandate's bands are what the plan reads. Saying so on the
 * card stops the obvious question — "does this know he is Conservative?" —
 * from having to be asked. What the plan genuinely does not read is the rest of
 * the profile: horizon, stated liquidity needs and tolerance score never reach
 * it, and those are named here rather than left to be discovered. */
function planBasis(f, p) {
  const prof = (B.clients[f.client_id] || {}).profile || {};
  return `<p class="plan-basis">It read the <b>${esc(p.mandate_name)}</b> mandate on ${esc(p.portfolio)}
    (${esc(p.service_model.toLowerCase())}), which is how
    ${esc(prof.client_name ? prof.client_name.split(" ")[0] : "the client")}'s
    <b>${esc(prof.risk_profile || "risk")}</b> profile reaches a number: the profile is
    expressed once, as the mandate, and the bands are read from there rather than
    re-derived here. Horizon (${esc(String(prof.investment_horizon_years || "—"))}y),
    stated liquidity needs (${esc(String(prof.liquidity_needs || "—")).toLowerCase()})
    and the tolerance score do <b>not</b> enter the trade selection &mdash; they belong to
    the conversation, not to the constraint set.</p>`;
}

function wireFindings() {
  document.querySelectorAll("[data-draft]").forEach(b =>
    b.addEventListener("click", () => openDrawer(b.dataset.draft)));
  document.querySelectorAll("[data-goto-finding]").forEach(b =>
    b.addEventListener("click", () => {
      const el = document.getElementById("f-" + b.dataset.gotoFinding);
      if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" });
                el.classList.add("flash");
                setTimeout(() => el.classList.remove("flash"), 1200); }
    }));
  document.querySelectorAll("[data-sev]").forEach(b =>
    b.addEventListener("click", () => {
      const card = document.getElementById("f-" + b.dataset.sev);
      const why = card && card.querySelector("details.why");
      if (!why) return;
      why.open = true;
      why.scrollIntoView({ behavior: "smooth", block: "center" });
    }));
  document.querySelectorAll("[data-tune]").forEach(b =>
    b.addEventListener("click", () => openTuner()));
  document.querySelectorAll("[data-reopen]").forEach(b =>
    b.addEventListener("click", () => {
      delete state.decisions[b.dataset.reopen];
      save("wb.decisions", state.decisions); renderClient();
    }));
}

/* ── the money charts ─────────────────────────────────────────────────────
 * All three read from `clients[cid].performance`, built by engine/performance.py.
 * Nothing is computed here: the deltas, the contributions and the event
 * attribution all arrive finished.
 *
 * Rebuilt on the lieflat-charts `basics-gallery.html` implementations rather
 * than on their silhouettes — B2 hairline line, C5 rung waterfall, C3 stacked
 * rungs. Palette stays porcelain, as everywhere else in the app, with the
 * skill's ink-boost on strokes. What the templates actually contribute:
 *
 *   a floor that exists whether or not there is a reading  (B2)
 *   a countable unit, stated in the footer                 (C3, C5)
 *   solid adds, dashed takes away                          (C5)
 *   value labels haloed with paint-order, never shrunk     (all)
 */

const MONTH3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = d => new Date(d + "T00:00:00Z").getTime() / 86400000;
const shortName = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);

/* Two lines of small caps under a waterfall column. The gallery's own labels
 * are four-letter category codes; instrument names are not, so they wrap. */
function capLines(name, per, lines) {
  const words = name.split(" ");
  const out = [];
  let line = "";
  words.forEach(w => {
    if ((line + " " + w).trim().length > per && line) { out.push(line); line = w; }
    else line = (line + " " + w).trim();
  });
  if (line) out.push(line);
  if (out.length > lines) {
    out.length = lines;
    out[lines - 1] = shortName(out[lines - 1], per);
  }
  return out;
}

/* B2 Hairline Line — basics-gallery.html, card B2.
 * The template's real mechanism is the floor: one tick per period whether or
 * not anything was recorded, so the reader sees the shape of time itself. Here
 * that is one tick per month, which also fixes a quiet dishonesty — the five
 * snapshots are not evenly spaced, and the old chart drew them as if they were.
 * Hollow marks a category, as the template's weekends do: here, an interim
 * snapshot against the two that bound the period. */
function wealthPath(C, perf) {
  const series = C.wealth_series;

  /* The right-hand fan is NOT a forecast and is not drawn on the time axis. The
   * line to the left of the dashed rule is five measured snapshots; everything
   * right of it is the same wealth repriced instantaneously under the stated
   * shocks of Module F. There is no path between the two and none is drawn —
   * a curve running left to right through future dates would be a prediction,
   * which this product does not make. The widest and the mildest of the four
   * are marked because those are the only two the RM can honestly name: the
   * worst and the best of what has actually been stated, not of what could
   * happen. */
  const sc = (C.scenarios || []).map((x, i) => ({ x: x, i: i }))
    .sort((a, b) => a.x.delta_pct - b.x.delta_pct);
  const fan = sc.length > 1 ? { worst: sc[0], best: sc[sc.length - 1] } : null;
  const PROJ = fan ? 196 : 0;

  const W = 760 + PROJ, H = 232, L = 26, R = 26, T = 44, Bm = 56;
  const base = H - Bm;
  const t0 = day(series[0].date), t1 = day(series[series.length - 1].date);
  const X = d => L + ((day(d) - t0) / (t1 - t0)) * (W - L - R - PROJ);
  const vals = series.map(s => s.usd);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (fan) { lo = Math.min(lo, fan.worst.x.after_usd); hi = Math.max(hi, fan.best.x.after_usd); }
  const pad = (hi - lo) * (fan ? 0.16 : 0.5) || hi * 0.08;
  lo -= pad; hi += pad * 0.7;
  const Y = v => T + (1 - (v - lo) / (hi - lo)) * (base - T);
  const xNow = X(series[series.length - 1].date), yNow = Y(vals[vals.length - 1]);
  const xEnd = xNow + 62;

  // the floor: every month in the period, whether or not it holds a snapshot
  const months = [];
  const m0 = new Date(series[0].date.slice(0, 8) + "01T00:00:00Z");
  for (let k = 0; k < 40; k++) {
    const d = new Date(Date.UTC(m0.getUTCFullYear(), m0.getUTCMonth() + k, 1));
    const iso = d.toISOString().slice(0, 10);
    if (day(iso) > t1) break;
    if (day(iso) >= t0) months.push(iso);
  }

  const path = series.map((s, i) => `${i ? "L" : "M"}${X(s.date).toFixed(1)},${
    Y(s.usd).toFixed(1)}`).join("");

  return `<svg viewBox="0 0 ${W} ${H}" class="wealth" role="img"
      aria-label="Total wealth across five snapshots, ${usd2(vals[0])} to ${
        usd2(vals[vals.length - 1])} USD, ${perf.period_change_pct}%.">
    ${months.map((m, k) => `<line class="fade" style="--d:${(k * 0.012).toFixed(2)}s"
      x1="${X(m).toFixed(1)}" y1="${base}" x2="${X(m).toFixed(1)}" y2="${base - 6}"
      stroke="${P.FLOOR}" stroke-width="0.9"/>`).join("")}
    <line x1="${L - 8}" y1="${base}" x2="${W - R + 8}" y2="${base}"
      stroke="${P.GRID}" stroke-width="1"/>

    <path class="draw" d="${path}" fill="none" stroke="${P.DATA}" stroke-width="1.8"
      stroke-linejoin="round"/>

    ${perf.steps.map((st, i) => {
      const mx = (X(st.from) + X(st.to)) / 2;
      const my = (Y(st.start_usd) + Y(st.end_usd)) / 2;
      const down = st.delta_usd < 0;
      return `<g class="wstep" data-step="${i}" tabindex="0" role="button"
          aria-label="${st.from} to ${st.to}, ${st.delta_pct}%, ${st.events.length} events
            touching ${st.touched_pct}% of holdings">
        <rect class="whit" x="${X(st.from).toFixed(1)}" y="${T - 24}"
          width="${(X(st.to) - X(st.from)).toFixed(1)}" height="${base - T + 24}"
          fill="transparent"/>
        <text class="wdelta ${down ? "down" : "up"}" x="${mx.toFixed(1)}"
          y="${(my - 15).toFixed(1)}" text-anchor="middle">${
            st.delta_pct > 0 ? "+" : ""}${st.delta_pct.toFixed(1)}%</text>
        ${st.events.length ? `<g class="wev fade" style="--d:${(0.7 + i * 0.08).toFixed(2)}s"
            transform="translate(${mx.toFixed(1)} ${base + 15})">
          <line y1="${(my - base - 9).toFixed(1)}" y2="-6" stroke="${P.FAINT}"
            stroke-width="0.9" stroke-dasharray="2 3"/>
          <circle r="7" fill="${st.events.some(e => e.severity === "Severe")
            ? P.ALERT : P.DATA2}"/>
          <text class="wevn" y="3.2" text-anchor="middle">${st.events.length}</text>
        </g>` : ""}
      </g>`;
    }).join("")}

    ${series.map((s, i) => {
      const edge = i === 0 || i === series.length - 1;
      return `<circle class="pop" style="--d:${(0.25 + i * 0.07).toFixed(2)}s"
          cx="${X(s.date).toFixed(1)}" cy="${Y(s.usd).toFixed(1)}" r="${edge ? 4.2 : 2.6}"
          fill="${edge ? P.HERO : P.BG}" stroke="${P.DATA}" stroke-width="${edge ? 0 : 1.2}"/>
        <text class="wval fade" style="--d:${(0.55 + i * 0.07).toFixed(2)}s"
          x="${X(s.date).toFixed(1)}" y="${(Y(s.usd) - 12).toFixed(1)}"
          text-anchor="${i === series.length - 1 ? "end" : i === 0 ? "start" : "middle"}">${
          usd2(s.usd)}</text>
        <text class="wdate" x="${X(s.date).toFixed(1)}" y="${base + 40}"
          text-anchor="middle">${+s.date.slice(8)} ${MONTH3[+s.date.slice(5, 7) - 1]
          } ${s.date.slice(2, 4)}</text>`;
    }).join("")}

    ${fan ? fanBlock(fan, xNow, yNow, xEnd, Y, T, base, W, R) : ""}

    <text class="rule" x="${((W - R - PROJ) / 2).toFixed(0)}" y="${H - 5}"
      text-anchor="middle">ONE TICK = ONE MONTH &#183; HOLLOW = INTERIM SNAPSHOT
      &#183; NUMBERED MARKER = EVENTS REACHING THESE HOLDINGS${fan
        ? " &#183; RIGHT OF THE RULE IS NOT A FORECAST" : ""}</text>
  </svg>`;
}

/* The two stated shocks that bracket the rest, drawn as an instantaneous
 * reprice off the last measured point. Hairline, no fill gradient, no arrow —
 * an arrow implies travel through time and nothing here travels. */
function fanBlock(fan, xNow, yNow, xEnd, Y, T, base, W, R) {
  const yW = Y(fan.worst.x.after_usd), yB = Y(fan.best.x.after_usd);
  const end = (o, y, tone) => `<g class="fanend ${tone}" data-goshock="${o.i}"
      tabindex="0" role="button"
      aria-label="${esc(o.x.name)}: ${o.x.delta_pct > 0 ? "+" : ""}${o.x.delta_pct}%,
        ${usd2(o.x.after_usd)}">
    <line class="fanray" x1="${xNow.toFixed(1)}" y1="${yNow.toFixed(1)}"
      x2="${xEnd.toFixed(1)}" y2="${y.toFixed(1)}"/>
    <circle cx="${xEnd.toFixed(1)}" cy="${y.toFixed(1)}" r="3.4"/>
    <text class="fanpct" x="${(xEnd + 9).toFixed(1)}" y="${(y - 2).toFixed(1)}">${
      o.x.delta_pct > 0 ? "+" : ""}${o.x.delta_pct.toFixed(1)}% · ${usd2(o.x.after_usd)}</text>
    <text class="fannm" x="${(xEnd + 9).toFixed(1)}" y="${(y + 9).toFixed(1)}">${
      esc(o.x.name)}</text>
  </g>`;
  return `<g class="fan">
    <path class="fanwedge" d="M${xNow.toFixed(1)},${yNow.toFixed(1)}
      L${xEnd.toFixed(1)},${yB.toFixed(1)} L${xEnd.toFixed(1)},${yW.toFixed(1)}Z"/>
    <line class="fannow" x1="${xNow.toFixed(1)}" y1="${(T - 20).toFixed(1)}"
      x2="${xNow.toFixed(1)}" y2="${base}"/>
    <text class="fanhead" x="${(xNow + 6).toFixed(1)}" y="${(T - 24).toFixed(1)}">IF
      REPRICED TODAY · STATED SHOCKS, NOT A FORECAST</text>
    ${end(fan.best, yB, "up")}
    ${end(fan.worst, yW, "down")}
  </g>`;
}

/* The window behind a marker: what the wealth did, and every event in that
 * window that has a route into this client's holdings — with the instrument it
 * reached and the word that matched. An event is never asserted to be the
 * cause; it is placed next to the move and left there. */
function stepPanel(perf, idx) {
  if (idx === null || idx === undefined || !perf.steps[idx]) {
    const busiest = perf.steps.reduce((a, b) => (b.events.length > a.events.length ? b : a),
                                      perf.steps[0]);
    return `<p class="step-hint">Click a marker on the line to read the events in that window.
      The busiest is ${esc(dateShort(busiest.from))}–${esc(dateShort(busiest.to))}, with
      ${busiest.events.length} touching ${busiest.touched_pct}% of holdings.</p>`;
  }
  const st = perf.steps[idx];
  return `<div class="step">
    <div class="step-head">
      <b>${esc(dateLong(st.from))} &rarr; ${esc(dateLong(st.to))}</b>
      <span class="n ${st.delta_usd < 0 ? "alert" : "pos"}">${signed(st.delta_usd)} ·
        ${st.delta_pct > 0 ? "+" : ""}${st.delta_pct.toFixed(1)}%</span>
      <button class="step-close" data-step="">Close</button>
    </div>
    <p class="step-sub">${st.events.length} of ${st.events_in_window} events in this window
      reach holdings this client actually owns, together ${st.touched_pct}% of wealth. Placed
      beside the move, not offered as its cause.</p>
    ${st.events.map(e => `<article class="ev">
      <div class="ev-top">
        <span class="ev-date n">${esc(dateShort(e.date))}</span>
        <span class="tag${e.severity === "Severe" ? " crit" : " on"}">${esc(e.severity)}</span>
        <span class="ev-kind">${esc(e.type)} · ${esc(e.region)}</span>
        <span class="ev-touch n">${e.touched_pct}% of wealth</span>
      </div>
      <p class="ev-desc">${esc(e.description)}</p>
      <div class="ev-hits">
        <span class="eyebrow">Reaches</span>
        ${e.hits.map(h => `<span class="ev-hit">${esc(h.instrument)}
          <i>${esc(h.via)} &rarr; ${esc(h.matched)}</i></span>`).join("")}
        ${e.hit_count > e.hits.length
          ? `<span class="ev-hit more">+${e.hit_count - e.hits.length} more</span>` : ""}
      </div>
    </article>`).join("") || `<p class="empty">No event in this window reaches this portfolio.</p>`}
  </div>`;
}

/* C5 Rung Waterfall — basics-gallery.html, card C5.
 * The template's contract exactly: solid rungs add, dashed rungs take away, a
 * dashed hairline hands the running level to the next column, and a stated unit
 * makes every rung countable. Contributions to a return are a decomposition
 * that sums to a total, which is the waterfall's own subject — the diverging
 * bars this replaces put the same numbers on a chart that could not show they
 * added up. The tail is bucketed so the column count stays inside the
 * template's ≤6 levels; the positions table below carries every line. */
function contribWaterfall(perf) {
  const all = perf.contributors.filter(c => Math.abs(c.contribution_pp) >= 0.01);
  if (!all.length) return `<p class="empty">Nothing has moved far enough to report.</p>`;
  const down = all.filter(c => c.contribution_pp < 0);
  const up = all.filter(c => c.contribution_pp > 0).slice().reverse();
  const bucket = (rest, name) => rest.length
    ? [{ instrument: name + " (" + rest.length + ")",
         contribution_pp: rest.reduce((s, c) => s + c.contribution_pp, 0) }] : [];

  const cols = down.slice(0, 3)
    .concat(bucket(down.slice(3), "Other detractors"))
    .concat(up.slice(0, 2))
    .concat(bucket(up.slice(2), "Other contributors"));

  // running level, and the extent it travels through
  let lv = 0;
  const rows = cols.map(c => {
    const from = lv; lv += c.contribution_pp;
    return { name: c.instrument, v: c.contribution_pp, from: from, to: lv };
  });
  rows.push({ name: "Net", v: lv, from: 0, to: lv, total: true });

  const levels = rows.flatMap(r => [r.from, r.to]).concat([0]);
  const top = Math.max(...levels), bot = Math.min(...levels);
  // one rung is a stated unit, chosen so the tallest column reads at a glance
  const span = top - bot || 1;
  // the unit has to keep the smallest step countable, not just the largest
  // column short: at one rung per point a +1.25 contribution is a single line
  const UNIT = [0.05, 0.1, 0.25, 0.5, 1, 2, 5].find(u => span / u <= 44) || 10;

  const W = 900, T = 34, Bm = 62, rung = 4.8;
  const H = T + Math.ceil(span / UNIT) * rung + Bm;
  const zero = T + (top / UNIT) * rung;
  const yOf = v => zero - (v / UNIT) * rung;
  const step = (W - 40) / rows.length;
  const x0 = i => 20 + step * (i + 0.5);
  const HW = Math.min(15, step / 2 - 12);

  return `<figure class="fchart wide" data-reveal>
    <svg viewBox="0 0 ${W} ${H}" role="img"
        aria-label="How each position's unrealised profit or loss builds the client's
          ${perf.return_on_cost_pct}% return on cost.">
      <line x1="12" x2="${W - 12}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}"
        stroke="${P.LAB}" stroke-width="1"/>
      <text class="foot" x="12" y="${(zero - 6).toFixed(1)}">0</text>

      ${rows.map((r, i) => {
        const x = x0(i), neg = r.v < 0 && !r.total;
        const a = Math.min(yOf(r.from), yOf(r.to)), b = Math.max(yOf(r.from), yOf(r.to));
        const n = Math.max(1, Math.round(Math.abs(r.to - r.from) / UNIT));
        const rungs = [];
        for (let k = 0; k < n; k++) {
          const y = b - k * rung - rung / 2;
          const w = HW - 1.2 + ((k * 7 + i * 13) % 11) / 11 * 2.6;   // template jitter
          rungs.push(`<line x1="${(x - w).toFixed(1)}" y1="${y.toFixed(1)}"
            x2="${(x + w).toFixed(1)}" y2="${y.toFixed(1)}"
            stroke="${r.total ? P.HERO : neg ? P.ALERT : P.DATA}" stroke-width="1.3"
            ${neg ? 'stroke-dasharray="2.5 2.5"' : ""}
            opacity="${(0.62 + ((k * 5 + i) % 7) / 7 * 0.38).toFixed(2)}"/>`);
        }
        const hand = i < rows.length - 1 && !rows[i + 1].total
          ? `<line x1="${(x + HW + 3).toFixed(1)}" y1="${yOf(r.to).toFixed(1)}"
             x2="${(x0(i + 1) - HW - 3).toFixed(1)}" y2="${yOf(r.to).toFixed(1)}"
             stroke="${P.FAINT}" stroke-width="0.8" stroke-dasharray="2 3"/>` : "";
        const lines = capLines(r.name, Math.max(11, Math.floor(step / 5.4)), 2);
        return `<g class="lrow" style="--i:${i}">
          <title>${esc(r.name)} — ${r.v > 0 ? "+" : ""}${r.v.toFixed(2)} points of the
            ${perf.return_on_cost_pct}% return</title>
          ${rungs.join("")}${hand}
          <text class="wnum ${neg ? "down" : r.total ? "net" : "up"}" x="${x.toFixed(1)}"
            y="${(a - 8).toFixed(1)}" text-anchor="middle">${
            r.v > 0 ? "+" : "−"}${Math.abs(r.v).toFixed(2)}</text>
          ${lines.map((ln, k) => `<text class="wname${r.total ? " net" : ""}"
            x="${x.toFixed(1)}" y="${H - Bm + 20 + k * 10}" text-anchor="middle">${
            esc(ln)}</text>`).join("")}
        </g>`;
      }).join("")}

      <text class="rule" x="${W / 2}" y="${H - 8}" text-anchor="middle">SOLID RUNGS ADD
        &#183; DASHED RUNGS TAKE AWAY &#183; ONE RUNG = ${UNIT} POINT${
          UNIT === 1 ? "" : "S"} OF RETURN</text>
    </svg>
    <figcaption>Unrealised only — a position counts from what it cost, not from the start of
      the period, so a holding bought years ago carries its whole history here. Every line
      is in the table below; the tail is bucketed so the steps stay countable.</figcaption>
  </figure>`;
}

/* C3 Stacked Rungs — basics-gallery.html, card C3.
 * One ladder per snapshot, one rung per two points of wealth, shades running
 * down the porcelain ladder. This replaces a stacked area, which drew a
 * continuous ribbon between five dated observations and so implied readings
 * that were never taken — the same objection the section's own standfirst
 * makes about everything between the snapshots. Five ladders say five days. */
function mixLadders(perf) {
  const series = perf.mix_series;
  const totals = series.map(s => Object.values(s.mix).reduce((a, b) => a + b, 0) || 1);
  const last = series[series.length - 1];
  const order = [...new Set(series.flatMap(s => Object.keys(s.mix)))]
    .sort((a, b) => (last.mix[b] || 0) - (last.mix[a] || 0));
  // porcelain's own note: the ladder carries four lightness steps, and adjacent
  // segments have to separate at a 1.3px stroke. HERO and DATA do not — they are
  // both navy — so the second sleeve takes the gold, which sits between them in
  // lightness and separates by hue as well. Five sleeves is the preset's stated
  // ceiling and reads tighter.
  const TONE = order.length <= 4
    ? [P.HERO, P.GOLD, P.DATA2, P.FAINT]
    : [P.HERO, P.GOLD, P.DATA, P.DATA2, P.FAINT];
  const UNIT = 2;                       // one rung = 2% of wealth

  const W = 900, T = 30, Bm = 54, R = 196, rung = 3.9;
  const rows = Math.ceil(100 / UNIT) + order.length;
  const H = T + rows * rung + Bm;
  const base = H - Bm;
  const step = (W - R - 60) / series.length;
  const x0 = i => 44 + step * (i + 0.5);
  const HW = Math.min(17, step / 2 - 10);
  const pct = (i, c) => 100 * (series[i].mix[c] || 0) / totals[i];

  const mid = {};                       // where each class sits in the last ladder
  let acc = 0;
  order.forEach((c, si) => {
    const n = pct(series.length - 1, c) / UNIT;
    mid[c] = base - (acc + n / 2 + si) * rung;
    acc += n;
  });

  return `<svg viewBox="0 0 ${W} ${H}" class="mix" role="img"
      aria-label="Asset class weights at each of the five snapshots, as ladders of
        countable rungs.">
    ${series.map((s, i) => {
      const x = x0(i);
      let k0 = 0;
      const ladder = order.map((c, si) => {
        const n = Math.round(pct(i, c) / UNIT);
        const out = [];
        for (let k = 0; k < n; k++) {
          const y = base - (k0 + k + si) * rung;
          const w = HW - 1.4 + ((k * 7 + si * 5 + i * 3) % 11) / 11 * 2.8;
          out.push(`<line x1="${(x - w).toFixed(1)}" y1="${y.toFixed(1)}"
            x2="${(x + w).toFixed(1)}" y2="${y.toFixed(1)}" stroke="${TONE[si % TONE.length]}"
            stroke-width="1.3" opacity="${(0.66 + ((k * 3 + si) % 6) / 6 * 0.34).toFixed(2)}"/>`);
        }
        k0 += n;
        return out.join("");
      }).join("");
      return `<g class="lrow" style="--i:${i}">
        <title>${esc(dateLong(s.date))} — ${usd2(totals[i])} USD</title>
        ${ladder}
        <text class="mixtot" x="${x.toFixed(1)}" y="${(base - (k0 + order.length) * rung - 9)
          .toFixed(1)}" text-anchor="middle">${usd2(totals[i])}</text>
        <text class="wdate" x="${x.toFixed(1)}" y="${base + 19}" text-anchor="middle">${
          +s.date.slice(8)} ${MONTH3[+s.date.slice(5, 7) - 1]} ${s.date.slice(2, 4)}</text>
      </g>`;
    }).join("")}
    <line x1="26" y1="${base + 5}" x2="${(W - R - 6).toFixed(1)}" y2="${base + 5}"
      stroke="${P.GRID}" stroke-width="0.9"/>

    ${(() => {
      // a 4% sleeve is two rungs, so two thin ones collide; push the labels
      // apart in reading order and elbow a leader back to the sleeve
      const lab = order.map((c, si) => ({ c: c, si: si, midY: mid[c] }))
        .sort((a, b) => a.midY - b.midY);
      let prev = -99;
      lab.forEach(b => { b.labY = Math.max(b.midY, prev + 17); prev = b.labY; });
      const over = lab.length ? lab[lab.length - 1].labY - (base - 2) : 0;
      if (over > 0) lab.forEach(b => { b.labY -= over; });

      return lab.map(b => {
        const first = pct(0, b.c), now = pct(series.length - 1, b.c);
        const move = now - first;
        const xa = W - R + 2, xb = W - R + 13;
        return `<g class="fade" style="--d:${(0.4 + b.si * 0.06).toFixed(2)}s">
          <path d="M${xa} ${b.midY.toFixed(1)} H${xa + 5} V${b.labY.toFixed(1)} H${xb}"
            fill="none" stroke="${TONE[b.si % TONE.length]}" stroke-width="1.6"/>
          <text class="mixlab" x="${xb + 6}" y="${(b.labY + 4).toFixed(1)}">${esc(b.c)}
            <tspan class="mixpct">${now.toFixed(0)}%</tspan><tspan class="mixmv ${
              move < -0.5 ? "down" : move > 0.5 ? "up" : ""}">${
              Math.abs(move) < 0.5 ? "" : (move > 0 ? " ▲" : " ▼") + Math.abs(move).toFixed(1)
            }</tspan></text></g>`;
      }).join("");
    })()}

    <text class="rule" x="${((W - R) / 2).toFixed(0)}" y="${H - 8}" text-anchor="middle">ONE
      RUNG = ${UNIT}% OF WEALTH &#183; COLOUR NAMES THE SLEEVE &#183; DARKEST = LARGEST</text>
  </svg>`;
}

function wireMoney() {
  document.querySelectorAll("[data-step]").forEach(el =>
    el.addEventListener("click", () => {
      const v = el.dataset.step;
      state.step = v === "" ? null : +v;
      const host = document.getElementById("stepPanel");
      if (host) host.innerHTML = stepPanel(B.clients[state.client].performance, state.step);
      wireMoney();
    }));
  document.querySelectorAll(".wstep").forEach(el =>
    el.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
    }));
}

/* Notes the RM writes here. Held apart from rm_notes.json and labelled as such:
 * the engine has already run, so a note added now cannot have changed a
 * finding, and pretending otherwise would be the worst kind of lie for this
 * product to tell. */
function wireNotes() {
  const form = document.getElementById("noteAdd");
  if (form) form.addEventListener("submit", e => {
    e.preventDefault();
    const text = document.getElementById("noteText").value.trim();
    if (!text) { document.getElementById("noteText").focus(); return; }
    const cid = state.client;
    state.notes[cid] = state.notes[cid] || [];
    state.notes[cid].push({
      id: "N-" + Date.now().toString(36),
      date: B.today,
      channel: document.getElementById("noteChannel").value,
      note: text,
    });
    save("wb.notes", state.notes);
    renderClient();
  });
  document.querySelectorAll("[data-del-note]").forEach(b =>
    b.addEventListener("click", () => {
      const cid = state.client;
      state.notes[cid] = (state.notes[cid] || []).filter(n => n.id !== b.dataset.delNote);
      save("wb.notes", state.notes);
      renderClient();
    }));
}

/* A decision in the composer is a client interaction, so it belongs on the
 * client's file and not only under the finding that produced it. The dismissal
 * placeholder has always said "written back as a note on the client file"; this
 * is the code that makes that sentence true, for all three verdicts. Keyed on
 * the finding so re-deciding replaces the entry rather than stacking a second
 * one, and deletable like any other note she writes here. */
function fileDecision(f, p, verdict, reason, text, lang, via) {
  const cid = f.client_id;
  const id = "D-" + f.id;
  state.notes[cid] = (state.notes[cid] || []).filter(n => n.id !== id);
  const body = verdict === "Dismissed"
    ? "Not raised with the client. " + (reason || "No reason given.")
    : (verdict === "Amended" ? "Note sent, amended from the draft"
                             : "Note sent as drafted")
      + (lang !== "English" ? " in " + lang : "")
      + (via ? ", translated by Claude from the " + via.from
             + (via.clean ? " with every figure checked" : "") : "")
      + ".\n\n" + text;
  state.notes[cid].push({
    id: id, date: B.today,
    channel: verdict === "Dismissed" ? "Internal" : "Note",
    from: f.id, headline: f.headline, verdict: verdict,
    note: body,
  });
}

/* ── screen 3 · the composer ──────────────────────────────────────────────
 * Layer 4. Nothing here executes; the RM accepts, amends or dismisses, and a
 * dismissal needs a reason that is written back to the file.
 *
 * The draft comes from engine/narrate.py when the cache holds one, and from the
 * deterministic template when it does not. The difference is stated on the
 * screen rather than hidden — an RM who cannot tell which she is looking at
 * cannot take responsibility for what she sends. */

/* The name never left the perimeter, so the draft addresses [[FIRST_NAME]] and
 * it is substituted here, on the RM's own machine. For a client reported to in
 * Chinese, Japanese or Korean the family name comes first and a bare given name
 * would be wrong, so the whole name is used — as it is for an entity such as a
 * family office, which has no first name (and no age). */
const CJK = ["Chinese", "Japanese", "Korean"];
function salutation(p) {
  const cjk = CJK.some(l => (p.reporting_language || "").indexOf(l) >= 0);
  return cjk || !p.age ? p.client_name : p.client_name.split(" ")[0];
}
const reIdent = (text, p) => String(text).split("[[FIRST_NAME]]").join(salutation(p));

function openDrawer(fid) {
  const f = F[fid];
  const p = B.clients[f.client_id].profile;
  const d = f.draft;
  const foreign = p.reporting_language && p.reporting_language !== "English";
  const clientLang = foreign ? p.reporting_language : null;
  // English always, plus the client's language when the engine or the model
  // wrote one — or when she has had one translated here.
  const base = d ? (foreign ? ["English", clientLang] : ["English"]) : noteLangs(f, p);
  const langs = foreign && base.indexOf(clientLang) < 0 && (fid + "|" + clientLang) in state.drafts
    ? base.concat([clientLang]) : base;
  // Default to what actually gets sent: the version the client can read.
  const lang = langs.indexOf(state.noteLang[fid]) >= 0 ? state.noteLang[fid]
             : langs[langs.length - 1];
  const isClientLang = lang !== "English";
  const generated = l => reIdent(d ? (l === "English" ? d.english : d.client_language)
                                   : composeIn(f, p, l), p);
  const current = l => ((fid + "|" + l) in state.drafts ? state.drafts[fid + "|" + l]
                                                         : generated(l));
  const key = fid + "|" + lang;
  const draft = current(lang);
  const held = d && d.unverified.length;

  /* Editing one language does not touch the other. The two versions are in
   * step when both are still what was generated, or when one is a checked
   * translation of the other and neither has been touched since. Anything else
   * is said out loud rather than letting her sign an English copy that no
   * longer matches the Chinese being sent. */
  const edited = l => current(l) !== generated(l);
  const sync = state.sync[fid];
  const synced = !!sync && langs.indexOf(sync.from) >= 0 && langs.indexOf(sync.to) >= 0
    && current(sync.from) === sync.source && current(sync.to) === sync.target;
  const drift = langs.length > 1 && !synced && langs.some(edited)
    && (!!sync || !langs.every(edited));
  const badTranslation = synced && !sync.clean;
  const target = langs.length > 1 ? langs.find(l => l !== lang) : clientLang;
  const blocked = held || badTranslation;
  const rec = !Translator.on && RECORDED.find(r => r.finding_id === fid);

  document.getElementById("drawer").innerHTML = `
  <div class="scrim" id="scrim"></div>
  <aside class="drawer" role="dialog" aria-modal="true" aria-label="Draft the client note">
    <div class="drawer-head">
      <button class="close" id="closeDrawer">Close</button>
      <div class="eyebrow">Draft for ${esc(p.client_name)}</div>
      <h2>${esc(d ? d.subject : f.headline)}</h2>
      <div class="src-row">
        ${d ? `<span class="tag${held ? " crit" : " on"}">${
          held ? "Held back" : "Drafted by Claude"}</span>` : `<span class="tag">Template</span>`}
        ${foreign ? `<span class="tag lang-tag">${esc(p.reporting_language)}</span>` : ""}
        ${synced ? `<span class="tag${sync.clean ? " on" : " crit"}">Translated by Claude</span>` : ""}
        ${d ? `<span class="src-note">${esc(provenance(d))} · ${esc(d.at)} · from the
          finding, never the portfolio</span>`
            : `<span class="src-note">Deterministic stand-in — the narration layer
               has not been run for this finding</span>`}
      </div>
    </div>

    <div class="drawer-body">
      ${d ? `<div class="checked ${held ? "bad" : "good"}">
        ${held
          ? `<b>${d.unverified.length} figure${d.unverified.length === 1 ? "" : "s"} in this
             draft could not be traced back to the rule</b> &mdash;
             ${d.unverified.map(n => `<code>${esc(n)}</code>`).join(", ")}. The workbench
             does not treat it as sendable. Every number a client sees has to come out of
             <code>engine/</code>, and this one did not.`
          : `<b>Every figure in this draft appears in the finding.</b> The engine published
             the numbers, the model was given them as an allow-list, and the draft was read
             back and checked against it before it reached this screen.`}
      </div>` : ""}

      <section>
        <div class="note-head">
          <h4>${isClientLang ? esc(lang) + " — what gets sent" : "Client-ready note"}</h4>
          ${langs.length > 1 ? `<div class="lang-switch" role="tablist"
              aria-label="Language of this note">
            ${langs.map(l => `<button role="tab" data-note-lang="${esc(l)}"
              aria-selected="${l === lang}">${esc(l)}</button>`).join("")}
          </div>` : ""}
        </div>
        ${foreign && langs.length === 1 ? `<p class="lang-warn">This stand-in is in
          English, and ${esc(p.client_name.split(" ")[0])} is reported to in
          ${esc(p.reporting_language)}. The workbench has no ${esc(p.reporting_language)}
          wording for this kind of finding, so it will not pretend otherwise${
          Translator.on ? " — translate it below, and every figure is checked" : ""}.</p>` : ""}
        <textarea id="draftText" ${isClientLang ? 'lang="' + esc(langTag(p)) + '"' : ""}>${
          esc(draft)}</textarea>
        ${synced ? translationCheck(sync) : ""}
        ${drift ? `<p class="lang-warn">${sync
          ? `The <b>${esc(langs.filter(l => current(l) !== (l === sync.from ? sync.source
              : sync.target)).join(" and "))}</b> version has changed since it was translated,`
          : `You have edited the <b>${esc(langs.filter(edited).join(" and "))}</b> version;
             the <b>${esc(langs.filter(l => !edited(l)).join(" and "))}</b> version is still
             the original,`} so the two no longer say the same thing. ${Translator.on
          ? "Translate the one you trust into the other, amend both, or send only the one you have read."
          : rec ? "Translate one into the other below, amend both, or send only the one you have read."
          : "Amend both, or send only the one you have read. (" + esc(Translator.reason) + ".)"}</p>` : ""}
        ${target ? `<div class="translate-row">
          <button class="btn ghost" id="translateBtn" data-from="${esc(lang)}"
            data-to="${esc(target)}"${Translator.on || recording(fid, lang, target)
              ? "" : " disabled"}>Translate this into ${esc(target)}</button>
          <span class="tr-hint">${Translator.on
            ? `Replaces the ${esc(target)} version with a translation of what is on screen.
               Figures are checked on the way back; names never leave this machine.`
            : rec && synced && sync.recorded ? `Replayed from a translation recorded in
               advance; this copy has no server to translate with.`
            : rec && lang === rec.from && current(lang) === rec.source ? `The recorded
               amendment is in place &mdash; &ldquo;${esc(rec.amendment)}&rdquo; Translate it,
               and the figures are checked on the way back.`
            : rec ? `This copy has no server, so it cannot translate your own edits &mdash;
               only one amendment recorded in advance, which adds &ldquo;${
               esc(rec.amendment)}&rdquo; <button class="linkish" id="useRecording">Use the
               recorded amendment</button>`
            : `Translation is off — ${esc(Translator.reason)}.`}</span>
          <p class="tr-error" id="translateErr" role="alert" hidden></p>
        </div>` : ""}
        <div class="provenance">Written from the finding, not from the portfolio. The client's
          name was never sent — the draft addresses a token, and it is substituted here.
          ${esc(RM_FIRST)} owns what is sent.</div>
      </section>

      ${isClientLang ? `<section>
        <h4>${drift ? "The English version — no longer the same note" : "The same note in English"}</h4>
        <p class="en-copy">${esc(current("English"))
          .replace(/\n\n/g, "</p><p class='en-copy'>").replace(/\n/g, "<br>")}</p>
        <div class="provenance">For the file, and so ${esc(RM_FIRST)} can read what is being
          signed. The version above is the one that is sent.</div>
      </section>` : ""}

      <section>
        <h4>Grounded in</h4>
        <div class="why-inner"><dl>
          ${d ? `<dt>Asks the client to</dt><dd>${esc(d.raises)}</dd>` : ""}
          <dt>Rule</dt><dd><code>${esc(f.rule_text)}</code></dd>
          <dt>Action</dt><dd>${esc(f.action)}</dd>
          <dt>Severity</dt><dd>${severityLadder(f)}</dd>
          ${f.evidence.length ? `<dt>Client said</dt><dd class="quote">&ldquo;${
            esc(f.evidence[f.evidence.length - 1].quote)}&rdquo;<cite>${
            esc(f.evidence[f.evidence.length - 1].note_id)}</cite></dd>` : ""}
        </dl></div>
      </section>
    </div>

    <div class="drawer-foot">
      <label class="eyebrow" for="reason">Reason, if you are dismissing this</label>
      <input type="text" id="reason" placeholder="Written back as a note on the client file">
      <div class="btn-row">
        <button class="btn" data-verdict="Accepted"${blocked ? " disabled" : ""}>${
          held ? "Cannot accept — figures unverified"
            : badTranslation ? "Cannot accept — the translation's figures differ"
            : "Accept and save draft"}</button>
        <button class="btn ghost" data-verdict="Amended"${badTranslation ? " disabled" : ""}>Save
          as amended</button>
        <button class="btn ghost" data-verdict="Dismissed">Dismiss</button>
      </div>
    </div>
  </aside>`;

  document.getElementById("scrim").addEventListener("click", closeDrawer);
  document.getElementById("closeDrawer").addEventListener("click", closeDrawer);
  document.querySelectorAll("[data-tune]").forEach(b =>
    b.addEventListener("click", () => openTuner()));
  document.querySelectorAll("[data-verdict]").forEach(b =>
    b.addEventListener("click", () => {
      const verdict = b.dataset.verdict;
      const reason = document.getElementById("reason").value.trim();
      if (verdict === "Dismissed" && !reason) {
        document.getElementById("reason").focus();
        document.getElementById("reason").placeholder = "A dismissal needs a reason — it goes on the file";
        return;
      }
      const text = document.getElementById("draftText").value;
      state.drafts[key] = text;
      state.decisions[fid] = { verdict, reason, at: dateLong(B.today) };
      const via = synced && sync.to === lang && text === sync.target ? sync : null;
      fileDecision(f, p, verdict, reason, text, lang, via);
      save("wb.drafts", state.drafts); save("wb.decisions", state.decisions);
      save("wb.notes", state.notes);
      closeDrawer(); renderClient();
      const el = document.getElementById("f-" + fid);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }));
  // Switching language keeps whatever she has already typed in each one: an
  // edit belongs to a language, not to a finding.
  document.querySelectorAll("[data-note-lang]").forEach(b =>
    b.addEventListener("click", () => {
      keepTyped(fid, lang);
      state.noteLang[fid] = b.dataset.noteLang;
      openDrawer(fid);
    }));
  const tb = document.getElementById("translateBtn");
  if (tb) tb.addEventListener("click", () => translateDraft(fid, tb.dataset.from, tb.dataset.to));
  const use = document.getElementById("useRecording");
  if (use) use.addEventListener("click", () => {
    keepTyped(fid, lang);
    state.drafts[fid + "|" + rec.from] = rec.source;
    save("wb.drafts", state.drafts);
    state.noteLang[fid] = rec.from;
    openDrawer(fid);
    // show what changed: select the added sentence and scroll it into view
    const t = document.getElementById("draftText");
    const at = rec.source.indexOf(rec.amendment);
    if (t && at >= 0) {
      t.focus();
      t.setSelectionRange(at, at + rec.amendment.length);
      t.scrollTop = (at / rec.source.length) * t.scrollHeight - t.clientHeight / 3;
    }
  });
  document.getElementById("draftText").focus();
}

/* Whatever is in the textarea belongs to the language on screen. Storing an
 * untouched note is harmless: "edited" is always a comparison with what was
 * generated, never the mere presence of a stored draft. */
function keepTyped(fid, lang) {
  const t = document.getElementById("draftText");
  if (!t) return;
  state.drafts[fid + "|" + lang] = t.value;
  save("wb.drafts", state.drafts);
}

function closeDrawer() { document.getElementById("drawer").innerHTML = ""; }
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && document.getElementById("drawer").innerHTML) closeDrawer();
});

/* What came back, and whether it says the same thing. The server compares the
 * figures on both sides — a translation may not add, drop or convert one — and
 * whether every name token survived. A mismatch is shown, never smoothed over,
 * and the composer will not treat it as sendable. */
function translationCheck(sync) {
  const c = sync.check || {};
  const list = a => a.map(x => `<code>${esc(x)}</code>`).join(", ");
  const problems = [
    (c.added || []).length ? `only in the ${esc(sync.to)}: ${list(c.added)}` : "",
    (c.dropped || []).length ? `missing from it: ${list(c.dropped)}` : "",
    (c.names_lost || []).length ? "a name in the original did not come back" : "",
    (c.names_invented || []).length ? "it names someone the original does not" : "",
  ].filter(Boolean);
  return `<div class="checked tr-check ${sync.clean ? "good" : "bad"}">
    ${sync.clean
      ? `<b>The ${esc(sync.to)} is Claude's translation of your ${esc(sync.from)}, and it
         carries the same figures.</b> Every figure was compared on both sides after it came
         back; names were replaced with tokens before it left this machine.`
      : `<b>The ${esc(sync.to)} does not carry the same figures as your ${esc(sync.from)}</b>
         &mdash; ${problems.join("; ")}. The workbench will not treat it as sendable.
         Translate again, or correct it by hand.`}
    <span class="tr-meta">${esc(provenance(sync))} · ${esc(sync.at)}${
      sync.recorded ? " · recorded in advance for this copy, which has no server" : ""}</span>
    ${sync.note ? `<span class="tr-note">Translator's note: ${esc(sync.note)}</span>` : ""}
  </div>`;
}

/* The one call the workbench makes while the RM types. It goes to
 * engine/serve.py on her own machine, which holds the key, takes the names
 * out, calls the model and checks what comes back.
 *
 * A static copy has no server. It replays a translation recorded in advance
 * (engine/translate.py --import-recorded), and only for the exact text it was
 * made from — anything else would be passing off one letter's translation as
 * another's. The check it shows is the one the engine ran on that text. */
async function translateDraft(fid, from, to) {
  const btn = document.getElementById("translateBtn");
  const err = document.getElementById("translateErr");
  const text = document.getElementById("draftText").value;
  keepTyped(fid, from);
  btn.disabled = true;
  btn.textContent = "Translating…";
  err.hidden = true;
  try {
    let j;
    if (Translator.on) {
      const r = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Canary": "1" },
        body: JSON.stringify({ finding_id: fid, text: text, from: from, to: to }),
      });
      j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || "the server answered " + r.status);
    } else {
      const rec = recording(fid, from, to);
      if (!rec || rec.source !== text) {
        throw new Error(rec ? "this copy can only replay the recorded amendment, word for "
          + "word. Use the link above, or run engine/serve.py with your own key to "
          + "translate your own edits" : Translator.reason);
      }
      j = Object.assign({ recorded: true }, rec);
    }
    state.drafts[fid + "|" + to] = j.text;
    state.sync[fid] = { from: from, to: to, source: text, target: j.text, check: j.check,
                        clean: j.clean, note: j.note, model: j.model, via: j.via, at: j.at,
                        recorded: !!j.recorded };
    save("wb.drafts", state.drafts);
    save("wb.sync", state.sync);
    // open on what gets sent, with her own words underneath it
    state.noteLang[fid] = to === "English" ? from : to;
    openDrawer(fid);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Translate this into " + to;
    err.textContent = "Not translated — " + e.message + ".";
    err.hidden = false;
  }
}

/* Translations recorded for a copy with no server, keyed to the exact text. */
const RECORDED = B.recorded_translations || [];
const recording = (fid, from, to) =>
  RECORDED.find(r => r.finding_id === fid && r.from === from && r.to === to);

/* Which model wrote a draft, and how: "Claude Opus 5.5 via the API", or the
 * tool named in the record for a draft prepared in advance. */
function provenance(d) {
  const name = String(d.model || "").replace(/^claude-/, "").split("-")
    .reduce((acc, w) => /^\d+$/.test(w) && /\d$/.test(acc) ? acc + "." + w
      : acc + " " + w.charAt(0).toUpperCase() + w.slice(1), "Claude");
  return name + (d.via && d.via !== "API" ? " in " + d.via : " via the API");
}

/* Translation needs engine/serve.py, which holds the API key; a page opened
 * from file:// has no server to ask. Probed once at boot, and the composer
 * says which of the two it is rather than offering a button that cannot work. */
const Translator = { on: false, reason: "checking for the local server", model: "" };
function probeTranslator() {
  if (!/^https?:$/.test(location.protocol)) {
    Translator.reason = "the workbench was opened as a file; run .venv/bin/python engine/serve.py "
      + "and open http://127.0.0.1:8000/app/ to translate";
    return;
  }
  fetch("/api/health").then(r => r.json()).then(j => {
    Translator.on = !!j.translate;
    Translator.reason = j.reason || "";
    Translator.model = j.model || "";
  }).catch(() => {
    // a static copy (GitHub Pages, any plain web server) has no /api at all
    Translator.reason = "this copy of the workbench is static; translation runs through "
      + "engine/serve.py on your own machine, with your own API key";
  });
}

/* So the browser hyphenates and renders the right glyphs for the language the
 * client actually reads. */
function langTag(p) {
  const l = p.reporting_language || "";
  return l.indexOf("Traditional Chinese") >= 0 ? "zh-Hant"
       : l.indexOf("Simplified Chinese") >= 0 ? "zh-Hans"
       : l.indexOf("Chinese") >= 0 ? "zh"
       : l.indexOf("Japanese") >= 0 ? "ja"
       : l.indexOf("Korean") >= 0 ? "ko"
       : l.indexOf("German") >= 0 ? "de"
       : l.indexOf("Italian") >= 0 ? "it"
       : l.indexOf("French") >= 0 ? "fr" : "en";
}

/* The stand-in when Layer 3 has not run: a deterministic draft assembled from
 * the finding, so the workbench works with no key and no network. It is never
 * passed off as the model's work — the composer labels it. */
/* The stand-in note. It used to paste `f.detail` into a greeting, which meant
 * sending the client a sentence written for the RM — "USD 10.3m falls due
 * within twelve months against USD 34.0m sellable at daily liquidity, of which
 * USD 0.0m sits outside any pledged portfolio" is exactly right for an RM and
 * unreadable for the person whose money it is. The plain-language version, and
 * the client's own language where the engine has frames for it, now come from
 * `engine/clientnote.py` — because it contains figures, and figures come out of
 * the engine. This only falls back to the old shape if a finding has no note. */
function composeIn(f, p, language) {
  const n = f.note && f.note[language];
  if (n) return n.text;
  return `Dear [[FIRST_NAME]],

Ahead of our next conversation I wanted to raise one thing directly.

${f.detail}

${f.action}

I would rather we discussed this properly than exchanged it by email. I will call this week.

${RM.rm_name || RM_FIRST}`;
}

/* Which languages this finding can be sent in: English always, plus the
 * client's own when the engine wrote one. */
function noteLangs(f, p) {
  const out = ["English"];
  const l = p.reporting_language;
  if (l && l !== "English" && f.note && f.note[l]) out.push(l);
  return out;
}

/* ── the ranking panel ────────────────────────────────────────────────
 * "How is severity calculated, and can I change it?" is the first question
 * anyone sensible asks of a ranked book, and the answer is two different
 * answers. Severity is a property of the finding and is built by the engine
 * from data — shown here, read-only, because changing it means re-running the
 * engine. Weight and the tier lines are the RM's judgement, and she moves
 * them here with the book reordering behind the panel as she drags. */
function openTuner() {
  const dims = Object.keys(DEFAULT_CFG.weights);
  const c = cfg();

  const slider = (key, lab, val, min, max, step, hint) => `
    <label class="tune-row" data-key="${key}">
      <span class="tw-lab">${esc(lab)}${hint ? `<em>${esc(hint)}</em>` : ""}</span>
      <input type="range" min="${min}" max="${max}" step="${step}" value="${val}">
      <output class="tw-val n">${(+val).toFixed(step < 1 ? 2 : 0)}</output>
    </label>`;

  document.getElementById("drawer").innerHTML = `
  <div class="scrim" id="scrim"></div>
  <aside class="drawer" role="dialog" aria-modal="true" aria-label="How the book is ranked">
    <div class="drawer-head">
      <button class="close" id="closeDrawer">Close</button>
      <div class="eyebrow">Ranking</div>
      <h2>Where the number comes from</h2>
    </div>

    <div class="drawer-body">
      <section>
        <h4>Two numbers, and only one of them is yours</h4>
        <ol class="tune-steps">
          <li><b>Severity, 0&ndash;100.</b> A property of the finding. The engine builds it from
            the data and records every step, so any finding can be taken apart &mdash; open
            <em>Why this fired</em> on one and the arithmetic is there. It is the same scale
            across all eight dimensions, which is what makes a mandate breach comparable to a
            margin call.</li>
          <li><b>Weight.</b> How much a dimension counts when ranking the book. This is
            judgement, not data, so it is yours. Neutral is 1.00.</li>
          <li><b>The peak.</b> A client's rank is set by their <em>worst</em> weighted finding,
            never a total. Count only breaks ties. An additive score once buried a discretionary
            compliance breach at rank ten for having fewer other problems.</li>
        </ol>
      </section>

      <section>
        <h4>Dimension weights</h4>
        <div class="tune-grid">
          ${dims.map(d => slider("w." + d, label(d), c.weights[d], 0, 2, 0.05)).join("")}
        </div>
      </section>

      <section>
        <h4>Where the tier lines fall</h4>
        <div class="tune-grid">
          ${slider("t.act", "Act at or above", c.tiers.act, 0, 100, 1, "weighted peak")}
          ${slider("t.review", "Review at or above", c.tiers.review, 0, 100, 1, "weighted peak")}
          ${slider("material", "Counts as material", c.material, 0, 100, 1, "for the tiebreak")}
        </div>
      </section>

      <section>
        <h4>What that does to the book</h4>
        <div id="tunePreview">${tunePreview()}</div>
      </section>

      <section>
        <h4>The engine's severity calibration</h4>
        <p class="sub">Every constant that shapes a severity, in one block &mdash;
          <code>engine/severity.py</code>. Read-only here on purpose: severity belongs to the
          finding, so moving these means re-running <code>python3 engine/build.py</code> and
          every number in the workbench moves with them.</p>
        ${B.calibration.map(k => `<div class="cal-rule">
          <div class="cr-head"><span class="tag on">${esc(label(k.dimension))}</span>
            <b>${esc(k.rule)}</b>
            ${k.ceiling ? `<span class="cr-ceil n">ceiling ${k.ceiling}</span>` : ""}</div>
          <p class="cr-formula">${esc(k.formula)}</p>
          <dl class="cr-terms">${k.terms.map(t =>
            `<div><dt>${esc(t[0])}</dt><dd class="n">${t[1]}</dd></div>`).join("")}</dl>
        </div>`).join("")}
      </section>
    </div>

    <div class="drawer-foot">
      <div class="btn-row">
        <button class="btn" id="closeDrawer2">Done</button>
        <button class="btn ghost" data-reset-rank>Reset to the engine's defaults</button>
      </div>
    </div>
  </aside>`;

  const close = () => { document.getElementById("drawer").innerHTML = ""; };
  document.getElementById("scrim").addEventListener("click", close);
  document.getElementById("closeDrawer").addEventListener("click", close);
  document.getElementById("closeDrawer2").addEventListener("click", close);
  document.querySelector("[data-reset-rank]").addEventListener("click", () => {
    close(); resetRanking();
  });

  document.querySelectorAll(".tune-row").forEach(row => {
    const input = row.querySelector("input");
    const out = row.querySelector("output");
    input.addEventListener("input", () => {
      const v = parseFloat(input.value);
      out.textContent = v.toFixed(input.step < 1 ? 2 : 0);
      applyTune(row.dataset.key, v);
      document.getElementById("tunePreview").innerHTML = tunePreview();
    });
  });
}

/* One knob moved. Copy the current settings, change the one field, and if that
 * lands us back on the engine's own numbers, drop the override entirely so the
 * workbench stops claiming to be retuned. */
function applyTune(key, value) {
  const next = {
    weights: Object.assign({}, cfg().weights),
    tiers: Object.assign({}, cfg().tiers),
    material: cfg().material,
  };
  if (key.slice(0, 2) === "w.") next.weights[key.slice(2)] = value;
  else if (key.slice(0, 2) === "t.") next.tiers[key.slice(2)] = value;
  else next.material = value;

  state.ranking = sameAsDefault(next) ? null : next;
  save("wb.ranking", state.ranking);
  reRank();
  renderBook();                       // the book reorders behind the open panel
}

function resetRanking() {
  state.ranking = null;
  save("wb.ranking", null);
  reRank();
  if (state.view === "client") renderClient(); else renderBook();
}

function tunePreview() {
  const t = { act: 0, review: 0, watch: 0 };
  ROWS.forEach(r => t[r.tier]++);
  return `<div class="tp-tiers">
      ${TIER_ORDER.map(([k, name]) => `<span class="tp-t t-${k}"><i class="dot"></i>
        <b class="n">${t[k]}</b> ${name}</span>`).join("")}
    </div>
    <ol class="tp-list">
      ${ROWS.slice(0, 6).map(r => {
        const moved = ENGINE_RANK[r.client_id] - r.rank;
        return `<li>
          <span class="n tp-r">${r.rank}</span>
          <span class="tp-n">${esc(r.name)}</span>
          <span class="tp-d">${esc(r.lead_label)}</span>
          <span class="n tp-p">${r.peak.toFixed(1)}</span>
          <span class="tp-m ${moved > 0 ? "up" : moved < 0 ? "down" : ""}">${
            moved ? (moved > 0 ? "▲" : "▼") + Math.abs(moved) : "—"}</span></li>`;
      }).join("")}
    </ol>
    <p class="tp-foot">Against the engine's own ranking. ${tuned()
      ? "These settings are yours and are kept in this browser."
      : "Currently the engine's own settings, unchanged."}</p>`;
}

/* ── boot ─────────────────────────────────────────────────────────────── */
document.getElementById("rmName").textContent = RM.rm_name || "—";
document.getElementById("rmInitials").textContent = (RM.rm_name || "")
  .split(" ").map(w => w[0] || "").join("").slice(0, 2).toUpperCase();

parityCheck(B);                     // the JS ranking must agree with the engine's
probeTranslator();
reRank();
Diary.init(B, { rerender: renderBook, openClient: openClient });
renderBook();
