#!/usr/bin/env node
/* The workbench in a real browser — headless Chrome over the DevTools protocol.
 * No dependencies: Node 22 or later (for the built-in WebSocket) and Chrome.
 *
 *   node tests/browser/run.mjs               # every check
 *   node tests/browser/run.mjs --shots DIR   # and save the README screenshots
 *
 * Two copies of the workbench are driven.
 *
 *   static   The repository served as plain files, as GitHub Pages serves it.
 *            No server and no key, so translation can only replay what was
 *            recorded in advance — and only for the exact text it was made from.
 *   served   engine/serve.py against a stand-in for the Messages API, run from
 *            a scratch copy so that nothing is cached into the repository. Every
 *            request the stand-in receives is kept, and the check that no
 *            client's name left the machine is made on those, not assumed.
 *
 * Unit tests cover the engine and the checks in Python; this covers what only a
 * browser can show: every screen renders, the browser's ranking agrees with
 * the engine's, nothing scrolls sideways on a phone, and the composer's
 * translation path behaves in both copies. */
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SHOTS = process.argv.includes("--shots")
  ? path.resolve(process.argv[process.argv.indexOf("--shots") + 1]) : null;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const children = [];
process.on("exit", () => children.forEach(c => { try { c.kill(); } catch (e) { /* gone */ } }));

// ── results ────────────────────────────────────────────────────────────────
let passed = 0, failed = 0;
function check(name, ok, detail) {
  if (ok) { passed++; console.log("  ok    " + name); }
  else { failed++; console.log("  FAIL  " + name + (detail ? "\n        " + detail : "")); }
}

// ── processes ──────────────────────────────────────────────────────────────
function run(cmd, args, opts = {}) {
  const c = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts });
  children.push(c);
  c.output = "";
  c.stdout.on("data", d => { c.output += d; });
  c.stderr.on("data", d => { c.output += d; });
  return c;
}

async function until(fn, what, ms = 15000) {
  const t0 = Date.now();
  for (;;) {
    try { const v = await fn(); if (v) return v; } catch (e) { /* not yet */ }
    if (Date.now() - t0 > ms) throw new Error("timed out waiting for " + what);
    await sleep(150);
  }
}

const freePort = () => new Promise(r => {
  const s = http.createServer().listen(0, "127.0.0.1", () => {
    const p = s.address().port; s.close(() => r(p));
  });
});

function findChrome() {
  const candidates = [
    process.env.CHROME,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const hit = candidates.find(p => fs.existsSync(p));
  if (!hit) throw new Error("Chrome not found; set CHROME to its path");
  return hit;
}

function python() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venv = path.join(ROOT, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python3";
}

// ── a page, over the DevTools protocol ─────────────────────────────────────
class Page {
  static async open() {
    const port = await freePort();
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "canary-chrome-"));
    const flags = ["--headless=new", "--remote-debugging-port=" + port,
      "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
      "--hide-scrollbars", "--mute-audio", "about:blank"];
    if (process.platform === "linux") flags.unshift("--no-sandbox", "--disable-dev-shm-usage");
    run(findChrome(), flags);
    const targets = await until(async () => {
      const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      return t.some(x => x.type === "page") && t;
    }, "Chrome");
    const page = new Page(targets.find(x => x.type === "page").webSocketDebuggerUrl);
    await page.ready;
    await page.send("Page.enable");
    await page.send("Runtime.enable");
    return page;
  }

  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0; this.pending = {}; this.errors = [];
    this.ready = new Promise(r => this.ws.addEventListener("open", r));
    this.ws.addEventListener("message", e => {
      const m = JSON.parse(e.data);
      if (m.id && this.pending[m.id]) { this.pending[m.id](m); delete this.pending[m.id]; }
      if (m.method === "Runtime.exceptionThrown") {
        const d = m.params.exceptionDetails;
        this.errors.push((d.exception && d.exception.description) || d.text);
      }
      if (m.method === "Runtime.consoleAPICalled"
          && (m.params.type === "error" || m.params.type === "warning")) {
        this.errors.push("console." + m.params.type + ": "
          + m.params.args.map(a => a.value || a.description).join(" "));
      }
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending[id] = m => (m.error ? reject(new Error(method + ": " + m.error.message))
                                       : resolve(m.result));
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  /* Evaluate an async function body in the page and return its value. */
  async eval(body) {
    const r = await this.send("Runtime.evaluate", {
      expression: "(async () => {" + body + "})()", awaitPromise: true, returnByValue: true,
    });
    if (r.exceptionDetails) {
      throw new Error((r.exceptionDetails.exception || {}).description || r.exceptionDetails.text);
    }
    return r.result.value;
  }

  async viewport(width, height) {
    await this.send("Emulation.setDeviceMetricsOverride",
      { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  }

  async go(url) {
    await this.send("Page.navigate", { url });
    await until(() => this.eval("return document.readyState === 'complete' && !!window.FINDINGS"
      + " && typeof renderBook === 'function'"), "the workbench to load");
    await sleep(300);
  }

  async shot(file, clip) {
    const r = await this.send("Page.captureScreenshot", { format: "png", ...(clip ? { clip } : {}) });
    fs.writeFileSync(file, Buffer.from(r.data, "base64"));
  }
}

// ── the stand-in for the Messages API ──────────────────────────────────────
// Answers like the real endpoint, with a "translation" that keeps every token
// and figure. The marker CONVERT makes it change one figure, so the check that
// should catch exactly that has something to catch.
function mockApi() {
  const bodies = [];
  const server = http.createServer((req, res) => {
    let raw = "";
    req.on("data", d => { raw += d; });
    req.on("end", () => {
      bodies.push(raw);
      const body = JSON.parse(raw || "{}");
      const payload = JSON.parse(body.messages[0].content);
      let letter = "【譯】" + payload.letter;
      if (letter.includes("CONVERT")) letter = letter.replace(/\d+\.\d+/, "999.9");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        id: "msg_test", type: "message", role: "assistant", model: body.model,
        stop_reason: "end_turn", stop_sequence: null,
        content: [{ type: "text",
                    text: JSON.stringify({ translation: letter, translator_note: "" }) }],
        usage: { input_tokens: 1, output_tokens: 1 },
      }));
    });
  });
  return new Promise(r => server.listen(0, "127.0.0.1",
    () => r({ port: server.address().port, bodies, server })));
}

// ════════════════════════════════════════════════════════════════════════════
async function staticCopy(page) {
  console.log("\nstatic copy — the repository served as plain files");
  const port = await freePort();
  run("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1",
                  "--directory", ROOT]);
  await until(() => fetch(`http://127.0.0.1:${port}/`).then(r => r.ok), "the static server");
  const base = `http://127.0.0.1:${port}`;

  await page.viewport(1440, 1000);
  await page.go(base + "/");
  check("the root opens the workbench",
    (await page.eval("return location.pathname")) === "/app/");
  await page.eval("localStorage.clear()");
  await page.go(base + "/app/");

  const parity = await page.eval("return parityCheck(window.FINDINGS)");
  check("the browser's ranking agrees with the engine's", parity.length === 0,
    JSON.stringify(parity).slice(0, 300));

  // every client, every tab, every composer
  const sweep = await page.eval(`
    const bad = [];
    for (const cid of Object.keys(B.clients)) {
      for (const [tab] of TABS) {
        openClient(cid); state.tab = tab; renderClient();
        const h1 = document.querySelector("#view h1");
        if (!h1 || h1.textContent !== B.clients[cid].profile.client_name) bad.push(cid + " " + tab);
      }
      for (const f of B.findings.filter(x => x.client_id === cid && x.status !== "waived")) {
        openDrawer(f.id);
        const t = document.getElementById("draftText").value;
        const src = (document.querySelector(".src-row") || {}).textContent || "";
        if (!t || /\\[\\[|undefined|NaN/.test(t)) bad.push(f.id + " text");
        if (!f.draft || !/Drafted by Claude/.test(src) || !/in Claude Code/.test(src))
          bad.push(f.id + " provenance");
        closeDrawer();
      }
    }
    return bad;`);
  check("every client renders on every tab, and every composer opens on a signed, "
    + "attributed Claude draft", sweep.length === 0, sweep.slice(0, 8).join(", "));

  // the start-here strip
  const start = await page.eval(`
    renderBook();
    const stops = [...document.querySelectorAll("[data-start]")];
    if (stops.length !== 3) return "stops: " + stops.length;
    stops[0].click();
    const fid = stops[0].dataset.fid;
    if (state.view !== "client" || !document.getElementById("f-" + fid)) return "stop 1";
    state.view = "book"; renderBook();
    document.querySelectorAll("[data-start]")[1].click();
    if (!document.getElementById("draftText")) return "stop 2";
    closeDrawer(); state.view = "book"; renderBook();
    document.querySelectorAll("[data-start]")[2].click();
    if (!document.querySelector("#drawer .tune-row")) return "stop 3";
    closeDrawer(); renderBook();
    return "ok";`);
  check("the start-here strip's three stops open what they promise", start === "ok", start);

  // translation with no server: replay the recording, refuse anything else
  const replay = await page.eval(`
    const rec = B.recorded_translations || [];
    if (!rec.length) return "no recordings in the bundle";
    for (const r of rec) {
      openDrawer(r.finding_id);
      const use = document.getElementById("useRecording");
      if (!use) return r.finding_id + ": no recorded amendment offered";
      use.click();
      if (document.getElementById("draftText").value !== r.source) return r.finding_id + ": source";
      document.getElementById("translateBtn").click();
      await new Promise(res => setTimeout(res, 100));
      const s = state.sync[r.finding_id];
      if (!s || !s.clean || !s.recorded || s.target !== r.text) return r.finding_id + ": replay";
      if (!/recorded in advance/.test(document.querySelector(".tr-meta").textContent))
        return r.finding_id + ": not labelled as a recording";
      if (document.querySelector("[data-verdict=Accepted]").disabled) return r.finding_id + ": accept";
      closeDrawer();
    }
    // an edit the recording was not made from is refused, not replayed
    const r = rec[0];
    delete state.sync[r.finding_id]; delete state.noteLang[r.finding_id];
    Object.keys(state.drafts).filter(k => k.startsWith(r.finding_id + "|"))
      .forEach(k => delete state.drafts[k]);
    openDrawer(r.finding_id);
    document.getElementById("useRecording").click();
    document.getElementById("draftText").value = r.source + " Edited.";
    document.getElementById("translateBtn").click();
    await new Promise(res => setTimeout(res, 100));
    const err = document.getElementById("translateErr");
    if (err.hidden || !/word for word/.test(err.textContent)) return "an edit was not refused";
    closeDrawer();
    // a note with no recording offers no button that cannot work
    const other = B.findings.find(f => f.draft && f.draft.language !== "English"
      && !rec.some(x => x.finding_id === f.id));
    openDrawer(other.id);
    const off = document.getElementById("translateBtn").disabled;
    closeDrawer();
    return off ? "ok" : other.id + ": translate offered with nothing to replay";`);
  check("with no server, translation replays only the recorded amendment, labelled as one",
    replay === "ok", replay);

  // nothing scrolls sideways on a phone
  await page.eval("localStorage.clear()");
  await page.viewport(390, 844);
  await page.go(base + "/app/");
  const phone = await page.eval(`
    const wide = [];
    // against clientWidth, not innerWidth: on an emulated phone the layout
    // viewport widens to fit the content, so innerWidth hides the very overflow
    // being looked for
    const over = () => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)
      - document.documentElement.clientWidth;
    renderBook(); if (over() > 1) wide.push("book +" + over());
    for (const cid of Object.keys(B.clients)) {
      for (const [tab] of TABS) {
        openClient(cid); state.tab = tab; renderClient();
        document.querySelectorAll("details").forEach(d => { d.open = true; });
        if (over() > 1) wide.push(cid + " " + tab + " +" + over());
      }
    }
    return wide;`);
  check("at 390px wide, the book and every dossier tab fit the screen", phone.length === 0,
    phone.slice(0, 8).join(", "));
  await page.eval("state.view = 'book'; renderBook(); window.scrollTo(0, 0)");
  if (SHOTS) await page.shot(path.join(SHOTS, "phone.png"));

  // screenshots for the README, from the same copy a visitor would see
  if (SHOTS) {
    await page.viewport(1440, 1000);
    await page.eval("localStorage.clear()");
    await page.go(base + "/app/");
    await sleep(1600);
    await page.shot(path.join(SHOTS, "book.png"));
    const y = await page.eval(`
      openClient("CL-0002");
      const el = document.getElementById("f-FUN-CL-0002");
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 24);
      return window.scrollY;`);
    await sleep(1600);
    await page.shot(path.join(SHOTS, "dossier.png"));
    await page.viewport(1440, 900);
    await page.eval("window.scrollTo(0, 0); openDrawer('FUN-CL-0002')");
    await sleep(500);
    await page.shot(path.join(SHOTS, "composer-1.png"));
    await page.eval("document.getElementById('useRecording').click()");
    await sleep(400);
    await page.shot(path.join(SHOTS, "composer-2.png"));
    await page.eval("document.getElementById('translateBtn').click()");
    await sleep(600);
    await page.eval("document.querySelector('.drawer-body').scrollTop = 0");
    await page.shot(path.join(SHOTS, "composer-3.png"));
    await page.eval(`document.querySelector(".tr-check").scrollIntoView({ block: "center" })`);
    await sleep(300);
    await page.shot(path.join(SHOTS, "composer.png"));
    void y;
  }
}

// ════════════════════════════════════════════════════════════════════════════
async function servedCopy(page) {
  console.log("\nserved copy — engine/serve.py, against a stand-in for the Messages API");
  const api = await mockApi();
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "canary-served-"));
  for (const d of ["app", "assets", "engine"]) {
    fs.cpSync(path.join(ROOT, d), path.join(scratch, d), { recursive: true,
      filter: s => !s.includes(path.join("engine", "cache", "translate")) && !s.includes("__pycache__") });
  }
  const port = await freePort();
  const srv = run(python(), [path.join(scratch, "engine", "serve.py"), "--port", String(port)], {
    env: { ...process.env, ANTHROPIC_API_KEY: "test-key-not-real",
           ANTHROPIC_BASE_URL: `http://127.0.0.1:${api.port}` },
  });
  const health = await until(() => fetch(`http://127.0.0.1:${port}/api/health`)
    .then(r => r.json()), "engine/serve.py").catch(e => ({ error: e.message + "\n" + srv.output }));
  check("serve.py is up with translation on", health.translate === true,
    JSON.stringify(health).slice(0, 400));
  if (health.translate !== true) return;

  await page.viewport(1440, 1000);
  await page.go(`http://127.0.0.1:${port}/app/`);
  await until(() => page.eval("return Translator.on"), "the composer to find the server");

  const flow = await page.eval(`
    const out = {};
    const translate = async (fid, edit) => {
      openDrawer(fid);
      const p = B.clients[F[fid].client_id].profile;
      state.noteLang[fid] = "English"; openDrawer(fid);
      document.getElementById("draftText").value += edit;
      document.getElementById("translateBtn").click();
      for (let i = 0; i < 100 && document.getElementById("translateBtn")
           && /Translating/.test(document.getElementById("translateBtn").textContent); i++)
        await new Promise(r => setTimeout(r, 100));
      const s = state.sync[fid];
      const accept = document.querySelector("[data-verdict=Accepted]");
      const res = { clean: s && s.clean, to: s && s.to, named: s && s.target.includes(p.client_name),
                    accept: accept && !accept.disabled, recorded: s && s.recorded };
      closeDrawer();
      return res;
    };
    out.chinese = await translate("FUN-CL-0002", "\\n\\nP.S. Thank you for your time.");
    out.korean = await translate("CON-CL-0011", "\\n\\nP.S. Thank you for your time.");
    out.convert = await translate("FIT-CL-0012", "\\n\\nCONVERT");
    return out;`);
  check("an amended English note translates into Traditional Chinese, names restored",
    flow.chinese.clean && flow.chinese.named && flow.chinese.accept && !flow.chinese.recorded,
    JSON.stringify(flow.chinese));
  check("and into Korean, a language the templates do not cover",
    flow.korean.clean && flow.korean.named && flow.korean.to === "Korean",
    JSON.stringify(flow.korean));
  check("a translation that changes a figure is marked and cannot be accepted",
    flow.convert.clean === false && flow.convert.accept === false, JSON.stringify(flow.convert));

  const leaked = [];
  const B = JSON.parse(fs.readFileSync(path.join(ROOT, "app", "findings.json"), "utf8"));
  const names = new Set(["Clara Teo", "Halden Rowe"]);
  ["CL-0002", "CL-0011", "CL-0012"].forEach(c => names.add(B.clients[c].profile.client_name));
  for (const body of api.bodies) for (const n of names) if (body.includes(n)) leaked.push(n);
  check(`no client, RM or bank name reached the API (${api.bodies.length} requests read)`,
    api.bodies.length >= 3 && leaked.length === 0, [...new Set(leaked)].join(", "));
  api.server.close();
}

// ════════════════════════════════════════════════════════════════════════════
(async () => {
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
  const page = await Page.open();
  try {
    await staticCopy(page);
    await servedCopy(page);
  } catch (e) {
    check("the run itself", false, e.stack);
  }
  check("no script errors or warnings in the page", page.errors.length === 0,
    page.errors.slice(0, 5).join("\n        "));
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
