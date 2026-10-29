/* app/calendar.js — the diary, three ways.
 *
 * engine/upcoming.py emits every dated obligation across the book with a
 * stable id. This renders them as an agenda, a month or a week, and lets
 * the RM edit them: move a date, correct a description, add the meeting
 * that only exists in her head, hide a row that is already dealt with.
 *
 * Her edits are hers. They are held separately from the engine's rows, as
 * patches keyed by the engine id, so a rebuild never silently overwrites what
 * she wrote and an edited row can always be put back. Nothing here computes:
 * amounts and clients travel with the item.
 *
 * Self-contained on purpose — it borrows no helper from app.js, so the load
 * order of the two files does not matter. */
"use strict";

const Diary = (function () {

  const KEY = "wb.diary";
  const KINDS = ["Cash need", "Commitment", "Review", "Meeting", "Note"];
  const CERTAINTY = ["Confirmed", "Contractual", "Planned", "Aspirational"];
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"];

  let B = null;                       // the bundle
  let ctx = { rerender: () => {}, openClient: () => {} };
  let store = { patch: {}, added: [], hidden: [] };
  const view = { mode: "agenda", cursor: "", day: "", moved: false };

  /* ── plain helpers, deliberately duplicated rather than shared ──────── */
  const ce = s => String(s == null ? "" : s)
    .replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const parse = s => new Date(s + "T00:00:00Z");
  const iso = d => d.toISOString().slice(0, 10);
  const addDays = (s, n) => { const d = parse(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const addMonths = (s, n) => {
    const d = parse(s.slice(0, 8) + "01"); d.setUTCMonth(d.getUTCMonth() + n); return iso(d);
  };
  const monthStart = s => s.slice(0, 8) + "01";
  const weekStart = s => addDays(s, -((parse(s).getUTCDay() + 6) % 7));
  const dowIndex = s => (parse(s).getUTCDay() + 6) % 7;
  const daysInMonth = s => new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7), 0)).getUTCDate();
  const money = it => (!it.amount ? "" :
    it.currency + " " + (Math.abs(it.amount) >= 1e6 ? (it.amount / 1e6).toFixed(1) + "m"
      : Math.abs(it.amount) >= 1e3 ? Math.round(it.amount / 1e3) + "k" : Math.round(it.amount)));

  function loadStore() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY));
      if (raw && raw.patch) store = { patch: raw.patch || {}, added: raw.added || [],
                                      hidden: raw.hidden || [] };
    } catch (e) { /* private mode: the diary is still readable, just not editable */ }
  }
  function saveStore() {
    try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* ok */ }
  }

  /* ── the merged list ─────────────────────────────────────────────────
   * Engine rows, with her patches applied and her hidden rows dropped, plus
   * whatever she has added herself. `source` survives so the UI can always
   * say which is which. */
  function items(cohort) {
    const out = [];
    (B.upcoming || []).forEach(it => {
      if (store.hidden.indexOf(it.id) >= 0) return;
      const patch = store.patch[it.id];
      out.push(Object.assign({ source: "engine", edited: !!patch }, it, patch || {}));
    });
    store.added.forEach(it => out.push(Object.assign({ source: "rm", edited: false }, it)));
    const list = out.filter(it => !cohort || !it.client_id || cohort.has(it.client_id));
    list.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 :
                         (b.usd || 0) - (a.usd || 0)));
    return list;
  }

  /* What the current month or week actually holds. */
  function inPeriod(list) {
    const all = list || items(null);
    if (view.mode === "month") {
      const m = view.cursor.slice(0, 7);
      return all.filter(it => it.date.slice(0, 7) === m);
    }
    const s = weekStart(view.cursor), e = addDays(s, 6);
    return all.filter(it => it.date >= s && it.date <= e);
  }

  function byDate(list) {
    const m = {};
    list.forEach(it => (m[it.date] = m[it.date] || []).push(it));
    return m;
  }

  /* ── render ──────────────────────────────────────────────────────────── */
  function html(cohort, cohortLabel) {
    const list = items(cohort);
    const body = view.mode === "month" ? month(list)
               : view.mode === "week" ? week(list)
               : agenda(list, cohort, cohortLabel);
    const nav = view.mode === "agenda" ? "" : `
      <div class="cal-nav">
        <button class="cal-step" data-cal-step="-1" aria-label="Previous">&#8249;</button>
        <span class="cal-period n">${ce(periodLabel())}</span>
        <span class="cal-count n">${inPeriod().length || "none"}</span>
        <button class="cal-step" data-cal-step="1" aria-label="Next">&#8250;</button>
        <button class="cal-today" data-cal-today>Today</button>
      </div>`;

    return `<aside class="diary" data-cal>
      <div class="cal-head">
        <h2>Key upcoming events</h2>
        <div class="cal-modes" role="tablist" aria-label="Calendar view">
          ${["agenda", "month", "week"].map(m =>
            `<button role="tab" data-cal-mode="${m}" aria-selected="${view.mode === m}">${
              m[0].toUpperCase() + m.slice(1)}</button>`).join("")}
        </div>
      </div>
      ${nav}
      ${body}
      <div class="cal-foot">
        <button class="cal-add" data-cal-new="">+ Add an entry</button>
        ${store.hidden.length ? `<button class="cal-restore" data-cal-restore>Restore ${
          store.hidden.length} hidden</button>` : ""}
        <span class="cal-note">Engine rows come from <code>planned_cash_needs</code>,
          <code>commitments</code> and KYC dates. Yours are marked. Both are editable;
          an edited engine row can be put back.</span>
      </div>
    </aside>`;
  }

  function periodLabel() {
    const c = view.cursor;
    if (view.mode === "month") return MONTHS[+c.slice(5, 7) - 1] + " " + c.slice(0, 4);
    const end = addDays(weekStart(c), 6);
    return c.slice(8) + " " + MONTHS[+c.slice(5, 7) - 1].slice(0, 3) + " – "
         + end.slice(8) + " " + MONTHS[+end.slice(5, 7) - 1].slice(0, 3) + " " + end.slice(0, 4);
  }

  /* Agenda. With no cohort selected this is the engine's own spotlight — its
   * judgement about which five matter, KYC admin capped at one. With a cohort
   * selected that judgement no longer applies, so it is simply the nearest few
   * in the cohort, and the caption says so. */
  function agenda(list, cohort, cohortLabel) {
    // With a cohort selected the engine's spotlight no longer applies — that
    // judgement was about the whole book. Show everything the cohort has.
    const rows = cohort ? list
                        : list.filter(it => it.spotlight || it.source === "rm");
    if (!rows.length) {
      return `<p class="cal-empty">${cohort
        ? "Nothing dated is outstanding for " + ce(cohortLabel || "this group") + "."
        : "Nothing dated across the book."}</p>`;
    }
    // A cohort agenda groups by client. "5 Act" used to open a flat list of
    // eight rows, because three of those five clients owe more than one thing —
    // so the tile said 5, the caption said 11 and the list showed 8, and the
    // reader had to reconcile three numbers to trust any of them. Grouped, the
    // number of names equals the number on the tile, and each client's rows sit
    // under their own name where the repetition is obvious rather than
    // confusing. Clients are ordered by their nearest obligation, so the
    // diary is still answering "what is coming".
    if (cohort) return agendaByClient(rows, cohortLabel);
    return `<ol class="diary-list">
      ${rows.slice(0, 8).map((it, i) => `<li style="--i:${i}">
        <div class="diary-row"${it.client_id ? ` data-client="${ce(it.client_id)}"` : ""}
            role="button" tabindex="0">
          <span class="diary-when">
            <span class="dd n">${it.date.slice(8)}</span>
            <span class="mm">${MONTHS[+it.date.slice(5, 7) - 1].slice(0, 3).toUpperCase()}</span>
          </span>
          <span class="diary-what">
            <span class="who">${ce(it.client || "Across the book")}${
              it.source === "rm" ? `<span class="cal-own">yours</span>`
              : it.edited ? `<span class="cal-own">edited</span>` : ""}</span>
            <span class="txt">${ce(it.what)}${money(it) ? " (" + ce(money(it)) + ")" : ""}${
              recurNote(it)}</span>
          </span>
        </div>
        <button class="cal-edit" data-cal-open="${ce(it.id)}"
          aria-label="Edit this diary entry">Edit</button>
      </li>`).join("")}
    </ol>
    ${rows.length > 8 ? `<p class="cal-more">${rows.length - 8} further out &mdash;
      switch to Month or Week to see them.</p>` : ""}
    <p class="diary-foot">Dated obligations across the book, nearest first. Amounts are
      what the client owes, in their own currency.</p>`;
  }

  /* One block per client, ordered by whichever of their obligations lands
   * first. Nothing is truncated: the caption's count and the visible rows are
   * the same set, because a hidden remainder is what made the flat list need
   * explaining in the first place. */
  function agendaByClient(rows, cohortLabel) {
    const groups = [];
    const byId = {};
    rows.forEach(it => {
      const key = it.client_id || "_book";
      if (!byId[key]) { byId[key] = { key: key, name: it.client || "Across the book",
                                      client_id: it.client_id || "", items: [] };
                        groups.push(byId[key]); }
      byId[key].items.push(it);
    });

    return `<p class="cal-scope"><b class="n">${groups.length}</b>
      client${groups.length === 1 ? "" : "s"} in view &middot; <b class="n">${rows.length}</b>
      dated obligation${rows.length === 1 ? "" : "s"} between them &middot;
      ${ce(cohortLabel || "filtered")}</p>
    <ol class="diary-list grouped">
      ${groups.map((g, gi) => `<li class="dg" style="--i:${gi}">
        <div class="dg-head"${g.client_id ? ` data-client="${ce(g.client_id)}"` : ""}
            role="button" tabindex="0">
          <span class="dg-nm">${ce(g.name)}</span>
          <span class="dg-n n">${g.items.length}</span>
        </div>
        <ol class="dg-items">
          ${g.items.map(it => `<li>
            <div class="diary-row bare">
              <span class="diary-when">
                <span class="dd n">${it.date.slice(8)}</span>
                <span class="mm">${MONTHS[+it.date.slice(5, 7) - 1].slice(0, 3).toUpperCase()}</span>
              </span>
              <span class="diary-what">
                <span class="txt">${ce(it.what)}${money(it) ? " (" + ce(money(it)) + ")" : ""}${
                  recurNote(it)}${it.source === "rm" ? `<span class="cal-own">yours</span>`
                  : it.edited ? `<span class="cal-own">edited</span>` : ""}</span>
              </span>
            </div>
            <button class="cal-edit" data-cal-open="${ce(it.id)}"
              aria-label="Edit this diary entry">Edit</button>
          </li>`).join("")}
        </ol>
      </li>`).join("")}
    </ol>
    <p class="diary-foot">One block per client, ordered by whichever obligation lands
      first. A client owing two things appears once with two rows &mdash; which is why
      there are more rows here than names.</p>`;
  }

  function month(list) {
    const map = byDate(list);
    const first = monthStart(view.cursor);
    const lead = dowIndex(first), n = daysInMonth(first);
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(null);
    for (let d = 1; d <= n; d++) cells.push(first.slice(0, 8) + String(d).padStart(2, "0"));
    while (cells.length % 7) cells.push(null);

    const inMonth = view.day && view.day.slice(0, 7) === first.slice(0, 7);
    const sel = inMonth ? (map[view.day] || []) : null;
    return `<div class="cal-grid" role="grid">
      ${DOW.map(d => `<div class="cal-dow">${d[0]}</div>`).join("")}
      ${cells.map(date => {
        if (!date) return `<div class="cal-cell empty"></div>`;
        const its = map[date] || [];
        return `<div class="cal-cell${date === B.today ? " today" : ""}${
            view.day === date ? " picked" : ""}" data-cal-day="${date}" tabindex="0" role="gridcell"
            aria-label="${date}, ${its.length} entr${its.length === 1 ? "y" : "ies"}">
          <span class="cal-num n">${+date.slice(8)}</span>
          <span class="cal-dots">${its.slice(0, 4).map(it =>
            `<i class="k-${kindClass(it)}"></i>`).join("")}</span>
        </div>`;
      }).join("")}
    </div>
    ${sel ? dayList(view.day, sel)
          : `<p class="cal-hint">Pick a day to read what falls on it, or drag an entry
             onto another day to move it.</p>`}`;
  }

  function week(list) {
    const map = byDate(list);
    const s = weekStart(view.cursor);
    return `<ol class="cal-week">
      ${DOW.map((d, i) => {
        const date = addDays(s, i), its = map[date] || [];
        return `<li class="cal-wday${date === B.today ? " today" : ""}" data-cal-day="${date}">
          <div class="cal-wlab"><b>${d}</b><span class="n">${+date.slice(8)}</span></div>
          <div class="cal-wits">
            ${its.length ? its.map(it => chip(it, true)).join("")
              : `<button class="cal-blank" data-cal-new="${date}">&#43;</button>`}
          </div>
        </li>`;
      }).join("")}
    </ol>`;
  }

  function dayList(date, its) {
    return `<div class="cal-day">
      <div class="cal-day-head">
        <b>${DOW[dowIndex(date)]} ${+date.slice(8)} ${MONTHS[+date.slice(5, 7) - 1]}</b>
        <button class="cal-add sm" data-cal-new="${date}">+ Add here</button>
      </div>
      ${its.length ? its.map(it => chip(it, true)).join("")
        : `<p class="cal-hint" style="margin:0">Nothing falls on this day.</p>`}
    </div>`;
  }

  /* `due_from` in the source row is an annual need's FIRST occurrence. When the
   * diary shows a later one, say which, or the calendar looks like it disagrees
   * with planned_cash_needs.csv. */
  function recurNote(it) {
    if (!it.recurring) return "";
    return `<i class="cal-rec">${ce(it.recurrence || "recurring")} &middot; next of a
      series that began ${ce(it.first_due)}</i>`;
  }

  function kindClass(it) {
    return it.source === "rm" ? "own" : (it.kind || "Note").split(" ")[0].toLowerCase();
  }

  /* The wide chip names the client. The week grid used the narrow one, which
   * showed only the description — "KYC review falls due" with no idea whose. */
  function chip(it, wide) {
    return `<button class="cal-chip k-${kindClass(it)}${wide ? " wide" : ""}${
        it.edited ? " edited" : ""}" draggable="true"
        data-cal-open="${ce(it.id)}" title="${ce(it.client || "Across the book")} — ${
          ce(it.what)}${money(it) ? " (" + ce(money(it)) + ")" : ""}${
          it.recurring ? " — " + ce(it.recurrence) + ", next of a series that began "
            + ce(it.first_due) : ""}">
      ${wide ? `<span class="cc-who">${ce(it.client || "Across the book")}${
        it.source === "rm" ? `<i class="cc-own">yours</i>`
        : it.edited ? `<i class="cc-own">edited</i>` : ""}</span>` : ""}
      <span class="cc-what">${ce(it.what)}${
        wide && money(it) ? ` <b>${ce(money(it))}</b>` : ""}${wide ? recurNote(it) : ""}</span>
    </button>`;
  }

  /* ── the editor ──────────────────────────────────────────────────────── */
  function editor(id, presetDate) {
    const it = id ? items(null).filter(x => x.id === id)[0] : null;
    const isNew = !it;
    const v = it || { id: "", date: presetDate || B.today, client_id: "", what: "",
                      currency: "USD", amount: 0, kind: "Meeting", certainty: "Confirmed",
                      source: "rm" };
    const clients = Object.keys(B.clients).map(cid =>
      `<option value="${cid}"${v.client_id === cid ? " selected" : ""}>${
        ce(B.clients[cid].profile.client_name)}</option>`).join("");

    return `
    <div class="scrim" data-cal-close></div>
    <aside class="drawer narrow" role="dialog" aria-modal="true" aria-label="Diary entry">
      <div class="drawer-head">
        <button class="close" data-cal-close>Close</button>
        <div class="eyebrow">${isNew ? "New diary entry"
          : v.source === "rm" ? "Your entry" : "From the book"}</div>
        <h2>${isNew ? "Add to the diary" : ce(v.what)}</h2>
        ${v.recurring ? `<p class="cal-src"><b>${ce(v.recurrence)}.</b>
          <code>planned_cash_needs.csv</code> records this as first due
          ${ce(v.first_due)}; the date shown is the next occurrence on or after
          today. Editing it moves this occurrence only.</p>` : ""}
        ${v.client_id ? `<button class="cal-goto" data-cal-goto="${ce(v.client_id)}">Open
          ${ce(B.clients[v.client_id].profile.client_name)}'s dossier &rarr;</button>` : ""}
        ${!isNew && v.source === "engine" ? `<p class="cal-src">Generated by the engine from
          <code>${ce(v.kind === "Review" ? "clients.kyc_review_due"
            : v.kind === "Commitment" ? "commitments" : "planned_cash_needs")}</code>.
          Editing it here changes your diary, never the underlying record.</p>` : ""}
      </div>
      <div class="drawer-body">
        <div class="cal-form">
          <label>What<input type="text" id="calWhat" value="${ce(v.what)}"></label>
          <label>Date<input type="date" id="calDate" value="${ce(v.date)}"></label>
          <label>Client<select id="calClient">
            <option value="">— across the book —</option>${clients}</select></label>
          <div class="cal-pair">
            <label>Currency<input type="text" id="calCcy" maxlength="3" value="${
              ce(v.currency || "")}"></label>
            <label>Amount<input type="number" id="calAmt" step="any" value="${
              v.amount || 0}"></label>
          </div>
          <div class="cal-pair">
            <label>Kind<select id="calKind">${KINDS.map(k =>
              `<option${(v.kind || "Note") === k ? " selected" : ""}>${k}</option>`).join("")}</select></label>
            <label>Certainty<select id="calCert">${CERTAINTY.map(k =>
              `<option${(v.certainty || "Confirmed") === k ? " selected" : ""}>${k}</option>`)
              .join("")}</select></label>
          </div>
        </div>
      </div>
      <div class="drawer-foot">
        <div class="btn-row">
          <button class="btn" data-cal-save="${ce(v.id)}">${isNew ? "Add to the diary" : "Save"}</button>
          ${isNew ? "" : v.source === "rm"
            ? `<button class="btn ghost" data-cal-delete="${ce(v.id)}">Delete</button>`
            : `<button class="btn ghost" data-cal-hide="${ce(v.id)}">Hide</button>`}
          ${!isNew && v.source === "engine" && v.edited
            ? `<button class="btn ghost" data-cal-reset="${ce(v.id)}">Reset to the engine's</button>` : ""}
        </div>
      </div>
    </aside>`;
  }

  function readForm() {
    const g = id => document.getElementById(id);
    return {
      what: g("calWhat").value.trim() || "Untitled",
      date: g("calDate").value || B.today,
      client_id: g("calClient").value,
      client: g("calClient").value ? B.clients[g("calClient").value].profile.client_name : "",
      currency: g("calCcy").value.trim().toUpperCase(),
      amount: parseFloat(g("calAmt").value) || 0,
      kind: g("calKind").value,
      certainty: g("calCert").value,
    };
  }

  function closeEditor() {
    const host = document.getElementById("drawer");
    if (host) host.innerHTML = "";
  }

  function openEditor(id, presetDate) {
    const host = document.getElementById("drawer");
    host.innerHTML = editor(id, presetDate);
    host.querySelectorAll("[data-cal-close]").forEach(b =>
      b.addEventListener("click", closeEditor));

    host.querySelector("[data-cal-save]").addEventListener("click", e => {
      const target = e.currentTarget.dataset.calSave;
      const patch = readForm();
      if (!target) {
        store.added.push(Object.assign({ id: "RM-" + Date.now().toString(36), usd: 0,
                                         spotlight: false }, patch));
      } else if (store.added.some(x => x.id === target)) {
        store.added = store.added.map(x => (x.id === target ? Object.assign(x, patch) : x));
      } else {
        store.patch[target] = patch;
      }
      saveStore(); closeEditor(); ctx.rerender();
    });

    const act = (attr, fn) => {
      const b = host.querySelector("[" + attr + "]");
      if (b) b.addEventListener("click", () => {
        fn(b.getAttribute(attr)); saveStore(); closeEditor(); ctx.rerender();
      });
    };
    act("data-cal-delete", id2 => { store.added = store.added.filter(x => x.id !== id2); });
    act("data-cal-hide", id2 => { if (store.hidden.indexOf(id2) < 0) store.hidden.push(id2); });
    act("data-cal-reset", id2 => { delete store.patch[id2]; });

    const goto = host.querySelector("[data-cal-goto]");
    if (goto) goto.addEventListener("click", () => {
      const cid = goto.getAttribute("data-cal-goto");
      closeEditor(); ctx.openClient(cid);
    });

    const first = document.getElementById("calWhat");
    if (first) first.focus();
  }

  /* ── wiring ──────────────────────────────────────────────────────────── */
  function wire() {
    const root = document.querySelector("[data-cal]");
    if (!root) return;

    root.querySelectorAll("[data-cal-mode]").forEach(b =>
      b.addEventListener("click", () => {
        view.mode = b.dataset.calMode;
        if (!view.cursor) view.cursor = B.today;
        // Month and week open on today, the way every calendar does. The one
        // exception is a period with nothing in it at all, which reads as a
        // broken grid rather than a quiet week — then jump to the nearest thing
        // that is actually coming. Once she has navigated, never move on her.
        if (view.mode !== "agenda" && !view.moved && !inPeriod().length) {
          const all = items(null);
          const next = all.filter(it => it.date >= B.today)[0] || all[all.length - 1];
          if (next) { view.cursor = next.date; view.day = next.date; }
        }
        ctx.rerender();
      }));
    root.querySelectorAll("[data-cal-step]").forEach(b =>
      b.addEventListener("click", () => {
        const n = +b.dataset.calStep;
        view.cursor = view.mode === "month" ? addMonths(view.cursor, n)
                                            : addDays(view.cursor, n * 7);
        view.day = ""; view.moved = true; ctx.rerender();
      }));
    const t = root.querySelector("[data-cal-today]");
    if (t) t.addEventListener("click", () => {
      view.cursor = B.today; view.day = B.today; view.moved = true; ctx.rerender();
    });
    const rest = root.querySelector("[data-cal-restore]");
    if (rest) rest.addEventListener("click", () => { store.hidden = []; saveStore();
                                                     ctx.rerender(); });

    root.querySelectorAll("[data-cal-open]").forEach(el => {
      const go = e => { e.stopPropagation(); openEditor(el.dataset.calOpen); };
      el.addEventListener("click", go);
      el.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(e); }
      });
    });
    root.querySelectorAll("[data-cal-new]").forEach(el =>
      el.addEventListener("click", e => {
        e.stopPropagation(); openEditor(null, el.dataset.calNew || view.day || B.today);
      }));
    root.querySelectorAll("[data-cal-day]").forEach(el => {
      const pick = () => { view.day = el.dataset.calDay; ctx.rerender(); };
      el.addEventListener("click", pick);
      el.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); pick(); }
      });
    });

    // Dragging a chip onto another day moves it. The same patch path as the
    // form, so an engine row dragged is an engine row edited, and resettable.
    let dragging = null;
    root.querySelectorAll(".cal-chip").forEach(c => {
      c.addEventListener("dragstart", e => {
        dragging = c.dataset.calOpen; c.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", dragging); } catch (err) { /* ok */ }
      });
      c.addEventListener("dragend", () => { dragging = null; c.classList.remove("dragging"); });
    });
    root.querySelectorAll("[data-cal-day]").forEach(cell => {
      cell.addEventListener("dragover", e => {
        if (!dragging) return;
        e.preventDefault(); cell.classList.add("over");
      });
      cell.addEventListener("dragleave", () => cell.classList.remove("over"));
      cell.addEventListener("drop", e => {
        e.preventDefault(); cell.classList.remove("over");
        if (!dragging) return;
        moveTo(dragging, cell.dataset.calDay);
        dragging = null; ctx.rerender();
      });
    });
  }

  function moveTo(id, date) {
    if (store.added.some(x => x.id === id)) {
      store.added = store.added.map(x => (x.id === id ? Object.assign(x, { date }) : x));
    } else {
      const cur = items(null).filter(x => x.id === id)[0];
      if (!cur) return;
      store.patch[id] = Object.assign({}, store.patch[id] || {}, {
        what: cur.what, client_id: cur.client_id, client: cur.client,
        currency: cur.currency, amount: cur.amount, kind: cur.kind,
        certainty: cur.certainty, date: date,
      });
    }
    saveStore();
  }

  return {
    init(bundle, context) {
      B = bundle; ctx = Object.assign(ctx, context || {});
      view.cursor = bundle.today; view.day = bundle.today;
      loadStore();
    },
    html, wire,
    mode: () => view.mode,
  };
})();
