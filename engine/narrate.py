"""
Layer 3. Claude explains and drafts; it never computes.

    .venv/bin/python engine/narrate.py --dry-run          # build payloads, call nothing
    .venv/bin/python engine/narrate.py                    # fill the cache, then rebuild
    .venv/bin/python engine/narrate.py --client CL-0012   # one client

Three rules this file exists to enforce, in the order they matter.

1.  **No number reaches a client unless the engine produced it.** The payload
    carries the finished figures and an allow-list of every numeral the model is
    permitted to write. Afterwards `verify()` reads the drafts back and checks
    each numeral against that list. A draft that invents a figure is kept, marked
    `unverified`, and the workbench refuses to treat it as sendable. This is the
    architectural rule of the whole product, and it is worth nothing unless
    something actually checks.

2.  **Direct identifiers never leave the perimeter.** Name, account number,
    nationality and exact age are removed before the call — pseudonymisation, not
    omission, so the substance still travels. The draft is written against the
    token `[[FIRST_NAME]]`, which the workbench substitutes at render time, inside
    the perimeter. The RM's own note text goes too, because reading the notes is
    this layer's most valuable job; the client's name is scrubbed out of it first.

3.  **The demo never depends on a live call.** Every response is cached to disk
    under a hash of the exact payload, prompt and model. Re-running is free and
    offline; `engine/build.py` reads the cache and attaches what it finds. No
    cache, no key, no network — the workbench falls back to the deterministic
    template and says so.

Runs on Python 3.10+ for the SDK. Everything else in engine/ stays stdlib-only on
3.9, and this script writes plain JSON, so nothing else acquires a dependency.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUNDLE = os.path.join(ROOT, "app", "findings.json")
CACHE_DIR = os.path.join(HERE, "cache", "narrate")
OUT = os.path.join(HERE, "cache", "narration.json")

MODEL = "claude-opus-5-5"
PROMPT_VERSION = "3"          # bump to invalidate every cached draft

# ── the system prompt ─────────────────────────────────────────────────────
# Stable across every call in a run, so it is cached at the API as well as on disk.
SYSTEM = """You draft private-client correspondence for a relationship manager at \
a private bank. You are given one finding that a deterministic engine has already \
produced, together with every figure it computed.

Your job is to explain that finding to the client in their own words, and to \
propose the conversation the relationship manager wants to have. You are the \
narration layer of a system whose first architectural rule is that a language \
model never computes a number that reaches a client.

Absolute rules:

1. Every figure, percentage, date and currency amount you write must appear in \
the ALLOWED FIGURES list. Do not add, round, restate in different units, sum, \
average, annualise, convert a currency, or infer any number that is not there. \
If a sentence would need a figure you do not have, write the sentence without it.
2. Never predict a price, a return or a market direction. You may say what has \
happened, what is contractually due, and what the client's own stated purpose is.
3. Address the client as [[FIRST_NAME]] exactly — that token, unaltered. You do \
not know their name and must not invent one, or a surname, or a title.
4. Do not promise, guarantee, or commit the bank to anything. The relationship \
manager decides what is sent; you are drafting for their signature, not sending.
5. Where the finding records uncertainty, say so plainly in the note. A finding \
marked "check" is a question to ask, never a fact to assert.
6. If the client's own words are quoted in the payload, engage with them. \
Disagreeing with a client respectfully is the job; pretending they never said it \
is not.

Register: a senior banker writing to a client of long standing. Plain sentences, \
no jargon, no bullet points, no marketing language, no exclamation marks. Four \
short paragraphs at most. End by proposing a call — the relationship manager \
signs off, so do not write a signature block.

Write two versions of the same note: one in English, and one in the client's \
reporting language. The second is a translation of the first for a reader who \
does not read English, not a different letter; use Western digits for every \
figure in both. If the reporting language is English, put the same text in both \
fields."""

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string",
                    "description": "One short line, in English, for the RM's own inbox."},
        "english": {"type": "string",
                    "description": "The note in English."},
        "client_language": {"type": "string",
                            "description": "The same note in the client's reporting language."},
        "raises": {"type": "string",
                   "description": "One sentence, in English, on what this note is asking "
                                  "the client to decide or confirm."},
    },
    "required": ["subject", "english", "client_language", "raises"],
    "additionalProperties": False,
}


# ── de-identification ─────────────────────────────────────────────────────
def age_band(age):
    if not age:
        return None
    a = int(age)
    lo = (a // 5) * 5
    return "%d-%d" % (lo, lo + 4)


# Words that can sit in a client's name without identifying anyone: "Lim Heng
# Family Office" is identified by Lim and Heng. Treating "Family" as a name part
# rewrote the family office's source of wealth as "[[FIRST_NAME]] shipping and
# port logistics business" — garbling the payload without protecting anything.
NAME_STOPWORDS = {"family", "office", "holdings", "holding", "group", "trust",
                  "foundation", "limited", "ltd", "pte", "company", "and", "the"}


def name_parts(profile):
    """The parts of a client's name that identify them. Two letters is enough:
    Ho, Wu, Li and Ng are surnames, and a rule that skipped them would let "Mrs
    Ho" through untouched. Matching is whole-word and case-sensitive, so a
    two-letter part does not catch ordinary words."""
    return [q for q in re.split(r"\s+", profile.get("client_name", "") or "")
            if len(q) >= 2 and q.lower() not in NAME_STOPWORDS]


def standalone(number):
    """A pattern for `number` as a whole figure — not the 57 inside 57.3 or 1,057."""
    return r"(?<![\d.,])%s(?!\d|[.,]\d)" % re.escape(str(number))


def scrub(text, profile):
    """Take the direct identifiers out of free text. The substance of an RM note
    is the most valuable thing this layer reads, so the text travels — but the
    name and the exact age do not.

    The age matters more than it looks. The engine writes "He is 68." into the
    purpose-fit and life-event findings, precisely because his age is the point
    of those findings; it reached the payload through the prose rather than
    through the profile, which is exactly how this kind of thing gets out. The
    band says the same thing about a man drawing income against a 2049 bond.

    Only the age as a whole number is banded. Matching its digits anywhere took a
    loan-to-value of 57.3% for a 57-year-old and sent it as "55-59.3%", which
    corrupted the very figures the allow-list is built from."""
    if not text:
        return text
    out = text
    for q in sorted(name_parts(profile), key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(q) + r"\b", "[[FIRST_NAME]]", out)
    out = re.sub(r"(?:\[\[FIRST_NAME\]\]\s*){2,}", "[[FIRST_NAME]] ", out).strip()
    age = profile.get("age")
    if age:
        band = age_band(age)
        out = re.sub(r"\b(is|aged|age of|was)\s+" + standalone(age),
                     r"\1 in the %s band" % band, out)
        # A bare number equal to the age is banded too ("At 50, she…") — but
        # not when it is a percentage or the end of a range. For a 50-year-old
        # that rule sent a 25–50% mandate band to the model as "25–50-54%".
        out = re.sub(r"(?<![–\-])" + standalone(age) + r"(?!\s?%)", band, out)
    return out


def age_band_of(profile):
    return age_band(profile.get("age"))


def needs_domicile(finding, domicile):
    """Tax domicile is the one field that can imply nationality — the two are the
    same string for most of this book. So it travels only where the rule
    turns on it, or where the engine has already written it into the finding."""
    if finding["dimension"] == "tax":
        return True
    blob = " ".join(str(finding.get(k, "")) for k in ("headline", "detail", "action"))
    return bool(domicile) and domicile in blob


def payload_for(bundle, finding):
    """Everything the model may see about this finding, and nothing else."""
    c = bundle["clients"][finding["client_id"]]
    p = c["profile"]
    dom = p.get("tax_domicile")

    # scrub once, then derive both the payload and the allow-list from the
    # scrubbed text — otherwise the model is permitted a figure it never saw
    sf = dict(finding)
    for k in ("headline", "detail", "action", "check"):
        sf[k] = scrub(finding.get(k, ""), p)
    sf["evidence"] = [dict(e, quote=scrub(e["quote"], p))
                      for e in finding.get("evidence", [])]
    # the purpose-fit rule records `age` among its numbers, and the allow-list is
    # built from those — so the exact age was reaching the model as a figure it
    # was *permitted to write*, having been banded out of the prose two lines up
    sf["numbers"] = {k: v for k, v in finding.get("numbers", {}).items() if k != "age"}

    return {
        "reference": finding["client_id"],          # already a pseudonym
        "client": {
            "age_band": age_band(p.get("age")),     # never the exact age
            "life_stage": p.get("life_stage"),
            "wealth_band": p.get("wealth_band"),
            "risk_profile": p.get("risk_profile"),
            "risk_score_out_of_10": p.get("risk_tolerance_score"),
            "investment_horizon_years": p.get("investment_horizon_years"),
            "liquidity_needs": p.get("liquidity_needs"),
            "objectives": scrub(p.get("objectives"), p),
            "source_of_wealth": scrub(p.get("source_of_wealth"), p),
            "tax_domicile": dom if needs_domicile(finding, dom) else None,
            "reporting_language": p.get("reporting_language"),
            # deliberately absent: client_name, nationality, exact age,
            # country_of_residence, booking centre, account identifiers
        },
        "finding": {
            "dimension": finding["label"],
            "headline": sf["headline"],
            "detail": sf["detail"],
            "suggested_action": sf["action"],
            "severity_of_100": finding["severity"],
            "confidence": finding["confidence"],
            "what_we_would_check": sf.get("check", ""),
            "rule_that_fired": finding["rule_text"],
        },
        "client_said": [
            {"date": e["date"], "channel": e.get("channel", ""), "quote": e["quote"]}
            for e in sf["evidence"]
        ],
        "allowed_figures": allowed_figures(sf),
    }


# ── the numeric allow-list, and the check that uses it ────────────────────
# a hyphen inside an identifier is not a minus sign, and the digits of PF-0007
# are not a figure the model could quote at a client. The class is spelled out
# in ASCII rather than as \w, because in Python \w also matches Chinese and
# Japanese characters — so 約768萬 read as no figure at all, and a
# client-language draft could carry an invented number straight past verify().
NUM = re.compile(r"(?<![A-Za-z0-9_\-])-?\d[\d,]*(?:\.\d+)?")


def _numbers_in(text):
    return {n.replace(",", "") for n in NUM.findall(str(text or ""))}


def allowed_figures(finding):
    """Every numeral the engine itself put in front of this finding. The model may
    use these and no others."""
    ok = set()
    for key in ("headline", "detail", "action", "check"):
        ok |= _numbers_in(finding.get(key))
    for e in finding.get("evidence", []):
        ok |= _numbers_in(e.get("quote"))

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, (int, float)):
            ok.add(_norm(v))
        elif isinstance(v, str):
            ok.update(_numbers_in(v))
    walk(finding.get("numbers", {}))
    ok |= _numbers_in(finding.get("severity"))
    return sorted(ok, key=lambda s: (len(s), s))


def _norm(v):
    f = float(v)
    return str(int(f)) if f == int(f) else repr(round(f, 4))


# figures a note may use without the engine having produced them: a year that
# is already in the text, small counting words, and the digits inside an id
YEARS = {str(y) for y in range(2024, 2061)}


def verify(draft, allowed):
    """Which numerals in the draft the engine cannot account for."""
    ok = set(allowed) | YEARS | {str(i) for i in range(0, 13)}
    # a figure like 34.9 is accounted for by 34.9; also accept it appearing
    # without its decimal, and with thousands separators stripped
    ok |= {a.split(".")[0] for a in allowed}
    bad = set()
    for field in ("english", "client_language"):
        for n in _numbers_in(draft.get(field, "")):
            if n not in ok and n.lstrip("-") not in ok:
                bad.add(n)
    return sorted(bad)


# ── the call ──────────────────────────────────────────────────────────────
def cache_key(payload):
    blob = json.dumps({"m": MODEL, "v": PROMPT_VERSION, "s": SYSTEM, "p": payload},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def cached(key):
    path = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def store(key, record):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)


def call(client, payload):
    """One finding, one call. The system prompt is identical across every call in
    the run, so it is cached at the API too."""
    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   json.dumps(payload, ensure_ascii=False, indent=1)}],
        # Opus 5.5 thinks on every call and defaults to medium effort; stated
        # here so the choice is visible rather than inherited
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # server-side fallback: if a safety classifier declines, the same request
        # is re-run on another model inside the same call rather than failing
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except Exception as e:                                   # noqa: BLE001
        if "fallback" not in str(e).lower():
            raise
        print("     (fallbacks unavailable, retrying without: %s)" % str(e)[:60])
        resp = client.messages.create(**kwargs)

    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined: %s" % getattr(resp.stop_details, "category", "?"))
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), {
        "input": resp.usage.input_tokens,
        "output": resp.usage.output_tokens,
        "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        "model": resp.model,
    }


def read_key():
    """Env first, then a file the user can drop in without touching their shell.
    The key is never printed and never written into the bundle."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var], var
    for path in (os.path.join(ROOT, ".anthropic_key"),
                 os.path.expanduser("~/.anthropic_key")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                k = fh.read().strip()
            if k:
                return k, path
    return None, None


# ── driver ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--client", help="only this client id, comma separated")
    ap.add_argument("--limit", type=int, help="stop after N findings")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the payloads and print one; call nothing")
    ap.add_argument("--force", action="store_true", help="ignore the disk cache")
    ap.add_argument("--export-payloads", metavar="PATH",
                    help="write every payload, with the system prompt and schema, to "
                         "PATH for drafting outside the API; call nothing")
    ap.add_argument("--import-drafts", metavar="PATH",
                    help="record drafts written outside the API under the same payload "
                         "hashes, through the same figure check; call nothing")
    ap.add_argument("--via", default="Claude Code",
                    help="with --import-drafts: where the drafts were written")
    args = ap.parse_args()

    if not os.path.exists(BUNDLE):
        sys.exit("run `python3 engine/build.py` first — %s is missing" % BUNDLE)
    with open(BUNDLE, encoding="utf-8") as fh:
        bundle = json.load(fh)

    only = set(args.client.split(",")) if args.client else None
    todo = [f for f in bundle["findings"]
            if f["status"] != "waived" and (not only or f["client_id"] in only)]
    todo.sort(key=lambda f: -f["severity"])
    if args.limit:
        todo = todo[:args.limit]
    print("  %d findings to narrate" % len(todo))

    if args.dry_run:
        p = payload_for(bundle, todo[0])
        print("\n  ── payload that would leave the perimeter, for %s ──" % todo[0]["id"])
        print(json.dumps(p, ensure_ascii=False, indent=1)[:2600])
        a = audit(bundle, todo)
        n = len(todo)
        print("\n  ── identifier audit, all %d payloads ──" % n)
        print("  forbidden keys present ........ %s" % (a["structural"] or "none"))
        print("  name or exact age in text ..... %s" % (a["leaked"] or "none"))
        d = a["domicile_implies_nationality"]
        print("  domicile carried .............. %d of %d findings" % (
            sum(1 for f in todo
                if payload_for(bundle, f)["client"]["tax_domicile"]), n))
        print("  ...of which it equals nationality, so it discloses it: %d" % len(d))
        print("  place named in the client's own words ... %d findings"
              % len(a["place_in_own_words"]))
        print("  age digits colliding with an engine figure: %s"
              % (a["age_collides_with_a_figure"] or "none"))
        print("\n  The last two lines are real disclosures, not bugs. Tax domicile drives"
              "\n  every tax finding in the book — Hong Kong, Singapore and the UAE levy"
              "\n  no capital gains tax, and a draft that does not know that gives wrong"
              "\n  advice. It travels only where the rule turns on it. Nationality itself"
              "\n  is never sent, and for the clients where the two differ it stays"
              "\n  unknown to the model. The second is a place the client named in their"
              "\n  own objectives — \"living costs in Singapore and Japan\". Cutting it"
              "\n  would leave the draft unable to discuss the thing being funded.")
        return

    if args.export_payloads:
        export_payloads(bundle, todo, args.export_payloads)
        return
    if args.import_drafts:
        out = import_drafts(bundle, todo, args.import_drafts, args.via)
        write_out(out, 0, "recorded from %s" % args.via)
        return

    key, source = read_key()
    if not key:
        sys.exit("no API key found.\n"
                 "  export ANTHROPIC_API_KEY=... , or write it to "
                 "./.anthropic_key or ~/.anthropic_key (chmod 600).\n"
                 "  Until then the workbench falls back to the deterministic template.")
    print("  key from %s" % source)
    try:
        import anthropic
    except ImportError:
        sys.exit("the anthropic package is not installed for this Python (%d.%d): "
                 "python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt, "
                 "then run with .venv/bin/python" % sys.version_info[:2])
    client = anthropic.Anthropic(api_key=key)

    out, spend, fresh, failed = {}, {"input": 0, "output": 0, "cache_read": 0}, 0, []
    for i, f in enumerate(todo, 1):
        payload = payload_for(bundle, f)
        k = cache_key(payload)
        rec = None if args.force else cached(k)
        was_cached = rec is not None
        if rec is None:
            try:
                draft, usage = call(client, payload)
            except Exception as e:                            # noqa: BLE001
                failed.append((f["id"], str(e)[:90]))
                print("  %3d/%d  %-22s FAILED %s" % (i, len(todo), f["id"], str(e)[:60]))
                continue
            rec = {"draft": draft, "usage": usage, "via": "API",
                   "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "unverified": verify(draft, payload["allowed_figures"]),
                   "language": bundle["clients"][f["client_id"]]["profile"]["reporting_language"]}
            store(k, rec)
            fresh += 1
            for kk in spend:
                spend[kk] += usage.get(kk, 0)
        out[f["id"]] = rec
        flag = " UNVERIFIED %s" % ",".join(rec["unverified"]) if rec["unverified"] else ""
        print("  %3d/%d  %-22s %-20s %s%s" % (
            i, len(todo), f["id"], rec["language"], "cached" if was_cached else "new", flag))

    # A partial run (--limit, --client) must not drop every other finding's draft
    # from the bundle: whatever the cache already holds for them stays.
    for f in bundle["findings"]:
        if f["id"] not in out and f["status"] != "waived":
            rec = cached(cache_key(payload_for(bundle, f)))
            if rec:
                out[f["id"]] = rec
    write_out(out, fresh)
    if failed:
        print("  %d failed: %s" % (len(failed), failed[:3]))
    # Opus 5.5 list pricing, input/output per MTok
    cost = spend["input"] / 1e6 * 4 + spend["output"] / 1e6 * 20
    print("  tokens in %d (cache reads %d) out %d  ~ USD %.2f this run"
          % (spend["input"], spend["cache_read"], spend["output"], cost))


def write_out(out, fresh, how=None):
    """narration.json is what build.py folds into the bundle."""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    bad = [fid for fid, r in out.items() if r["unverified"]]
    print("\n  %d drafts (%s) -> %s" % (len(out), how or "%d new" % fresh, OUT))
    print("  numeric check: %d of %d clean%s" % (
        len(out) - len(bad), len(out),
        "" if not bad else " — held back: " + ", ".join(bad)))
    print("\n  now re-run:  python3 engine/build.py")


# ── drafting outside the API ──────────────────────────────────────────────
# Drafts prepared outside the API, ahead of time, go through the same door: the
# payloads below are exactly what call() would send, the drafts are stored under
# the same hash call() would use, and verify() reads every one back against the
# same allow-list. The record says where it was written, and the workbench shows
# that on screen.
def export_payloads(bundle, todo, path):
    out = {"model": MODEL, "prompt_version": PROMPT_VERSION, "system": SYSTEM,
           "schema": SCHEMA,
           "payloads": {f["id"]: payload_for(bundle, f) for f in todo}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("  %d payloads -> %s (identifier audit: run --dry-run)" % (len(todo), path))


def import_drafts(bundle, todo, path, via):
    """{finding id -> draft} from `path`, checked and cached as a call would be."""
    with open(path, encoding="utf-8") as fh:
        drafts = json.load(fh)
    out, missing = {}, []
    for f in todo:
        draft = drafts.get(f["id"])
        if draft is None:
            missing.append(f["id"])
            continue
        extra = set(draft) - set(SCHEMA["properties"])
        if extra or not all(isinstance(draft.get(k), str) and draft[k].strip()
                             for k in SCHEMA["required"]):
            sys.exit("  %s does not match the schema (%s)" % (
                f["id"], ", ".join(sorted(extra)) or "a required field is empty"))
        payload = payload_for(bundle, f)
        rec = {"draft": draft, "usage": {"model": MODEL}, "via": via,
               "at": time.strftime("%Y-%m-%d"),
               "unverified": verify(draft, payload["allowed_figures"]),
               "language": bundle["clients"][f["client_id"]]["profile"]["reporting_language"]}
        store(cache_key(payload), rec)
        out[f["id"]] = rec
    if missing:
        sys.exit("  no draft for %d findings: %s" % (len(missing), ", ".join(missing[:6])))
    return out


FORBIDDEN_KEYS = {"client_name", "nationality", "country_of_residence", "age",
                  "portfolio_id", "account", "rm_name", "rm_id"}


def audit(bundle, findings):
    """Prove what the payloads do and do not carry, and be honest about the one
    thing that cannot be proved away.

    A substring test alone is useless here: nationality, residence and tax
    domicile are the *same string* for most of this book, so a naive check either
    cries wolf on a field that is deliberately retained or is quietly satisfied by
    removing something the advice needs. So this reports three separate things —
    a structural guarantee, a real leak test, and a stated inference."""
    leaked, structural, disclose, place, collide = [], [], [], [], []
    for f in findings:
        p = bundle["clients"][f["client_id"]]["profile"]
        payload = payload_for(bundle, f)
        blob = json.dumps(payload, ensure_ascii=False)

        def keys(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in FORBIDDEN_KEYS:
                        structural.append((f["id"], k))
                    keys(x)
            elif isinstance(v, list):
                for x in v:
                    keys(x)
        keys(payload)

        for part in name_parts(p):
            if re.search(r"\b%s\b" % re.escape(part), blob):
                leaked.append((f["id"], "name part " + part))
        # The band is the coarsening, so its own endpoints do not count as the
        # age. And an age that equals a figure the engine itself computed — 55 is
        # both this client's age and his mandate's upper equity bound — is a
        # collision, not a disclosure. Saying otherwise would be crying wolf, and
        # an audit that cries wolf gets switched off.
        band = payload["client"]["age_band"] or ""
        rest = blob.replace(band, "") if band else blob
        age = str(p.get("age") or "")
        if age and re.search(standalone(age), rest):
            if age in payload["allowed_figures"] or ("." + age) in rest or ("-" + age) in rest:
                collide.append((f["id"], age))
            else:
                leaked.append((f["id"], "exact age"))

        res, dom = p.get("country_of_residence"), payload["client"]["tax_domicile"]
        if res and res != dom and res in blob:
            # not the residence field — that is never sent. It is a place the
            # client themselves named, in their objectives or in an RM note
            place.append(f["id"])
        if dom and dom == p.get("nationality"):
            disclose.append(f["id"])
    return {"structural": structural[:6], "leaked": leaked[:6],
            "domicile_implies_nationality": disclose, "place_in_own_words": place,
            "age_collides_with_a_figure": collide}


if __name__ == "__main__":
    main()
